"""
MotionDetector — detects meaningful motion between consecutive frames
using frame differencing + contour analysis.
"""

import cv2
import numpy as np
from typing import Tuple

import config


class MotionDetector:
    """
    Compares the current frame against the previous one.
    Returns (motion_detected: bool, magnitude: float)
    where magnitude is the fraction of pixels that changed significantly.
    """

    def __init__(
        self,
        threshold: float = config.MOTION_THRESHOLD,
        min_area: int = config.MOTION_MIN_AREA,
    ) -> None:
        self._threshold = int(threshold)
        self._min_area = min_area
        self._prev_gray: np.ndarray | None = None

    # ------------------------------------------------------------------
    def update(self, frame: np.ndarray) -> Tuple[bool, float]:
        """
        Process a new frame.

        Returns:
            (motion_detected, magnitude)
            motion_detected — True when significant motion was found.
            magnitude       — Fraction of frame area covered by moving regions (0.0–1.0).
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._prev_gray is None:
            self._prev_gray = gray
            return False, 0.0

        diff = cv2.absdiff(self._prev_gray, gray)
        self._prev_gray = gray

        _, thresh = cv2.threshold(diff, self._threshold, 255, cv2.THRESH_BINARY)
        thresh = cv2.dilate(thresh, None, iterations=2)

        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        motion_area = sum(
            cv2.contourArea(c) for c in contours if cv2.contourArea(c) >= self._min_area
        )
        frame_area = frame.shape[0] * frame.shape[1]
        magnitude = min(motion_area / frame_area, 1.0)
        motion_detected = motion_area >= self._min_area

        return motion_detected, magnitude

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Discard stored previous frame (e.g., after a scene cut)."""
        self._prev_gray = None
