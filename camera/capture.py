"""
CameraCapture — wraps cv2.VideoCapture with configurable FPS and resolution.
"""

import time
import cv2
import numpy as np
from typing import Optional

import config


class CameraCapture:
    """Opens a camera device and yields frames on demand."""

    def __init__(
        self,
        index: int = config.CAMERA_INDEX,
        width: int = config.FRAME_WIDTH,
        height: int = config.FRAME_HEIGHT,
        fps: int = config.FPS,
    ) -> None:
        self._index = index
        self._width = width
        self._height = height
        self._fps = fps
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_interval: float = 1.0 / fps
        self._last_capture: float = 0.0

    # ------------------------------------------------------------------
    def start(self) -> None:
        """Open the capture device."""
        self._cap = cv2.VideoCapture(self._index)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"Could not open camera at index {self._index}. "
                "Check that the camera is connected and not used by another process."
            )
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)

    # ------------------------------------------------------------------
    def read_frame(self) -> Optional[np.ndarray]:
        """
        Read one frame, respecting the target FPS interval.
        Returns None if the camera is not open or read fails.
        """
        if self._cap is None or not self._cap.isOpened():
            return None

        now = time.monotonic()
        elapsed = now - self._last_capture
        if elapsed < self._frame_interval:
            time.sleep(self._frame_interval - elapsed)

        ret, frame = self._cap.read()
        self._last_capture = time.monotonic()

        if not ret or frame is None:
            return None
        return frame

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Release the capture device."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    # ------------------------------------------------------------------
    def __enter__(self) -> "CameraCapture":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()

    # ------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()
