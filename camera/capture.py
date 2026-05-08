"""
CameraCapture — supports picamera2 (CSI) or cv2.VideoCapture (USB webcam).
"""

import time
import cv2
import numpy as np
from typing import Optional

import config

try:
    from picamera2 import Picamera2
    _PICAMERA2_AVAILABLE = True
except ImportError:
    _PICAMERA2_AVAILABLE = False


class CameraCapture:

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
        self._frame_interval: float = 1.0 / fps
        self._last_capture: float = 0.0
        self._last_frame = None          # cached frame for display between captures
        self._cap: Optional[cv2.VideoCapture] = None
        self._picam = None

    def start(self) -> None:
        if config.CAMERA_USE_PICAMERA2:
            self._start_picamera2()
        else:
            self._start_cv2()
        time.sleep(config.CAMERA_WARMUP_SECONDS)

    def _start_picamera2(self) -> None:
        if not _PICAMERA2_AVAILABLE:
            raise RuntimeError(
                "picamera2 not found. Run: sudo apt install -y python3-picamera2"
            )
        self._picam = Picamera2()
        cfg = self._picam.create_preview_configuration(
            main={"format": "BGR888", "size": (self._width, self._height)}
        )
        self._picam.configure(cfg)
        self._picam.start()

    def _start_cv2(self) -> None:
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
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
                cap.set(cv2.CAP_PROP_FPS, self._fps)
                self._cap = cap
                return
            cap.release()
        raise RuntimeError(f"Could not open camera at index {self._index}.")

    def read_frame(self) -> Optional[np.ndarray]:
        now = time.monotonic()
        # Only grab a new frame from hardware when the capture interval has elapsed.
        # Between captures return the last frame immediately so the display loop
        # is never blocked by a sleep() and the window stays smooth.
        if now - self._last_capture >= self._frame_interval:
            if self._picam is not None:
                try:
                    frame = self._picam.capture_array("main")
                except Exception:
                    frame = None
            else:
                if self._cap is None or not self._cap.isOpened():
                    return None
                ret, frame = self._cap.read()
                if not ret:
                    frame = None
            if frame is not None:
                self._last_frame = frame
            self._last_capture = now
        return self._last_frame

    def stop(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        if self._picam is not None:
            self._picam.stop()
            self._picam = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    @property
    def is_open(self) -> bool:
        if self._picam is not None:
            return True
        return self._cap is not None and self._cap.isOpened()