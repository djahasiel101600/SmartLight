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
        self._camera_lock_report: list[str] = []

    def start(self) -> None:
        if config.CAMERA_USE_PICAMERA2:
            self._start_picamera2()
        else:
            self._start_cv2()
        self._apply_camera_lock_settings()
        self._log_camera_lock_status()
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

    def _apply_camera_lock_settings(self) -> None:
        self._camera_lock_report = []

        if not getattr(config, "CAMERA_LOCK_ENABLED", False):
            self._camera_lock_report.append("camera lock disabled in config")
            return

        if self._picam is not None:
            self._apply_picamera2_lock()
            return

        if self._cap is not None:
            self._apply_cv2_lock()
            return

        self._camera_lock_report.append("camera lock skipped: no active camera backend")

    def _apply_picamera2_lock(self) -> None:
        supported = set(getattr(self._picam, "camera_controls", {}).keys())
        controls = {}

        def _set_if_supported(name: str, value) -> None:
            if name in supported:
                controls[name] = value
            else:
                self._camera_lock_report.append(f"unsupported (picamera2): {name}")

        _set_if_supported("AeEnable", False)
        _set_if_supported("ExposureTime", int(getattr(config, "CAMERA_LOCK_EXPOSURE_US", 10000)))
        _set_if_supported("AnalogueGain", float(getattr(config, "CAMERA_LOCK_ANALOG_GAIN", 1.0)))
        _set_if_supported("Sensitivity", int(getattr(config, "CAMERA_LOCK_ISO", 100)))
        _set_if_supported("AwbEnable", bool(getattr(config, "CAMERA_LOCK_AWB_ENABLED", False)))
        _set_if_supported("ExposureValue", float(getattr(config, "CAMERA_LOCK_EV", 0.0)))

        awb_mode = getattr(config, "CAMERA_LOCK_AWB_MODE", None)
        if "AwbMode" in supported and awb_mode is not None:
            if isinstance(awb_mode, (int, float)):
                controls["AwbMode"] = int(awb_mode)
            else:
                self._camera_lock_report.append(
                    "ignored invalid AwbMode type (expected int enum)"
                )
        elif "AwbMode" not in supported:
            self._camera_lock_report.append("unsupported (picamera2): AwbMode")

        if not controls:
            self._camera_lock_report.append("camera lock: no picamera2 controls could be applied")
            return

        try:
            self._picam.set_controls(controls)
            self._camera_lock_report.append(
                "picamera2 lock applied: " + ", ".join(sorted(controls.keys()))
            )
        except Exception as exc:
            self._camera_lock_report.append(f"picamera2 lock failed: {exc}")

    def _apply_cv2_lock(self) -> None:
        if self._cap is None:
            return

        def _try_prop(prop: int, value: float, label: str) -> None:
            try:
                ok = self._cap.set(prop, value)
                if ok:
                    self._camera_lock_report.append(f"cv2 applied {label}={value}")
                else:
                    self._camera_lock_report.append(f"cv2 rejected {label}={value}")
            except Exception as exc:
                self._camera_lock_report.append(f"cv2 error {label}: {exc}")

        # Driver behavior differs by backend; try several known manual modes.
        _try_prop(cv2.CAP_PROP_AUTO_EXPOSURE, 1.0, "auto_exposure")
        _try_prop(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25, "auto_exposure")
        _try_prop(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75, "auto_exposure")

        _try_prop(
            cv2.CAP_PROP_EXPOSURE,
            float(getattr(config, "CAMERA_LOCK_EXPOSURE_US", 10000)),
            "exposure",
        )
        _try_prop(
            cv2.CAP_PROP_GAIN,
            float(getattr(config, "CAMERA_LOCK_ANALOG_GAIN", 1.0)),
            "gain",
        )

        iso_prop = getattr(cv2, "CAP_PROP_ISO_SPEED", None)
        if iso_prop is not None:
            _try_prop(
                iso_prop,
                float(getattr(config, "CAMERA_LOCK_ISO", 100)),
                "iso",
            )
        else:
            self._camera_lock_report.append("cv2 CAP_PROP_ISO_SPEED not available")

    def _log_camera_lock_status(self) -> None:
        if not self._camera_lock_report:
            return
        for line in self._camera_lock_report:
            print(f"[Camera] {line}")
        self._print_camera_details()

    def _print_camera_details(self) -> None:
        """Print detailed camera information for debugging."""
        print("\n[CameraDebug] ========== Camera Details ==========")
        
        if self._picam is not None:
            self._print_picamera2_details()
        elif self._cap is not None:
            self._print_cv2_details()
        else:
            print("[CameraDebug] No active camera backend")
        
        print("[CameraDebug] =====================================\n")

    def _print_picamera2_details(self) -> None:
        """Print picamera2-specific camera details."""
        try:
            print("[CameraDebug] Backend: Picamera2")
            
            # Camera info
            if hasattr(self._picam, "camera_properties"):
                props = self._picam.camera_properties
                print(f"[CameraDebug] Camera Model: {props.get('Model', 'Unknown')}")
                print(f"[CameraDebug] Sensor Size: {props.get('UnitCellSize', 'Unknown')}")
                print(f"[CameraDebug] Pixel Array: {props.get('PixelArraySize', 'Unknown')}")
            
            # Supported controls
            if hasattr(self._picam, "camera_controls"):
                controls = self._picam.camera_controls
                print(f"[CameraDebug] Supported Controls ({len(controls)}):")
                for ctrl_name in sorted(controls.keys()):
                    print(f"[CameraDebug]   - {ctrl_name}")
            
            # Current control values (best effort)
            print("[CameraDebug] Current Values (where readable):")
            for ctrl_name in ["AeEnable", "ExposureTime", "AnalogueGain", "Sensitivity", 
                             "AwbEnable", "AwbMode", "ExposureValue"]:
                try:
                    if hasattr(self._picam, "camera_controls") and ctrl_name in self._picam.camera_controls:
                        # Try to read via metadata
                        print(f"[CameraDebug]   {ctrl_name}: (locked in config)")
                except Exception:
                    pass
        except Exception as exc:
            print(f"[CameraDebug] Error retrieving picamera2 details: {exc}")

    def _print_cv2_details(self) -> None:
        """Print OpenCV camera details."""
        try:
            print("[CameraDebug] Backend: OpenCV (cv2.VideoCapture)")
            print(f"[CameraDebug] Camera Index: {self._index}")
            print(f"[CameraDebug] Resolution: {self._width}x{self._height}")
            print(f"[CameraDebug] FPS: {self._fps}")
            
            # Try to read some properties
            if self._cap is not None and self._cap.isOpened():
                props_to_check = [
                    (cv2.CAP_PROP_FRAME_WIDTH, "Frame Width"),
                    (cv2.CAP_PROP_FRAME_HEIGHT, "Frame Height"),
                    (cv2.CAP_PROP_FPS, "FPS"),
                    (cv2.CAP_PROP_EXPOSURE, "Exposure"),
                    (cv2.CAP_PROP_GAIN, "Gain"),
                    (cv2.CAP_PROP_AUTO_EXPOSURE, "Auto Exposure"),
                ]
                
                # Only check ISO if available
                if hasattr(cv2, "CAP_PROP_ISO_SPEED"):
                    props_to_check.append((cv2.CAP_PROP_ISO_SPEED, "ISO Speed"))
                
                print("[CameraDebug] Current Properties:")
                for prop_id, prop_name in props_to_check:
                    try:
                        val = self._cap.get(prop_id)
                        print(f"[CameraDebug]   {prop_name}: {val}")
                    except Exception:
                        pass
        except Exception as exc:
            print(f"[CameraDebug] Error retrieving cv2 details: {exc}")

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