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
from decision_engine.engine import DecisionEngine, Decision
from applog.logger import StructuredLogger
from dimmer_controller.dimmer_manager import DimmerManager
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

            # 6. Dimmer — only fires when stable activity label changes
            dimmer.update(stable_activity)
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
                _lux = _estimate_lux(frame)
                _dim_pct = config.DIMMER_BRIGHTNESS.get(stable_activity, 0)
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


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Activity Recognition System")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without a display window (for Raspberry Pi SSH sessions).",
    )
    args = parser.parse_args()
    run(headless=args.headless)
