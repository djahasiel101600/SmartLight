"""
StructuredLogger — logs activity results and system events to stdout
and an optional rotating log file under outputs/.
"""

import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from typing import Optional

import config


class StructuredLogger:
    """
    Wraps Python's standard logging with structured fields.

    All log entries carry:
        timestamp | level | message | [optional key=value pairs]
    """

    def __init__(
        self,
        name: str = "activity_recognition",
        log_dir: str = config.LOG_DIR,
        level: str = config.LOG_LEVEL,
        to_file: bool = config.LOG_TO_FILE,
    ) -> None:
        self._logger = logging.getLogger(name)
        self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))

        fmt = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # --- stdout handler ---
        if not self._logger.handlers:
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setFormatter(fmt)
            self._logger.addHandler(stream_handler)

            # --- file handler ---
            if to_file:
                os.makedirs(log_dir, exist_ok=True)
                log_path = os.path.join(log_dir, "activity_log.log")
                file_handler = RotatingFileHandler(
                    log_path,
                    maxBytes=5 * 1024 * 1024,   # 5 MB per file
                    backupCount=5,
                    encoding="utf-8",
                )
                file_handler.setFormatter(fmt)
                self._logger.addHandler(file_handler)

        self._api_calls: int = 0
        self._session_start: float = time.monotonic()

    # ------------------------------------------------------------------
    def log_activity(
        self,
        activity: str,
        confidence: int,
        similarity_score: float,
        source: str,              # "api" | "cache"
        processing_ms: float,
        reasoning: str = "",
    ) -> None:
        msg = (
            f"activity={activity!r:20s} "
            f"confidence={confidence:3d} "
            f"similarity={similarity_score:.3f} "
            f"source={source:5s} "
            f"proc={processing_ms:.1f}ms"
        )
        if reasoning:
            msg += f" | {reasoning}"
        self._logger.info(msg)

    # ------------------------------------------------------------------
    def log_api_call(self, activity: str, confidence: int, latency_ms: float) -> None:
        self._api_calls += 1
        self._logger.info(
            f"[API #{self._api_calls}] activity={activity!r} "
            f"confidence={confidence} latency={latency_ms:.0f}ms"
        )

    # ------------------------------------------------------------------
    def log_cache_reuse(self, reason: str, activity: str) -> None:
        self._logger.debug(f"[CACHE] reuse reason={reason!r} activity={activity!r}")

    # ------------------------------------------------------------------
    def log_error(self, message: str, exc: Optional[Exception] = None) -> None:
        if exc:
            self._logger.error(f"{message} | {type(exc).__name__}: {exc}")
        else:
            self._logger.error(message)

    # ------------------------------------------------------------------
    def log_warning(self, message: str) -> None:
        self._logger.warning(message)

    # ------------------------------------------------------------------
    def log_info(self, message: str) -> None:
        self._logger.info(message)

    # ------------------------------------------------------------------
    def log_startup(self) -> None:
        self._logger.info(
            "=== Activity Recognition System starting ==="
        )
        self._logger.info(
            f"Allowed activities: {config.ALLOWED_ACTIVITIES}"
        )
        self._logger.info(
            f"Similarity threshold: {config.SIMILARITY_THRESHOLD} | "
            f"Motion threshold: {config.MOTION_THRESHOLD} | "
            f"API cooldown: {config.API_COOLDOWN_SECONDS}s"
        )

    # ------------------------------------------------------------------
    def log_shutdown(self) -> None:
        elapsed = time.monotonic() - self._session_start
        self._logger.info(
            f"=== Shutting down | runtime={elapsed:.1f}s "
            f"api_calls={self._api_calls} ==="
        )
