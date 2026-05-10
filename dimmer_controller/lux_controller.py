"""
LuxController — closed-loop dead-band step controller for dimmer brightness.

Maintains a current brightness value (0–100) and adjusts it in small steps
every LUX_CONTROL_INTERVAL seconds to keep the calibrated camera-estimated
lux within the IES-recommended range for the current activity.

Dead-band logic (evaluated per tick):
    calibrated_lux = raw_lux * LUX_CALIBRATION_SCALE
    calibrated_lux < range_min  →  brightness += LUX_STEP_SIZE   (too dark, brighten)
    calibrated_lux > range_max  →  brightness -= LUX_STEP_SIZE   (too bright, dim)
    within [range_min, range_max]  →  hold (no serial command)

Brightness output is always clamped to the range produced by
``LUX_BRIGHTNESS_TABLE`` for the target lux band, so the displayed
brightness % stays physically meaningful.
"""

import time

import config


# ---------------------------------------------------------------------------
# Piecewise-linear interpolation helpers
# ---------------------------------------------------------------------------

def _build_control_points() -> list[tuple[float, float]]:
    """
    Derive unique, sorted (lux, brightness%) control points from
    LUX_BRIGHTNESS_TABLE by treating each row’s endpoints as anchors.
    """
    pts: dict[float, float] = {}
    for lux_lo, lux_hi, b_lo, b_hi in config.LUX_BRIGHTNESS_TABLE:
        pts[float(lux_lo)] = float(b_lo)
        pts[float(lux_hi)] = float(b_hi)
    return sorted(pts.items())


def _lux_to_brightness(lux: float) -> int:
    """
    Piecewise-linear mapping from a lux value to a brightness percentage
    using LUX_BRIGHTNESS_TABLE as anchor points.

    Values below the lowest anchor are clamped to the minimum brightness;
    values above the highest anchor are clamped to the maximum.
    """
    pts = _build_control_points()
    if lux <= pts[0][0]:
        return int(pts[0][1])
    if lux >= pts[-1][0]:
        return int(pts[-1][1])
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if x0 <= lux <= x1:
            t = (lux - x0) / (x1 - x0)
            return int(round(y0 + t * (y1 - y0)))
    return 50  # unreachable fallback


class LuxController:
    """
    Dead-band step controller that drives dimmer brightness toward the
    IES lux target range for the current activity.

    Brightness output is clamped to the range [_lux_to_brightness(lux_min),
    _lux_to_brightness(lux_max)] for the target band, ensuring the displayed
    brightness % always falls within the values that physically produce the
    required illuminance.
    """

    def __init__(
        self,
        step: int = config.LUX_STEP_SIZE,
        interval: float = config.LUX_CONTROL_INTERVAL,
    ) -> None:
        self._step = step
        self._interval = interval
        self._brightness: int = 50          # Start at a neutral mid-point
        self._last_tick: float = 0.0        # Monotonic time of last adjustment

    # ------------------------------------------------------------------
    def set_initial(self, target_range: tuple[int, int]) -> None:
        """
        Seed brightness using LUX_BRIGHTNESS_TABLE so the light immediately
        jumps to the brightness % that physically produces the midpoint lux
        of *target_range*, rather than starting from an arbitrary number.
        """
        lo, hi = target_range
        mid_lux = (lo + hi) / 2.0
        self._brightness = _lux_to_brightness(mid_lux)
        # Delay first control tick so the light can settle after the jump.
        self._last_tick = time.monotonic()

    # ------------------------------------------------------------------
    def compute(
        self,
        current_lux: float,
        target_range: tuple[int, int],
    ) -> tuple[int, bool]:
        """
        Evaluate one control tick.

        Parameters
        ----------
        current_lux:
            Raw lux value from ``_estimate_lux()`` (not yet calibrated).
        target_range:
            (min_lux, max_lux) IES target band for the current activity.

        Returns
        -------
        (brightness, changed)
            brightness — current brightness value (0–100), possibly updated.
            changed    — True when brightness was adjusted this tick (caller
                         should enqueue a serial command).
        """
        now = time.monotonic()
        if now - self._last_tick < self._interval:
            return self._brightness, False

        calibrated = current_lux * config.LUX_CALIBRATION_SCALE
        lo, hi = target_range

        # Derive the valid brightness range for this lux band from the table.
        b_min = _lux_to_brightness(lo)
        b_max = _lux_to_brightness(hi)

        if calibrated < lo:
            # Scene is too dark — increase brightness, clamped to table max
            new_brightness = min(b_max, self._brightness + self._step)
        elif calibrated > hi:
            # Scene is too bright — decrease brightness, clamped to table min
            new_brightness = max(b_min, self._brightness - self._step)
        else:
            # Within target band — hold
            return self._brightness, False

        changed = new_brightness != self._brightness
        self._brightness = new_brightness
        if changed:
            self._last_tick = now
        return self._brightness, changed

    # ------------------------------------------------------------------
    @property
    def brightness(self) -> int:
        """Current brightness value (0–100)."""
        return self._brightness
