"""
LambertianLuxEstimator — physics-based ambient lux estimation from a camera frame.

Model
-----
For a Lambertian (perfectly diffuse) surface with reflectance ρ illuminated
by irradiance E (lux), the reflected radiance L (cd/m²) is:

    L = ρ · E / π   →   E = π · L / ρ

The camera's pixel value encodes luminance.  After removing the display-gamma
applied by the ISP (sRGB ≈ 2.2), the linearised pixel value is proportional to
the physical radiance reaching the sensor:

    L = K_cal · Y_linear / (t_s · g)

where:
    Y_linear   — mean linear luminance (0–1), gamma-decoded from the frame
    t_s        — shutter/exposure time in seconds (from CAMERA_LOCK_EXPOSURE_US)
    g          — analogue gain (from CAMERA_LOCK_ANALOG_GAIN)
    K_cal      — camera-specific calibration constant (LUX_LAMBERTIAN_K_CAL);
                 derive once with --calibrate-lux and a real lux meter

Combining:

    E_lux = π · K_cal · Y_linear / (t_s · g · ρ)

Requirements
------------
- CAMERA_LOCK_ENABLED must be True so t_s and g are fixed and known.  When
  auto-exposure is active the camera silently changes both values each frame,
  making the estimate unreliable.
- All parameters are read from config at construction time for fast per-frame
  calling.
"""

import math
import numpy as np
import config


class LambertianLuxEstimator:
    """
    Estimates scene illuminance (lux) from a BGR camera frame using the
    Lambertian reflectance model.

    Parameters are loaded from config at construction time:
        LUX_LAMBERTIAN_REFLECTANCE  — surface reflectance ρ  (default 0.50)
        LUX_LAMBERTIAN_GAMMA        — ISP gamma exponent      (default 2.2)
        LUX_LAMBERTIAN_K_CAL        — calibration constant    (default 1.0)
        CAMERA_LOCK_EXPOSURE_US     — shutter time µs         (from camera lock)
        CAMERA_LOCK_ANALOG_GAIN     — analogue gain           (from camera lock)
    """

    # Rec.709 luminance coefficients (BGR order)
    _REC709_B = 0.0722
    _REC709_G = 0.7152
    _REC709_R = 0.2126

    def __init__(self) -> None:
        self._rho: float = float(
            getattr(config, "LUX_LAMBERTIAN_REFLECTANCE", 0.85)
        )
        self._gamma: float = float(
            getattr(config, "LUX_LAMBERTIAN_GAMMA", 2.2)
        )
        self._k_cal: float = float(
            getattr(config, "LUX_LAMBERTIAN_K_CAL", 1.0)
        )
        exposure_us: int = int(
            getattr(config, "CAMERA_LOCK_EXPOSURE_US", 10_000)
        )
        self._exposure_s: float = max(exposure_us, 1) / 1_000_000.0
        self._gain: float = float(
            getattr(config, "CAMERA_LOCK_ANALOG_GAIN", 1.0)
        )
        self._roi_enabled: bool = bool(
            getattr(config, "LUX_LAMBERTIAN_ROI_ENABLED", False)
        )
        self._roi: tuple = tuple(
            getattr(config, "LUX_LAMBERTIAN_ROI", (0.78, 0.04, 0.18, 0.18))
        )

        # Pre-compute the constant part of the formula so estimate() is fast.
        # E = (π / (ρ · t_s · g)) · K_cal · Y_linear
        denom = self._rho * self._exposure_s * self._gain
        if denom <= 0.0:
            denom = 1e-9  # guard against bad config values
        self._scale: float = (math.pi * self._k_cal) / denom

        if not getattr(config, "CAMERA_LOCK_ENABLED", False):
            print(
                "[LambertianLux] WARNING — CAMERA_LOCK_ENABLED is False. "
                "Auto-exposure changes exposure/gain each frame, making the "
                "Lambertian estimate unreliable. Set CAMERA_LOCK_ENABLED = True "
                "in config.py for accurate readings."
            )
        if self._roi_enabled:
            x, y, w, h = self._roi
            print(
                f"[LambertianLux] ROI enabled — measuring from "
                f"x={x:.0%} y={y:.0%} w={w:.0%} h={h:.0%} of frame. "
                f"Place white paper inside the on-screen box."
            )

    # ------------------------------------------------------------------
    def _crop_to_roi(self, frame: np.ndarray) -> np.ndarray:
        """Return the ROI sub-image if ROI is enabled, else the full frame."""
        if not self._roi_enabled:
            return frame
        fh, fw = frame.shape[:2]
        x1 = int(self._roi[0] * fw)
        y1 = int(self._roi[1] * fh)
        x2 = int((self._roi[0] + self._roi[2]) * fw)
        y2 = int((self._roi[1] + self._roi[3]) * fh)
        x1, x2 = max(0, x1), min(fw, x2)
        y1, y2 = max(0, y1), min(fh, y2)
        if x2 <= x1 or y2 <= y1:
            return frame
        return frame[y1:y2, x1:x2]

    # ------------------------------------------------------------------
    def estimate(self, frame: np.ndarray) -> float:
        """
        Return the estimated scene illuminance in lux from *frame* (BGR, uint8).

        Steps
        -----
        1. Compute per-pixel luminance Y using Rec.709 coefficients.
        2. Average Y over the whole frame.
        3. Gamma-decode to linear: Y_linear = (Y_mean / 255) ^ gamma.
        4. Apply the Lambertian formula: E = scale * Y_linear.
        5. Clamp to a physical floor of 0.1 lux.
        """
        src = self._crop_to_roi(frame)
        # --- Step 1 & 2: Rec.709 luminance, averaged over the ROI / full frame ---
        # Split channels and apply coefficients in float32 to avoid overflow.
        b = src[:, :, 0].astype(np.float32)
        g_ch = src[:, :, 1].astype(np.float32)
        r = src[:, :, 2].astype(np.float32)
        Y_mean: float = float(
            self._REC709_B * b.mean()
            + self._REC709_G * g_ch.mean()
            + self._REC709_R * r.mean()
        )

        # --- Step 3: Gamma decode ---
        Y_norm = Y_mean / 255.0
        # Guard against log(0) in power function
        Y_norm = max(Y_norm, 1e-9)
        Y_linear = Y_norm ** self._gamma

        # --- Step 4: Lambertian formula ---
        lux = self._scale * Y_linear

        # --- Step 5: Physical floor ---
        return max(lux, 0.1)

    # ------------------------------------------------------------------
    def estimate_raw(self, frame: np.ndarray) -> float:
        """
        Same as estimate() but forces K_cal = 1.0 so the output is the
        un-calibrated raw estimate.  Used by the --calibrate-lux wizard to
        measure what K_cal should be set to.
        """
        denom = self._rho * self._exposure_s * self._gain
        if denom <= 0.0:
            denom = 1e-9
        raw_scale = math.pi / denom  # K_cal = 1.0

        src = self._crop_to_roi(frame)
        b = src[:, :, 0].astype(np.float32)
        g_ch = src[:, :, 1].astype(np.float32)
        r = src[:, :, 2].astype(np.float32)
        Y_mean = float(
            self._REC709_B * b.mean()
            + self._REC709_G * g_ch.mean()
            + self._REC709_R * r.mean()
        )
        Y_norm = max(Y_mean / 255.0, 1e-9)
        Y_linear = Y_norm ** self._gamma
        return max(raw_scale * Y_linear, 1e-9)  # no floor — caller needs the raw value
