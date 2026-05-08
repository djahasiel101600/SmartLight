"""
ROIExtractor — detects the person region using MediaPipe Pose and crops it.
Falls back to the full frame if no person is detected.
"""

import cv2
import numpy as np
from typing import Tuple

import config

try:
    import mediapipe as mp
    # mediapipe 0.10+ removed the legacy solutions API; check before using it
    _MP_POSE_AVAILABLE = hasattr(mp, "solutions") and hasattr(mp.solutions, "pose")
except ImportError:
    mp = None  # type: ignore[assignment]
    _MP_POSE_AVAILABLE = False


class ROIExtractor:
    """
    Extracts the person's region of interest (ROI) from a frame.

    If MediaPipe Pose (legacy solutions API) is available, uses landmarks to
    compute a tight bounding box around the detected body, padded by ROI_PADDING.
    Falls back gracefully to returning the full frame when MediaPipe is absent
    or uses the new Tasks API (0.10+).
    """

    def __init__(self, padding: float = config.ROI_PADDING) -> None:
        self._padding = padding
        self._pose = None

        if _MP_POSE_AVAILABLE:
            self._pose = mp.solutions.pose.Pose(
                static_image_mode=False,
                model_complexity=0,          # Fastest model for Raspberry Pi
                enable_segmentation=False,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )

    # ------------------------------------------------------------------
    def extract(self, frame: np.ndarray) -> Tuple[np.ndarray, Tuple[int, int, int, int] | None]:
        """
        Extract the ROI from the given BGR frame.

        Returns:
            (roi_frame, bbox)
            roi_frame — cropped BGR image of the person area (or full frame).
            bbox      — (x1, y1, x2, y2) in pixel coords, or None if not detected.
        """
        if self._pose is None:
            return frame, None

        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._pose.process(rgb)

        if not results.pose_landmarks:
            return frame, None

        landmarks = results.pose_landmarks.landmark
        xs = [lm.x for lm in landmarks]
        ys = [lm.y for lm in landmarks]

        x1 = max(0, int((min(xs) - self._padding) * w))
        y1 = max(0, int((min(ys) - self._padding) * h))
        x2 = min(w, int((max(xs) + self._padding) * w))
        y2 = min(h, int((max(ys) + self._padding) * h))

        # Guard against degenerate boxes
        if x2 <= x1 or y2 <= y1:
            return frame, None

        roi = frame[y1:y2, x1:x2]
        return roi, (x1, y1, x2, y2)

    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._pose is not None:
            self._pose.close()
            self._pose = None

    # ------------------------------------------------------------------
    def __del__(self) -> None:
        self.close()
