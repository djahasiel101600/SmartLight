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

The controller is intentionally simple — no integral or derivative terms — to
avoid windup and over-correction on a non-calibrated camera-based lux estimate.
"""

import time

import config


class LuxController:
    """
    Dead-band step controller that drives dimmer brightness toward the
    IES lux target range for the current activity.
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
        Seed brightness to the midpoint of *target_range* when the activity
        first commits.  This puts the light in a reasonable starting position
        before the closed-loop controller takes over, avoiding a long ramp
        from whatever the previous brightness was.
        """
        lo, hi = target_range
        self._brightness = max(0, min(100, (lo + hi) // 2))
        # Reset the tick timer so the first control step is delayed by one
        # full interval, giving the light time to settle after the jump.
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

        if calibrated < lo:
            # Scene is too dark — increase brightness
            new_brightness = min(100, self._brightness + self._step)
        elif calibrated > hi:
            # Scene is too bright — decrease brightness
            new_brightness = max(0, self._brightness - self._step)
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
