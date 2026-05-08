"""
DecisionEngine — the central gating logic.

Determines for each frame whether to:
  (A) Reuse the cached activity result, or
  (B) Call the OpenAI Vision API for a fresh classification.

Decision tree:
    1. No motion detected         → reuse (motion gate)
    2. Similarity above threshold → reuse (similarity gate)
    3. API cooldown still active  → reuse (rate limiter)
    4. Otherwise                  → call API
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Tuple

import numpy as np

from cache.frame_cache import FrameCache
from preprocessing.motion_detector import MotionDetector
from similarity.comparator import SimilarityComparator


class Decision(Enum):
    CALL_API = auto()
    REUSE_CACHE = auto()


@dataclass
class EngineResult:
    decision: Decision
    reason: str                  # Human-readable reason for the decision
    motion_detected: bool
    motion_magnitude: float
    similarity_score: float
    is_similar: bool


class DecisionEngine:
    """
    Wires together the MotionDetector, SimilarityComparator, and FrameCache
    to produce a Decision for every incoming ROI frame.
    """

    def __init__(
        self,
        motion_detector: MotionDetector,
        similarity_comparator: SimilarityComparator,
        frame_cache: FrameCache,
    ) -> None:
        self._motion = motion_detector
        self._similarity = similarity_comparator
        self._cache = frame_cache

    # ------------------------------------------------------------------
    def evaluate(self, roi_frame: np.ndarray) -> EngineResult:
        """
        Evaluate *roi_frame* and return an EngineResult.

        Call this on every captured ROI before deciding whether to hit the API.
        """
        # --- Gate 1: Motion ---
        motion_detected, magnitude = self._motion.update(roi_frame)
        if not motion_detected:
            score, similar = self._similarity.compare(roi_frame)
            return EngineResult(
                decision=Decision.REUSE_CACHE,
                reason="no_motion",
                motion_detected=False,
                motion_magnitude=magnitude,
                similarity_score=score,
                is_similar=similar,
            )

        # --- Gate 2: Similarity ---
        score, similar = self._similarity.compare(roi_frame)
        if similar:
            return EngineResult(
                decision=Decision.REUSE_CACHE,
                reason="similar_frame",
                motion_detected=True,
                motion_magnitude=magnitude,
                similarity_score=score,
                is_similar=True,
            )

        # --- Gate 3: Cooldown ---
        if not self._cache.should_call_api():
            return EngineResult(
                decision=Decision.REUSE_CACHE,
                reason="cooldown",
                motion_detected=True,
                motion_magnitude=magnitude,
                similarity_score=score,
                is_similar=False,
            )

        # --- Decision: Call API ---
        return EngineResult(
            decision=Decision.CALL_API,
            reason="significant_change",
            motion_detected=True,
            motion_magnitude=magnitude,
            similarity_score=score,
            is_similar=False,
        )
