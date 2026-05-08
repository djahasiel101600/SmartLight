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
        """Open the capture device, trying V4L2 backend on Linux if auto fails."""
        self._cap = self._open_camera()
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)
        # Give the camera hardware time to initialise before the first read
        time.sleep(config.CAMERA_WARMUP_SECONDS)

    def _open_camera(self) -> cv2.VideoCapture:
        """Try V4L2 backend first on Linux, then auto-detect."""
        import platform
        backends = []
        if config.CAMERA_BACKEND != 0:
            backends.append(config.CAMERA_BACKEND)
        if platform.system() == "Linux":
            backends.append(cv2.CAP_V4L2)
        backends.append(cv2.CAP_ANY)

        for backend in backends:
            cap = cv2.VideoCapture(self._index, backend)
            if cap.isOpened():
                return cap
            cap.release()

        raise RuntimeError(
            f"Could not open camera at index {self._index} with any backend. "
            "Check that the camera is connected and not used by another process."
        )

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
