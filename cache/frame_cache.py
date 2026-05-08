"""
FrameCache — lightweight store for the most recent API result and metadata.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

import config


@dataclass
class CacheEntry:
    activity: str = config.DEFAULT_ACTIVITY
    confidence: int = 0
    reasoning: str = ""
    similarity_score: float = 0.0
    timestamp: float = field(default_factory=time.monotonic)
    frame: Optional[np.ndarray] = None     # Last frame sent to API


class FrameCache:
    """
    Stores the most recent activity classification result and the frame
    that produced it, plus metadata needed by the decision engine.
    """

    def __init__(self, cooldown: float = config.API_COOLDOWN_SECONDS) -> None:
        self._cooldown = cooldown
        self._entry = CacheEntry()
        self._api_call_count: int = 0

    # ------------------------------------------------------------------
    def update(
        self,
        activity: str,
        confidence: int,
        reasoning: str,
        frame: np.ndarray,
        similarity_score: float = 0.0,
    ) -> None:
        """Store a fresh API result."""
        self._entry = CacheEntry(
            activity=activity,
            confidence=confidence,
            reasoning=reasoning,
            similarity_score=similarity_score,
            timestamp=time.monotonic(),
            frame=frame.copy(),
        )
        self._api_call_count += 1

    # ------------------------------------------------------------------
    def should_call_api(self) -> bool:
        """Return True when the cooldown period has elapsed."""
        elapsed = time.monotonic() - self._entry.timestamp
        return elapsed >= self._cooldown

    # ------------------------------------------------------------------
    @property
    def current(self) -> CacheEntry:
        return self._entry

    @property
    def api_call_count(self) -> int:
        return self._api_call_count

    @property
    def cooldown(self) -> float:
        return self._cooldown
