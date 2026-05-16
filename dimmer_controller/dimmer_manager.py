"""
DimmerManager — integrates DimmerController into the activity recognition pipeline.

Responsibilities:
- Optional connection: if the Arduino is absent the system keeps running.
- Activity-change detection: sends a serial command only when the stable
  activity label changes, avoiding redundant serial writes.
- Maps activity labels → behavior strings and brightness values from config.
- All serial I/O is executed in a background daemon thread so the camera /
  display loop is never blocked by serial readline() latency.
"""

import queue
import threading
import time

import config
from dimmer_controller.controller import DimmerController
from dimmer_controller.lux_controller import LuxController


class _SerialWorker:
    """
    Background thread that drains a command queue and executes serial I/O.
    The main loop enqueues work and returns immediately; this thread does
    the actual blocking serial.write() / serial.readline() calls.
    """

    # Sentinel pushed to the queue to ask the thread to exit cleanly.
    _STOP = object()

    def __init__(self, controller: DimmerController) -> None:
        self._controller = controller
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, name="dimmer-serial", daemon=True
        )
        self._thread.start()

    def enqueue(self, fn) -> None:
        """Enqueue a zero-argument callable.  Returns immediately."""
        self._queue.put_nowait(fn)

    def stop(self) -> None:
        """Ask the worker thread to exit and wait up to 0.5 s."""
        self._queue.put_nowait(self._STOP)
        self._thread.join(timeout=0.5)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is self._STOP:
                break
            try:
                item()
            except Exception as exc:
                print(f"[DimmerWorker] serial error: {exc}")


class DimmerManager:
    """
    Thin wrapper around DimmerController that adds:
      - Graceful fallback (no crash if Arduino is disconnected)
      - Change-only updates (command sent only when activity changes)
      - Config-driven behavior/brightness mapping
    """

    def __init__(self) -> None:
        self._controller: DimmerController | None = None
        self._worker: _SerialWorker | None = None
        self._last_activity: str | None = None
        self._available: bool = False
        self._last_keepalive: float = 0.0
        # Keepalive interval must be safely below the firmware COMMAND_TIMEOUT (60s)
        self._keepalive_interval: float = 30.0
        # Commit delay — a new activity must persist this long before dimmer acts.
        # Prevents flickering when the smoother oscillates between two activities.
        self._commit_delay: float = getattr(config, "DIMMER_COMMIT_DELAY", 3.0)
        self._pending_activity: str | None = None
        self._pending_since: float = 0.0

        # Idle auto-off tracking
        self._idle_since: float | None = None
        self._auto_off_active: bool = False

        # Closed-loop lux controller
        self._lux_ctrl = LuxController()

        # Photoresistor polling
        self._photoresistor_lux: float = 0.0
        self._last_photoresistor_poll: float = 0.0
        self._photoresistor_enabled = getattr(config, "PHOTORESISTOR_ENABLED", False)

        if not config.DIMMER_ENABLED:
            print("[Dimmer] Disabled in config.")
            return

        try:
            self._controller = DimmerController(
                port=config.DIMMER_PORT,
                baud=config.DIMMER_BAUD,
            )
            self._worker = _SerialWorker(self._controller)
            self._available = True
            print(f"[Dimmer] Connected on {config.DIMMER_PORT}")
        except Exception as exc:
            print(
                f"[Dimmer] WARNING — Arduino not found on {config.DIMMER_PORT}: {exc}\n"
                f"          The system will run without dimmer control.\n"
                f"          Update DIMMER_PORT in config.py once the device is connected."
            )

    # ------------------------------------------------------------------
    def update(self, activity: str, current_lux: float = 0.0) -> bool:
        """
        Evaluate dimmer output for the current stable *activity* and
        *current_lux* (raw camera-estimated lux from ``_estimate_lux()``).

        On the first call after an activity commit, brightness is seeded to
        the midpoint of the IES target range for that activity.  On every
        subsequent call the LuxController nudges brightness up or down in
        LUX_STEP_SIZE increments every LUX_CONTROL_INTERVAL seconds until
        the calibrated lux lands inside the target band.

        Returns True if a serial command was dispatched, False otherwise.
        """
        if not self._available or self._controller is None:
            return False

        now = time.monotonic()

        # ------------------------------------------------------------------
        # Idle auto-off: if the activity has been "Idle" continuously for
        # IDLE_AUTO_OFF_SECONDS, fade the light fully off.
        # ------------------------------------------------------------------
        auto_off_enabled = getattr(config, "IDLE_AUTO_OFF_ENABLED", False)
        auto_off_seconds = getattr(config, "IDLE_AUTO_OFF_SECONDS", 120.0)

        if activity == "Idle":
            if self._idle_since is None:
                self._idle_since = now           # start idle timer
            if auto_off_enabled and not self._auto_off_active:
                if now - self._idle_since >= auto_off_seconds:
                    try:
                        self._auto_off_active = True
                        self._last_activity = "Idle"
                        self._pending_activity = None
                        def _send_auto_off():
                            response = self._controller.send_command("off", 0)
                            print(f"[Dimmer] Idle auto-off triggered after {auto_off_seconds}s | response={response!r}")
                        self._worker.enqueue(_send_auto_off)
                        return True
                    except Exception as exc:
                        print(f"[Dimmer] ERROR queuing auto-off command: {exc}")
                        self._available = False
                        return False
        else:
            # Non-idle activity: reset idle tracking so light comes back on
            self._idle_since = None
            self._auto_off_active = False

        # ------------------------------------------------------------------
        # Standard change-detection with commit delay
        # ------------------------------------------------------------------
        if activity == self._last_activity:
            self._pending_activity = None  # committed already; reset pending
            # Activity is stable — run one lux-controller tick
            return self._adjust_lux(activity, current_lux)

        # Track how long this candidate activity has been continuously requested
        if activity != self._pending_activity:
            # New candidate — start the hold timer
            self._pending_activity = activity
            self._pending_since = now
            return False

        if now - self._pending_since < self._commit_delay:
            return False  # Not stable long enough yet

        # Activity has been stable for commit_delay — seed the lux controller
        # to the midpoint of the IES range and send the initial command.
        behavior = config.DIMMER_BEHAVIOR.get(activity, "idle")
        lux_range = config.ACTIVITY_LUX_RANGE.get(activity, (100, 500))
        self._lux_ctrl.set_initial(lux_range)
        brightness = self._lux_ctrl.brightness

        try:
            self._last_activity = activity
            self._pending_activity = None
            def _send(_behavior=behavior, _brightness=brightness, _activity=activity):
                response = self._controller.send_command(_behavior, _brightness)
                print(f"[Dimmer] {_activity!r} → behavior={_behavior!r} brightness={_brightness} (IES seed) | response={response!r}")
            self._worker.enqueue(_send)
            return True
        except Exception as exc:
            print(f"[Dimmer] ERROR queuing command: {exc}")
            self._available = False  # Stop retrying after a failure
            return False

        # ------------------------------------------------------------------
        # After a commit, check whether the lux controller wants to nudge
        # brightness on this tick (activity already stable from here on).
        # Falls through to the continuous adjustment block below.

    # ------------------------------------------------------------------
    def _adjust_lux(self, activity: str, current_lux: float) -> bool:
        """
        Called every frame when *activity* is already the committed label.
        Runs one lux-controller tick and dispatches a serial command if
        brightness changed.
        """
        if not self._available or self._controller is None:
            return False

        lux_range = config.ACTIVITY_LUX_RANGE.get(activity, (100, 500))
        brightness, changed = self._lux_ctrl.compute(current_lux, lux_range)
        if not changed:
            return False

        behavior = config.DIMMER_BEHAVIOR.get(activity, "idle")
        try:
            def _send(_b=behavior, _br=brightness, _a=activity):
                response = self._controller.send_command(_b, _br)
                print(f"[Dimmer] lux-adjust {_a!r} → behavior={_b!r} brightness={_br} | response={response!r}")
            self._worker.enqueue(_send)
            return True
        except Exception as exc:
            print(f"[Dimmer] ERROR queuing lux-adjust: {exc}")
            self._available = False
            return False

    # ------------------------------------------------------------------
    def poll_photoresistor(self) -> float:
        """
        Poll Arduino for photoresistor ADC reading and convert to lux.
        Returns the calibrated lux value, or 0.0 if polling fails.
        Polls periodically based on PHOTORESISTOR_POLL_INTERVAL.
        """
        if not self._available or self._controller is None or not self._photoresistor_enabled:
            return 0.0

        now = time.monotonic()
        poll_interval = getattr(config, "PHOTORESISTOR_POLL_INTERVAL", 0.5)
        
        if now - self._last_photoresistor_poll < poll_interval:
            return self._photoresistor_lux

        try:
            # Send PHOTOLUX? command and get raw ADC reading
            raw_adc = self._controller.send_raw_command("PHOTOLUX?")
            if raw_adc is None:
                return self._photoresistor_lux
            
            # Parse response: "PHOTOLUX:<value>"
            if isinstance(raw_adc, str) and ":" in raw_adc:
                parts = raw_adc.split(":")
                if len(parts) == 2:
                    raw_adc = int(parts[1].strip())
            else:
                raw_adc = int(raw_adc) if isinstance(raw_adc, str) else raw_adc

            # Convert raw ADC to lux using calibration points
            self._photoresistor_lux = self._adc_to_lux(raw_adc)
            self._last_photoresistor_poll = now
            
        except Exception as exc:
            print(f"[Photoresistor] ERROR polling ADC: {exc}")

        return self._photoresistor_lux

    # ------------------------------------------------------------------
    def _adc_to_lux(self, raw_adc: int) -> float:
        """
        Convert raw ADC reading (0-1023) to lux using linear interpolation
        of calibration points from config.PHOTORESISTOR_CALIBRATION_POINTS.
        """
        cal_points = getattr(config, "PHOTORESISTOR_CALIBRATION_POINTS", {100: 20, 500: 100, 1000: 1000})
        if not cal_points or len(cal_points) < 1:
            return 0.0

        # Sort calibration points by ADC value
        sorted_points = sorted(cal_points.items())

        # Clamp raw_adc to calibration range
        if raw_adc <= sorted_points[0][0]:
            return sorted_points[0][1]
        if raw_adc >= sorted_points[-1][0]:
            return sorted_points[-1][1]

        # Linear interpolation between two nearest calibration points
        for i in range(len(sorted_points) - 1):
            adc1, lux1 = sorted_points[i]
            adc2, lux2 = sorted_points[i + 1]
            if adc1 <= raw_adc <= adc2:
                # Linear interpolation
                t = (raw_adc - adc1) / (adc2 - adc1) if adc2 != adc1 else 0.0
                lux = lux1 + t * (lux2 - lux1)
                return lux

        return 0.0

    # ------------------------------------------------------------------
    def keepalive(self) -> None:
        """
        Send a PING every keepalive_interval seconds to prevent the firmware
        safety timeout from cutting the lights during stable activity periods.
        Call this from the main loop on every frame.
        """
        if not self._available or self._controller is None:
            return
        if time.monotonic() - self._last_keepalive < self._keepalive_interval:
            return
        self._last_keepalive = time.monotonic()
        try:
            self._worker.enqueue(self._controller.ping)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def ping(self) -> bool:
        """Returns True if the Arduino is still responding."""
        if not self._available or self._controller is None:
            return False
        try:
            return self._controller.ping()
        except Exception:
            return False

    # ------------------------------------------------------------------
    def set_full_brightness_test(self, duration_seconds: float | None = None) -> bool:
        """
        Send a single full-brightness command for CLI test mode.
        Uses synchronous serial writes for deterministic test completion.
        """
        if not self._available or self._controller is None:
            print("[DimmerTest] Arduino not available for full-brightness test.")
            return False

        self._enter_test_mode()
        behavior = getattr(config, "DIMMER_TEST_BEHAVIOR", "writing")
        ok = self._send_command_sync(behavior, 100, "full-brightness")
        if not ok:
            return False
        return self._hold_test_duration(duration_seconds)

    # ------------------------------------------------------------------
    def run_dimm_ramp_test(self, duration_seconds: float | None = None) -> bool:
        """
        Run a deterministic 0->100->0 brightness ramp for CLI test mode.
        Uses synchronous serial writes with fixed dwell time per step.
        """
        if not self._available or self._controller is None:
            print("[DimmerTest] Arduino not available for ramp test.")
            return False

        self._enter_test_mode()

        behavior = getattr(config, "DIMMER_TEST_BEHAVIOR", "writing")
        step = max(1, int(getattr(config, "DIMMER_TEST_STEP", 10)))
        dwell = max(0.0, float(getattr(config, "DIMMER_TEST_DWELL_SECONDS", 0.4)))

        up = list(range(0, 101, step))
        if up[-1] != 100:
            up.append(100)
        sequence = up + list(reversed(up[:-1]))

        end_time = None
        if duration_seconds is not None and duration_seconds > 0:
            end_time = time.monotonic() + duration_seconds

        if end_time is None:
            print(
                f"[DimmerTest] Ramp test started | points={len(sequence)} step={step}% dwell={dwell:.2f}s"
            )
            for idx, brightness in enumerate(sequence):
                if not self._send_command_sync(behavior, brightness, "ramp"):
                    return False
                if idx < len(sequence) - 1 and dwell > 0.0:
                    time.sleep(dwell)
            print("[DimmerTest] Ramp test completed.")
            return True

        print(
            "[DimmerTest] Timed ramp test started | "
            f"duration={duration_seconds:.1f}s step={step}% dwell={dwell:.2f}s"
        )
        while time.monotonic() < end_time:
            for idx, brightness in enumerate(sequence):
                if time.monotonic() >= end_time:
                    break
                if not self._send_command_sync(behavior, brightness, "ramp"):
                    return False
                if idx < len(sequence) - 1 and dwell > 0.0:
                    remaining = end_time - time.monotonic()
                    if remaining > 0:
                        time.sleep(min(dwell, remaining))

        print("[DimmerTest] Timed ramp test completed.")
        return True

    # ------------------------------------------------------------------
    def _hold_test_duration(self, duration_seconds: float | None) -> bool:
        if duration_seconds is None or duration_seconds <= 0:
            return True
        if self._controller is None:
            return False

        end_time = time.monotonic() + duration_seconds
        print(f"[DimmerTest] Holding test output for {duration_seconds:.1f}s")
        while time.monotonic() < end_time:
            remaining = end_time - time.monotonic()
            try:
                self._controller.ping()
            except Exception as exc:
                print(f"[DimmerTest] hold ping failed: {exc}")
                self._available = False
                return False
            time.sleep(min(5.0, max(0.1, remaining)))
        return True

    # ------------------------------------------------------------------
    def _enter_test_mode(self) -> None:
        """Stop async worker so test-mode serial writes are fully deterministic."""
        if self._worker is not None:
            try:
                self._worker.stop()
            except Exception:
                pass
            self._worker = None

    # ------------------------------------------------------------------
    def _send_command_sync(self, behavior: str, brightness: int, label: str) -> bool:
        if self._controller is None:
            return False
        try:
            response = self._controller.send_command(behavior, brightness)
            print(
                f"[DimmerTest] {label}: behavior={behavior!r} brightness={brightness} | response={response!r}"
            )
            return True
        except Exception as exc:
            print(f"[DimmerTest] {label} failed: {exc}")
            self._available = False
            return False

    # ------------------------------------------------------------------
    @property
    def current_brightness(self) -> int:
        """Current brightness value (0–100) as tracked by the lux controller."""
        return self._lux_ctrl.brightness

    # ------------------------------------------------------------------
    def disconnect(self) -> None:
        """
        Notify the Arduino that Python is shutting down so it fades the
        lights off immediately rather than waiting for the 60 s safety timeout.
        """
        if not self._available or self._controller is None:
            return
        try:
            # Stop the background worker first so no queued commands race
            # with the disconnect write.
            if self._worker is not None:
                self._worker.stop()
                self._worker = None
            self._controller.ser.write(b"DISCONNECT\n")
            # Small pause so the Arduino can process the command before the
            # serial port is closed (which triggers an Arduino reset anyway).
            time.sleep(0.2)
            print("[Dimmer] Disconnect signal sent — lights fading off.")
        except Exception:
            pass

    # ------------------------------------------------------------------
    @property
    def is_available(self) -> bool:
        return self._available
