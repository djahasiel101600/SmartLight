"""
DimmerManager — integrates DimmerController into the activity recognition pipeline.

Responsibilities:
- Optional connection: if the Arduino is absent the system keeps running.
- Activity-change detection: sends a serial command only when the stable
  activity label changes, avoiding redundant serial writes.
- Maps activity labels → behavior strings and brightness values from config.
"""

import time

import config
from dimmer_controller.controller import DimmerController


class DimmerManager:
    """
    Thin wrapper around DimmerController that adds:
      - Graceful fallback (no crash if Arduino is disconnected)
      - Change-only updates (command sent only when activity changes)
      - Config-driven behavior/brightness mapping
    """

    def __init__(self) -> None:
        self._controller: DimmerController | None = None
        self._last_activity: str | None = None
        self._available: bool = False
        self._last_keepalive: float = 0.0
        # Keepalive interval must be safely below the firmware COMMAND_TIMEOUT (60s)
        self._keepalive_interval: float = 30.0

        if not config.DIMMER_ENABLED:
            print("[Dimmer] Disabled in config.")
            return

        try:
            self._controller = DimmerController(
                port=config.DIMMER_PORT,
                baud=config.DIMMER_BAUD,
            )
            self._available = True
            print(f"[Dimmer] Connected on {config.DIMMER_PORT}")
        except Exception as exc:
            print(
                f"[Dimmer] WARNING — Arduino not found on {config.DIMMER_PORT}: {exc}\n"
                f"          The system will run without dimmer control.\n"
                f"          Update DIMMER_PORT in config.py once the device is connected."
            )

    # ------------------------------------------------------------------
    def update(self, activity: str) -> bool:
        """
        Send a dimmer command if *activity* differs from the last sent activity.

        Returns True if a command was dispatched, False otherwise.
        """
        if not self._available or self._controller is None:
            return False

        if activity == self._last_activity:
            return False  # No change — skip serial write

        behavior = config.DIMMER_BEHAVIOR.get(activity, "idle")
        brightness = config.DIMMER_BRIGHTNESS.get(activity, 20)

        try:
            response = self._controller.send_command(behavior, brightness)
            self._last_activity = activity
            print(f"[Dimmer] {activity!r} → behavior={behavior!r} brightness={brightness} | response={response!r}")
            return True
        except Exception as exc:
            print(f"[Dimmer] ERROR sending command: {exc}")
            self._available = False  # Stop retrying after a failure
            return False

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
        try:
            self._controller.ping()
            self._last_keepalive = time.monotonic()
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
    @property
    def is_available(self) -> bool:
        return self._available
