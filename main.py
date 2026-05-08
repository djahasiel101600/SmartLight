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
    "Reading Book/s": (0, 200, 255),
    "Using Cellphone": (255, 150, 0),
    "Using Laptop":   (0, 255, 100),
    "Idle":           (180, 180, 180),
}
_DEFAULT_COLOR = (200, 200, 200)


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
    api_busy: bool = False,
) -> None:
    h, w = frame.shape[:2]
    color = _ACTIVITY_COLORS.get(activity, _DEFAULT_COLOR)

    # Bounding box around detected person
    if bbox is not None:
        x1, y1, x2, y2 = bbox
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    # Activity label bar at top
    cv2.rectangle(frame, (0, 0), (w, 50), (0, 0, 0), -1)
    label = f"{activity}  ({confidence}%)  [{source}]"
    if api_busy:
        label += "  [API...]"
    cv2.putText(frame, label, (10, 33), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2, cv2.LINE_AA)

    # Motion indicator dot — green = still, red = motion detected
    dot_color = (0, 0, 255) if motion else (0, 255, 0)
    cv2.circle(frame, (w - 20, 20), 8, dot_color, -1)

    # API busy spinner dot (yellow) in bottom-right
    if api_busy:
        cv2.circle(frame, (w - 20, h - 20), 8, (0, 220, 255), -1)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run(headless: bool = False) -> None:
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
    logger.log_info("Indicator dots — top-right: green=still / red=motion  |  bottom-right: yellow=API calling")

    try:
        while True:
            t_start = time.monotonic()

            # 1. Capture
            frame = camera.read_frame()
            if frame is None:
                logger.log_warning("Empty frame received — skipping.")
                continue

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
                _draw_overlay(
                    frame,
                    activity=stable_activity,
                    confidence=stable_confidence,
                    source=source,
                    bbox=bbox,
                    motion=engine_result.motion_detected,
                    api_busy=api_worker.is_busy,
                )
                cv2.imshow("Activity Recognition", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    except KeyboardInterrupt:
        pass
    finally:
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
