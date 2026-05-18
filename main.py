"""
Main entry point for the Activity Recognition System.

Pipeline per frame:
    CameraCapture → ROIExtractor → DecisionEngine
        → [OpenAIVisionClient (background thread)] → ActivitySmoother → StructuredLogger
        → cv2.imshow overlay

The OpenAI API call runs in a daemon thread so the camera feed and display
loop are never blocked by network latency.

Usage:
    Set the OPENAI_API_KEY environment variable, then run:
        python main.py

    Headless mode (no display window):
        python main.py --headless

    Test mode (dimmer only):
        python main.py --test-dimm
        python main.py --test-full-brightness
        python main.py --test-dimm --test-seconds 30

Press  Q  in the display window, or Ctrl+C in the terminal, to exit.
"""

import argparse
import sys
import threading
import time

import cv2

# --- Path fix so sub-packages can resolve `config` regardless of cwd ---
import os
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import config
from ai.openai_client import OpenAIVisionClient
from cache.frame_cache import FrameCache
from camera.capture import CameraCapture
from camera.lambertian_estimator import LambertianLuxEstimator
from decision_engine.engine import DecisionEngine, Decision
from applog.logger import StructuredLogger
from dimmer_controller.dimmer_manager import DimmerManager
from dimmer_controller.lux_controller import _lux_to_brightness
from preprocessing.motion_detector import MotionDetector
from preprocessing.roi_extractor import ROIExtractor
from similarity.comparator import SimilarityComparator
from stability.activity_smoother import ActivitySmoother


# ---------------------------------------------------------------------------
# Overlay helpers
# ---------------------------------------------------------------------------
_ACTIVITY_COLORS = {
    "Reading Book/s": (0,   200, 255),
    "Using Cellphone": (255, 150,   0),
    "Using Laptop":   (0,   255, 100),
    "Idle":           (160, 160, 160),
}
_DEFAULT_COLOR = (200, 200, 200)

# UI palette (BGR)
_BG_DARK    = (20,  20,  40)
_TEXT_PRI   = (240, 240, 240)
_TEXT_SEC   = (150, 155, 170)
_ACCENT_YEL = (50,  220, 255)   # lux / sun tint
_ACCENT_AMB = (50,  190, 255)   # dimmer / bulb tint

_FONT      = cv2.FONT_HERSHEY_SIMPLEX
_FONT_BOLD = cv2.FONT_HERSHEY_DUPLEX


def _estimate_lux(frame) -> float:
    """
    Estimate relative ambient lux from average frame brightness.
    Not calibrated; useful as a lighting trend indicator.
      avg=0   →    0 lux
      avg=128 → ~150 lux
      avg=255 → 1000 lux
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    avg = float(gray.mean())
    return round((avg / 255.0) ** 1.8 * 1000.0, 1)


def _pill(frame, text: str, origin, color, scale: float = 0.52, thickness: int = 1) -> int:
    """Draw a filled pill label; returns the x-coordinate after the pill."""
    x, y = origin
    pad_x, pad_y = 10, 5
    (tw, th), _ = cv2.getTextSize(text, _FONT_BOLD, scale, thickness)
    rx1, ry1 = x, y - th - pad_y
    rx2, ry2 = x + tw + pad_x * 2, y + pad_y
    cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), color, -1)
    cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), _TEXT_PRI, 1)
    text_color = (10, 10, 10) if sum(color) > 400 else _TEXT_PRI
    cv2.putText(frame, text, (x + pad_x, y), _FONT_BOLD, scale,
                text_color, thickness, cv2.LINE_AA)
    return rx2 + 8


# ---------------------------------------------------------------------------
# Background API worker — prevents API latency from blocking the camera loop
# ---------------------------------------------------------------------------
class _AsyncAPIWorker:
    """
    Runs a single OpenAI classify() call in a daemon thread.

    Usage:
        worker = _AsyncAPIWorker(ai_client)
        worker.submit(roi_frame)          # starts background thread
        ...                               # main loop keeps running
        if worker.result_ready:
            result = worker.take_result() # consume result, resets state
    """

    def __init__(self, ai_client: "OpenAIVisionClient") -> None:  # noqa: F821
        self._client = ai_client
        self._lock = threading.Lock()
        self._busy = False
        self._result = None
        self._latency_ms: float = 0.0

    def submit(self, frame) -> None:
        """Kick off a classify call in the background. No-op if already running."""
        with self._lock:
            if self._busy:
                return
            self._busy = True
            self._result = None

        thread = threading.Thread(target=self._run, args=(frame.copy(),), daemon=True)
        thread.start()

    def _run(self, frame) -> None:
        t = time.monotonic()
        result = self._client.classify(frame)
        latency = (time.monotonic() - t) * 1000
        with self._lock:
            self._result = result
            self._latency_ms = latency
            self._busy = False

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._busy

    @property
    def result_ready(self) -> bool:
        with self._lock:
            return self._result is not None and not self._busy

    def take_result(self):
        """Consume and return the finished result (resets to idle)."""
        with self._lock:
            result = self._result
            latency = self._latency_ms
            self._result = None
            return result, latency


def _draw_overlay(
    frame,
    activity: str,
    confidence: int,
    source: str,
    bbox,
    motion: bool,
    api_busy: bool,
    fps: float,
    lux: float,
    dimmer_pct: int,
) -> None:
    import math
    h, w = frame.shape[:2]
    act_color = _ACTIVITY_COLORS.get(activity, _DEFAULT_COLOR)

    # ------------------------------------------------------------------
    # Bounding box: thin rect + L-corner accents + floating pill label
    # ------------------------------------------------------------------
    if bbox is not None:
        x1, y1, x2, y2 = bbox
        cv2.rectangle(frame, (x1, y1), (x2, y2), act_color, 1)
        clen = 14
        for cx, cy, dx, dy in [(x1, y1, 1, 1), (x2, y1, -1, 1),
                                (x1, y2, 1, -1), (x2, y2, -1, -1)]:
            cv2.line(frame, (cx, cy), (cx + dx * clen, cy), act_color, 3)
            cv2.line(frame, (cx, cy), (cx, cy + dy * clen), act_color, 3)
        tag_y = max(y1 - 6, 22)
        _pill(frame, f" {activity} ", (x1, tag_y), act_color, scale=0.44)

    # ------------------------------------------------------------------
    # Header bar  (semi-transparent)
    # ------------------------------------------------------------------
    header_h = 38
    ov = frame.copy()
    cv2.rectangle(ov, (0, 0), (w, header_h), _BG_DARK, -1)
    cv2.addWeighted(ov, 0.78, frame, 0.22, 0, frame)

    # Live indicator dot
    cv2.circle(frame, (14, header_h // 2), 6, (0, 220, 80), -1)
    cv2.putText(frame, "SmartLight AI", (28, 25),
                _FONT_BOLD, 0.55, _TEXT_PRI, 1, cv2.LINE_AA)

    fps_txt = f"FPS: {fps:.1f}"
    (fw, _), _ = cv2.getTextSize(fps_txt, _FONT, 0.46, 1)
    cv2.putText(frame, fps_txt, (w - fw - 10, 25),
                _FONT, 0.46, _TEXT_SEC, 1, cv2.LINE_AA)

    # ------------------------------------------------------------------
    # Bottom info panel  (semi-transparent, 2 rows)
    # ------------------------------------------------------------------
    panel_h = 72
    panel_y = h - panel_h
    ov2 = frame.copy()
    cv2.rectangle(ov2, (0, panel_y), (w, h), _BG_DARK, -1)
    cv2.addWeighted(ov2, 0.80, frame, 0.20, 0, frame)
    cv2.line(frame, (0, panel_y), (w, panel_y), (60, 60, 90), 1)

    # Row 1 — activity pill | confidence | source tag
    row1_y = panel_y + 26
    nx = _pill(frame, f"  {activity}  ", (8, row1_y), act_color, scale=0.52)
    cv2.putText(frame, f"Conf: {confidence}%", (nx, row1_y),
                _FONT, 0.48, _TEXT_SEC, 1, cv2.LINE_AA)

    src_col = (100, 220, 100) if source == "api" else (130, 130, 210)
    src_txt = f"[{source.upper()}]"
    (sw, _), _ = cv2.getTextSize(src_txt, _FONT, 0.44, 1)
    cv2.putText(frame, src_txt, (w - sw - 10, row1_y),
                _FONT, 0.44, src_col, 1, cv2.LINE_AA)
    if api_busy:
        cv2.circle(frame, (w - sw - 22, row1_y - 6), 5, (0, 220, 255), -1)

    # Row 2 — lux | dimmer brightness | motion
    row2_y = panel_y + 57

    # Sun icon (circle + 8 rays)
    sx, sy = 14, row2_y - 7
    cv2.circle(frame, (sx, sy), 5, _ACCENT_YEL, -1)
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        cv2.line(frame,
                 (int(sx + 8  * math.cos(rad)), int(sy + 8  * math.sin(rad))),
                 (int(sx + 11 * math.cos(rad)), int(sy + 11 * math.sin(rad))),
                 _ACCENT_YEL, 1)
    lux_txt = f"{lux:.0f} lx"
    cv2.putText(frame, lux_txt, (sx + 16, row2_y),
                _FONT, 0.50, _ACCENT_YEL, 1, cv2.LINE_AA)

    # Bulb icon + dimmer %
    (lw, _), _ = cv2.getTextSize(lux_txt, _FONT, 0.50, 1)
    bx, by = sx + 16 + lw + 20, row2_y - 7
    cv2.circle(frame, (bx, by), 6, _ACCENT_AMB, 1)
    cv2.line(frame, (bx - 3, by + 6), (bx + 3, by + 6), _ACCENT_AMB, 2)
    cv2.line(frame, (bx - 3, by + 9), (bx + 3, by + 9), _ACCENT_AMB, 2)
    dim_txt = f"Light: {dimmer_pct}%"
    cv2.putText(frame, dim_txt, (bx + 14, row2_y),
                _FONT, 0.50, _ACCENT_AMB, 1, cv2.LINE_AA)

    # Motion indicator
    (dw, _), _ = cv2.getTextSize(dim_txt, _FONT, 0.50, 1)
    mx = bx + 14 + dw + 20
    mot_col = (60, 60, 255) if motion else (80, 200, 80)
    cv2.circle(frame, (mx, row2_y - 7), 5, mot_col, -1)
    cv2.putText(frame, "MOTION" if motion else "STILL", (mx + 12, row2_y),
                _FONT, 0.46, mot_col, 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run(headless: bool = config.HEADLESS) -> None:
    logger = StructuredLogger()
    logger.log_startup()

    # --- Initialise modules ---
    try:
        ai_client = OpenAIVisionClient()
    except (ImportError, EnvironmentError) as exc:
        logger.log_error("Failed to initialise OpenAI client", exc)
        sys.exit(1)

    frame_cache = FrameCache(cooldown=config.API_COOLDOWN_SECONDS)
    motion_detector = MotionDetector()
    roi_extractor = ROIExtractor()
    similarity_comparator = SimilarityComparator()
    engine = DecisionEngine(motion_detector, similarity_comparator, frame_cache)
    smoother = ActivitySmoother()
    api_worker = _AsyncAPIWorker(ai_client)
    dimmer = DimmerManager()
    lux_estimator = LambertianLuxEstimator()

    try:
        camera = CameraCapture()
        camera.start()
    except RuntimeError as exc:
        logger.log_error("Camera initialisation failed", exc)
        sys.exit(1)

    logger.log_info("Camera opened. Press Q to quit.")
    logger.log_info("Bottom panel: lux estimate | light brightness % | motion status")

    # FPS rolling average over the last 30 frames
    _fps_times: list = []

    try:
        while True:
            t_start = time.monotonic()

            # 1. Capture
            frame = camera.read_frame()
            if frame is None:
                logger.log_warning("Empty frame received — skipping.")
                continue

            # FPS — rolling average over last 30 frames
            _t = time.monotonic()
            _fps_times.append(_t)
            if len(_fps_times) > 30:
                _fps_times.pop(0)
            _fps = (len(_fps_times) / (_fps_times[-1] - _fps_times[0] + 1e-9)
                    if len(_fps_times) > 1 else 0.0)

            # 2. ROI extraction
            roi, bbox = roi_extractor.extract(frame)

            # 3. Pick up finished API result (non-blocking)
            if api_worker.result_ready:
                result, api_latency_ms = api_worker.take_result()
                if result.error:
                    logger.log_error(f"API classification error: {result.error}")
                else:
                    frame_cache.update(
                        activity=result.activity,
                        confidence=result.confidence,
                        reasoning=result.reasoning,
                        frame=roi,
                        similarity_score=0.0,
                    )
                    similarity_comparator.update_reference(roi)
                    logger.log_api_call(result.activity, result.confidence, api_latency_ms)

            # 4. Decision — only dispatch if worker is free
            engine_result = engine.evaluate(roi)
            if engine_result.decision == Decision.CALL_API and not api_worker.is_busy:
                api_worker.submit(roi)
                source = "api"
            else:
                reason = "api_busy" if api_worker.is_busy else engine_result.reason
                logger.log_cache_reuse(reason, frame_cache.current.activity)
                source = "cache"

            # 5. Temporal smoothing
            cached = frame_cache.current
            stable_activity, stable_confidence = smoother.update(
                cached.activity, cached.confidence
            )

            # 6. Dimmer — lux-based closed-loop control
            # Estimate ambient lux from the camera frame using the Lambertian
            # Reflectance model (E = π × K_cal × Y_linear / (t_s × g × ρ)).
            _lux = lux_estimator.estimate(frame)
            dimmer.update(stable_activity, _lux)
            dimmer.keepalive()

            # 7. Logging
            processing_ms = (time.monotonic() - t_start) * 1000
            logger.log_activity(
                activity=stable_activity,
                confidence=stable_confidence,
                similarity_score=engine_result.similarity_score,
                source=source,
                processing_ms=processing_ms,
                reasoning=cached.reasoning,
            )

            # 8. Display
            if not headless:
                _dim_pct = _lux_to_brightness(_lux)
                try:
                    _draw_overlay(
                        frame,
                        activity=stable_activity,
                        confidence=stable_confidence,
                        source=source,
                        bbox=bbox,
                        motion=engine_result.motion_detected,
                        api_busy=api_worker.is_busy,
                        fps=_fps,
                        lux=_lux,
                        dimmer_pct=_dim_pct,
                    )
                except Exception:
                    pass  # overlay errors must not drop the camera feed
                cv2.imshow("SmartLight Activity Recognition", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    except KeyboardInterrupt:
        pass
    finally:
        dimmer.disconnect()
        camera.stop()
        roi_extractor.close()
        if not headless:
            cv2.destroyAllWindows()
        logger.log_shutdown()


def run_calibrate_lux_mode(num_samples: int = 30) -> int:
    """
    Interactive Lambertian calibration wizard.

    1. Opens the camera and shows a live preview window.
    2. Captures *num_samples* frames while displaying the running raw estimate.
    3. Freezes the last frame with an overlay prompt, then reads the meter value
       from the terminal — the window stays visible so you can keep the lux meter
       and camera pointing at the same scene while typing.
    4. Computes and prints the K_cal value to set in config.py.

    Returns a process exit code (0 = success, 1 = error).
    """
    headless: bool = config.HEADLESS

    print("\n[Calibrate] ===== Lambertian Lux Calibration Wizard =====")
    print(f"[Calibrate] CAMERA_LOCK_ENABLED = {getattr(config, 'CAMERA_LOCK_ENABLED', False)}")
    if not getattr(config, "CAMERA_LOCK_ENABLED", False):
        print(
            "[Calibrate] WARNING — CAMERA_LOCK_ENABLED is False.  Set it to True in "
            "config.py before calibrating, otherwise the estimate will be unreliable."
        )

    estimator = LambertianLuxEstimator()

    try:
        camera = CameraCapture()
        camera.start()
    except RuntimeError as exc:
        print(f"[Calibrate] ERROR — Could not open camera: {exc}")
        return 1

    print(f"[Calibrate] Camera open. Capturing {num_samples} sample frames …")
    if not headless:
        print("[Calibrate] A preview window will open. Keep it visible while taking your meter reading.")

    # Threshold below which we consider the frame too dark to be useful.
    # Y_mean is on a 0–255 scale; <8 means essentially black.
    _DARK_THRESHOLD = 8

    raw_values: list[float] = []
    y_means: list[float] = []
    last_frame = None
    attempts = 0
    too_dark_warned = False

    try:
        while len(raw_values) < num_samples:
            frame = camera.read_frame()
            attempts += 1
            if frame is None:
                if attempts > num_samples * 3:
                    print("[Calibrate] ERROR — Too many empty frames. Check camera.")
                    return 1
                time.sleep(0.05)
                continue

            import cv2 as _cv2_local
            gray = _cv2_local.cvtColor(frame, _cv2_local.COLOR_BGR2GRAY)
            y_mean = float(gray.mean())
            y_means.append(y_mean)

            raw_val = estimator.estimate_raw(frame)
            raw_values.append(raw_val)
            last_frame = frame.copy()

            # Warn once in terminal if frames are underexposed
            if not too_dark_warned and y_mean < _DARK_THRESHOLD:
                too_dark_warned = True
                print(
                    f"\n[Calibrate] WARNING — Frames are very dark (Y_mean={y_mean:.1f}/255). "
                    f"Current CAMERA_LOCK_EXPOSURE_US={getattr(config, 'CAMERA_LOCK_EXPOSURE_US', '?')} µs "
                    f"is likely too short for indoor conditions.\n"
                    f"[Calibrate] Increase CAMERA_LOCK_EXPOSURE_US in config.py "
                    f"(try 10000–30000 for indoors) and re-run --calibrate-lux.\n"
                    f"[Calibrate] Continuing anyway — K_cal result will be unreliable.\n"
                )

            if not headless:
                # Auto-brighten the preview so the user can see the scene even
                # when the sensor is underexposed.  The boost is display-only —
                # the actual measurement still uses the raw pixel values.
                if y_mean > 0:
                    boost = min(128.0 / y_mean, 8.0)  # cap at 8× to avoid noise blowup
                else:
                    boost = 1.0
                display_frame = cv2.convertScaleAbs(frame, alpha=boost, beta=0)

                collected = len(raw_values)
                running_mean = sum(raw_values) / collected

                is_dark = y_mean < _DARK_THRESHOLD
                status_color = (0, 60, 255) if is_dark else (0, 220, 255)

                cv2.putText(
                    display_frame,
                    f"Calibrating: {collected}/{num_samples} frames",
                    (10, 30), _FONT_BOLD, 0.65, status_color, 2, cv2.LINE_AA,
                )
                cv2.putText(
                    display_frame,
                    f"Raw estimate (K_cal=1.0): {running_mean:.4f} lux",
                    (10, 62), _FONT, 0.58, (200, 200, 200), 1, cv2.LINE_AA,
                )
                if boost > 1.05:
                    cv2.putText(
                        display_frame,
                        f"[Display boosted {boost:.1f}x — sensor underexposed]",
                        (10, 92), _FONT, 0.48, (0, 140, 255), 1, cv2.LINE_AA,
                    )
                if is_dark:
                    cv2.putText(
                        display_frame,
                        "Frames too dark! Increase CAMERA_LOCK_EXPOSURE_US",
                        (10, 118), _FONT, 0.48, (0, 60, 255), 1, cv2.LINE_AA,
                    )

                cv2.imshow("SmartLight — Lux Calibration", display_frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("[Calibrate] Aborted by user.")
                    return 1

            time.sleep(0.05)  # ~20 fps sampling

        # Sampling done — freeze the last frame with a prompt overlay so the
        # user can still see the scene while typing in the terminal.
        if not headless and last_frame is not None:
            avg_y = sum(y_means) / len(y_means) if y_means else 0.0
            boost = min(128.0 / avg_y, 8.0) if avg_y > 0 else 1.0
            final_preview = cv2.convertScaleAbs(last_frame, alpha=boost, beta=0)
            raw_mean_display = sum(raw_values) / len(raw_values)
            cv2.putText(
                final_preview,
                "Sampling complete!",
                (10, 30), _FONT_BOLD, 0.65, (0, 255, 100), 2, cv2.LINE_AA,
            )
            cv2.putText(
                final_preview,
                f"Raw estimate (K_cal=1.0): {raw_mean_display:.4f} lux",
                (10, 62), _FONT, 0.58, (200, 200, 200), 1, cv2.LINE_AA,
            )
            cv2.putText(
                final_preview,
                "Point lux meter at this scene,",
                (10, 96), _FONT, 0.55, (50, 220, 255), 1, cv2.LINE_AA,
            )
            cv2.putText(
                final_preview,
                "then type the reading in the terminal.",
                (10, 122), _FONT, 0.55, (50, 220, 255), 1, cv2.LINE_AA,
            )
            if boost > 1.05:
                cv2.putText(
                    final_preview,
                    f"[Display boosted {boost:.1f}x — sensor underexposed]",
                    (10, 152), _FONT, 0.48, (0, 140, 255), 1, cv2.LINE_AA,
                )
            cv2.imshow("SmartLight — Lux Calibration", final_preview)
            cv2.waitKey(1)  # pump event loop once so the window repaints

    finally:
        camera.stop()

    raw_mean = sum(raw_values) / len(raw_values)
    print(f"[Calibrate] Raw estimate (K_cal=1.0): {raw_mean:.4f} lux")
    print("[Calibrate] -----------------------------------------------")
    print("[Calibrate] Keep the camera and lux meter aimed at the same scene.")

    try:
        meter_str = input("[Calibrate] Enter lux meter reading: ").strip()
        meter_lux = float(meter_str)
    except (ValueError, EOFError):
        print("[Calibrate] ERROR — Invalid input. Aborted.")
        return 1
    finally:
        if not headless:
            cv2.destroyWindow("SmartLight — Lux Calibration")

    if meter_lux <= 0:
        print("[Calibrate] ERROR — Lux reading must be greater than 0.")
        return 1

    k_cal = meter_lux / raw_mean
    print("[Calibrate] =======================================")
    print(f"[Calibrate] Computed K_cal = {k_cal:.6f}")
    print("[Calibrate] Set this in config.py:")
    print(f"[Calibrate]   LUX_LAMBERTIAN_K_CAL: float = {k_cal:.6f}")
    print("[Calibrate] =======================================")
    return 0


def run_test_mode(
    test_dimm: bool = False,
    test_full_brightness: bool = False,
    test_lux: float | None = None,
    test_raw: int | None = None,
    test_seconds: float | None = None,
    interactive: bool = False,
) -> int:
    """Run dimmer-only diagnostics and return process exit code."""
    logger = StructuredLogger()
    logger.log_startup()
    dimmer = DimmerManager()

    try:
        if not dimmer.is_available:
            logger.log_error("Dimmer test requested but Arduino is not available.")
            return 2

        if test_dimm:
            if test_seconds is not None and test_seconds > 0:
                logger.log_info(f"Starting timed dimmer ramp test mode ({test_seconds:.1f}s).")
            else:
                logger.log_info("Starting dimmer ramp test mode.")
            ok = dimmer.run_dimm_ramp_test(duration_seconds=test_seconds)
        elif test_full_brightness:
            if test_seconds is not None and test_seconds > 0:
                logger.log_info(
                    f"Starting full-brightness dimmer test mode ({test_seconds:.1f}s)."
                )
            else:
                logger.log_info("Starting full-brightness dimmer test mode.")
            ok = dimmer.set_full_brightness_test(duration_seconds=test_seconds)
        elif test_lux is not None:
            if test_seconds is not None and test_seconds > 0:
                logger.log_info(
                    f"Starting lux target test mode (target={test_lux:.1f} lux, "
                    f"hold={test_seconds:.1f}s)."
                )
            else:
                logger.log_info(f"Starting lux target test mode (target={test_lux:.1f} lux).")
            ok = dimmer.set_target_lux_test(target_lux=test_lux, duration_seconds=test_seconds)
        elif test_raw is not None:
            if test_seconds is not None and test_seconds > 0:
                logger.log_info(
                    f"Starting raw ADC seek test (target_raw={test_raw}, "
                    f"time_limit={test_seconds:.1f}s, interactive={interactive})."
                )
            else:
                logger.log_info(
                    f"Starting raw ADC seek test (target_raw={test_raw}, "
                    f"interactive={interactive})."
                )
            ok = dimmer.seek_raw_adc_test(
                target_adc=test_raw,
                duration_seconds=test_seconds,
                interactive=interactive,
            )
        else:
            logger.log_error("No dimmer test mode selected.")
            return 2

        if ok:
            logger.log_info("Dimmer test completed successfully.")
            return 0

        logger.log_error("Dimmer test failed.")
        return 2
    finally:
        dimmer.disconnect()
        logger.log_shutdown()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Activity Recognition System")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without a display window (for Raspberry Pi SSH sessions).",
    )
    test_group = parser.add_mutually_exclusive_group()
    test_group.add_argument(
        "--calibrate-lux",
        action="store_true",
        help=(
            "Run the Lambertian lux calibration wizard. Opens the camera, captures frames, "
            "then prompts for a real lux meter reading to compute LUX_LAMBERTIAN_K_CAL."
        ),
    )
    test_group.add_argument(
        "--test-dimm",
        "--test-dim",
        dest="test_dimm",
        action="store_true",
        help="Run dimmer ramp test (0->100->0) and exit. (--test-dim is an alias)",
    )
    test_group.add_argument(
        "--test-full-brightness",
        action="store_true",
        help="Set dimmer to full brightness once and exit.",
    )
    test_group.add_argument(
        "--test-lux",
        type=float,
        default=None,
        metavar="LUX",
        help=(
            "Set dimmer to the brightness that corresponds to LUX (uses LUX_BRIGHTNESS_TABLE). "
            "Pair with --test-seconds to hold and compare photoresistor vs real lux meter."
        ),
    )
    test_group.add_argument(
        "--test-raw",
        type=int,
        default=None,
        metavar="ADC",
        help=(
            "Closed-loop seek: adjust dimmer brightness until the photoresistor reads ADC (0–1023). "
            "Add --test-seconds to cap the search time; after settling it holds and keeps printing."
        ),
    )
    parser.add_argument(
        "--calibrate-samples",
        type=int,
        default=30,
        metavar="N",
        help="Number of frames to average during --calibrate-lux (default: 30).",
    )
    parser.add_argument(
        "--test-seconds",
        type=float,
        default=None,
        help="Optional duration (seconds) for --test-dimm or --test-full-brightness.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help=(
            "Step mode for --test-raw: pause at each brightness adjustment so you can "
            "observe the photoresistor and lux meter before stepping. "
            "Press Enter (or Space+Enter) to advance, q+Enter to quit."
        ),
    )
    args = parser.parse_args()

    if args.test_seconds is not None and args.test_seconds <= 0:
        parser.error("--test-seconds must be greater than 0.")

    if args.test_seconds is not None and not (
        args.test_dimm or args.test_full_brightness
        or args.test_lux is not None or args.test_raw is not None
    ):
        parser.error(
            "--test-seconds requires --test-dimm, --test-full-brightness, "
            "--test-lux, or --test-raw."
        )

    if args.test_lux is not None and args.test_lux <= 0:
        parser.error("--test-lux must be greater than 0.")

    if args.test_raw is not None and not (0 <= args.test_raw <= 1023):
        parser.error("--test-raw must be between 0 and 1023.")

    if args.interactive and args.test_raw is None:
        parser.error("--interactive only applies to --test-raw.")

    if getattr(args, "calibrate_lux", False):
        sys.exit(run_calibrate_lux_mode(num_samples=args.calibrate_samples))

    if args.test_dimm or args.test_full_brightness \
            or args.test_lux is not None or args.test_raw is not None:
        exit_code = run_test_mode(
            test_dimm=args.test_dimm,
            test_full_brightness=args.test_full_brightness,
            test_lux=args.test_lux,
            test_raw=args.test_raw,
            test_seconds=args.test_seconds,
            interactive=args.interactive,
        )
        sys.exit(exit_code)

    run(headless=args.headless)
