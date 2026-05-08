"""
SimilarityComparator — measures structural similarity between the current
ROI frame and the last frame that was sent to the OpenAI API.
"""

import cv2
import numpy as np
from typing import Tuple

import config

try:
    from skimage.metrics import structural_similarity as ssim
    _SSIM_AVAILABLE = True
except ImportError:
    _SSIM_AVAILABLE = False


class SimilarityComparator:
    """
    Compares two frames using SSIM (preferred) or histogram correlation
    as a fallback when scikit-image is unavailable.

    Usage:
        comp = SimilarityComparator()
        score, is_similar = comp.compare(current_roi)
        # After deciding to call the API:
        comp.update_reference(current_roi)
    """

    def __init__(
        self,
        threshold: float = config.SIMILARITY_THRESHOLD,
        resize: Tuple[int, int] = config.SIMILARITY_RESIZE,
    ) -> None:
        self._threshold = threshold
        self._resize = resize
        self._reference: np.ndarray | None = None

    # ------------------------------------------------------------------
    def compare(self, frame: np.ndarray) -> Tuple[float, bool]:
        """
        Compare *frame* against the stored reference.

        Returns:
            (score, is_similar)
            score      — 0.0 (completely different) to 1.0 (identical).
            is_similar — True when score >= threshold, meaning the API
                         result can safely be reused.
        """
        if self._reference is None:
            # No reference yet → treat as always different so first frame is sent
            return 0.0, False

        current = self._preprocess(frame)
        reference = self._preprocess(self._reference)

        if _SSIM_AVAILABLE:
            score = float(ssim(current, reference, data_range=255))
        else:
            score = self._histogram_similarity(current, reference)

        return score, score >= self._threshold

    # ------------------------------------------------------------------
    def update_reference(self, frame: np.ndarray) -> None:
        """Store *frame* as the new reference for future comparisons."""
        self._reference = frame.copy()

    # ------------------------------------------------------------------
    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        resized = cv2.resize(frame, self._resize, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        return gray

    # ------------------------------------------------------------------
    @staticmethod
    def _histogram_similarity(a: np.ndarray, b: np.ndarray) -> float:
        hist_a = cv2.calcHist([a], [0], None, [256], [0, 256])
        hist_b = cv2.calcHist([b], [0], None, [256], [0, 256])
        cv2.normalize(hist_a, hist_a)
        cv2.normalize(hist_b, hist_b)
        return float(cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL))

    # ------------------------------------------------------------------
    @property
    def has_reference(self) -> bool:
        return self._reference is not None
