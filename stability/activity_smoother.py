"""
ActivitySmoother — temporal smoothing to prevent rapid activity label switching.

Maintains a rolling window of recent classifications and only emits a new
label when a sufficient majority of the window agrees.
"""

from collections import deque
from typing import Tuple

import config


class ActivitySmoother:
    """
    Collects recent (activity, confidence) pairs and returns the stable
    consensus label together with its average confidence.

    A label is considered "stable" when it represents at least
    STABILITY_MAJORITY fraction of the last STABILITY_WINDOW results.
    If no majority exists the previous stable label is retained.
    """

    def __init__(
        self,
        window: int = config.STABILITY_WINDOW,
        majority: float = config.STABILITY_MAJORITY,
        default: str = config.DEFAULT_ACTIVITY,
    ) -> None:
        self._window = window
        self._majority = majority
        self._history: deque = deque(maxlen=window)
        self._stable_activity: str = default
        self._stable_confidence: int = 0

    # ------------------------------------------------------------------
    def update(self, activity: str, confidence: int) -> Tuple[str, int]:
        """
        Add the latest observation and return the current stable result.

        Returns:
            (stable_activity, average_confidence)
        """
        self._history.append((activity, confidence))

        counts: dict[str, list[int]] = {}
        for act, conf in self._history:
            counts.setdefault(act, []).append(conf)

        best_act = max(counts, key=lambda a: len(counts[a]))
        best_fraction = len(counts[best_act]) / len(self._history)

        if best_fraction >= self._majority:
            self._stable_activity = best_act
            self._stable_confidence = int(
                sum(counts[best_act]) / len(counts[best_act])
            )

        return self._stable_activity, self._stable_confidence

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Clear history, e.g., when the subject leaves the frame."""
        self._history.clear()

    # ------------------------------------------------------------------
    @property
    def stable_activity(self) -> str:
        return self._stable_activity

    @property
    def stable_confidence(self) -> int:
        return self._stable_confidence
