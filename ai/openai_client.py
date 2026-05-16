"""
OpenAIVisionClient — sends a frame to the OpenAI Vision API and returns a
structured activity classification.

Security:
    The API key is NEVER hardcoded. It is loaded from the .env file in the
    project root (OPENAI_API_KEY=...). The .env file must never be committed
    to version control — it is listed in .gitignore.
"""

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from dotenv import load_dotenv

import config

# Load .env from the project root (SmartLight/) so the key is always available
# regardless of where the script is launched from.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

try:
    from openai import OpenAI, APIError, APITimeoutError, APIConnectionError
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constrained prompt — only the four allowed labels may be returned
# ---------------------------------------------------------------------------
# _SYSTEM_PROMPT = (
#     "You are an activity recognition assistant. "
#     "You must classify exactly what activity a person is doing in the provided image. "
#     "You MUST ONLY use one of these four labels exactly as written:\n"
#     "  - Reading Book/s\n"
#     "  - Using Cellphone\n"
#     "  - Using Laptop\n"
#     "  - Writing\n"
#     "  - Idle\n\n"
#     "Do NOT invent new activity labels. "
#     "Do NOT return anything outside of these four labels. "
#     "Respond with valid JSON only — no markdown fences, no extra text."
# )

# _USER_PROMPT = (
#     "Analyze the human activity in this image.\n\n"
#     "Return ONLY the following JSON structure:\n"
#     '{\n'
#     '  "activity": "<one of the four allowed labels>",\n'
#     '  "confidence": <integer 0-100>,\n'
#     '  "reasoning": "<brief one-sentence explanation>"\n'
#     '}'
# )

_SYSTEM_PROMPT = (
    "You are an activity recognition assistant. "
    "Classify the PRIMARY human activity shown in the image. "
    "You MUST use exactly one of these labels:\n"
    "- Reading Book/s\n"
    "- Using Cellphone\n"
    "- Using Laptop\n"
    "- Writing\n"
    "- Idle\n\n"

    "Important classification rules:\n"
    "- Focus on what the person is ACTIVELY DOING, not just nearby objects.\n"
    "- If multiple objects are visible, choose the activity receiving the person's main attention.\n"
    "- A visible laptop alone does NOT mean Using Laptop.\n"
    "- A visible cellphone alone does NOT mean Using Cellphone.\n"
    "- If the person is looking at or touching a cellphone while seated at a laptop, classify as Using Cellphone.\n"
    "- If the person is typing, looking at, or interacting mainly with the laptop, classify as Using Laptop.\n"
    "- If no clear activity is detected, classify as Idle.\n\n"

    "Respond with valid JSON only."
)


# ---------------------------------------------------------------------------
@dataclass
class ClassificationResult:
    activity: str
    confidence: int
    reasoning: str
    raw_response: str = ""
    error: Optional[str] = None


class OpenAIVisionClient:
    """
    Encodes a frame as a JPEG, sends it to GPT-4o with a constrained prompt,
    and parses the JSON response into a ClassificationResult.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        encode_width: int = config.ENCODE_WIDTH,
        encode_height: int = config.ENCODE_HEIGHT,
        jpeg_quality: int = config.JPEG_QUALITY,
        confidence_threshold: int = config.CONFIDENCE_THRESHOLD,
    ) -> None:
        if not _OPENAI_AVAILABLE:
            raise ImportError("openai package is required. Run: pip install openai")

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY environment variable is not set. "
                "Set it before running the application."
            )

        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._encode_size = (encode_width, encode_height)
        self._jpeg_quality = jpeg_quality
        self._confidence_threshold = confidence_threshold

    # ------------------------------------------------------------------
    def classify(self, frame: np.ndarray) -> ClassificationResult:
        """
        Send *frame* to the OpenAI Vision API and return a classification.

        Returns a ClassificationResult with error set if the call fails.
        The activity defaults to DEFAULT_ACTIVITY on any error so the
        caller always has a usable label.
        """
        image_b64 = self._encode_frame(frame)

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _USER_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}",
                                    "detail": "low",   # Cheaper + faster; sufficient for activity detection
                                },
                            },
                        ],
                    },
                ],
                max_tokens=150,
                temperature=0,
            )

            raw = response.choices[0].message.content or ""
            return self._parse_response(raw)

        except APITimeoutError as exc:
            return ClassificationResult(
                activity=config.DEFAULT_ACTIVITY,
                confidence=0,
                reasoning="",
                error=f"API timeout: {exc}",
            )
        except APIConnectionError as exc:
            return ClassificationResult(
                activity=config.DEFAULT_ACTIVITY,
                confidence=0,
                reasoning="",
                error=f"Connection error: {exc}",
            )
        except APIError as exc:
            return ClassificationResult(
                activity=config.DEFAULT_ACTIVITY,
                confidence=0,
                reasoning="",
                error=f"API error: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return ClassificationResult(
                activity=config.DEFAULT_ACTIVITY,
                confidence=0,
                reasoning="",
                error=f"Unexpected error: {exc}",
            )

    # ------------------------------------------------------------------
    def _encode_frame(self, frame: np.ndarray) -> str:
        """Resize frame and encode as base64 JPEG string."""
        resized = cv2.resize(frame, self._encode_size, interpolation=cv2.INTER_AREA)
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
        _, buffer = cv2.imencode(".jpg", resized, encode_params)
        return base64.b64encode(buffer.tobytes()).decode("utf-8")

    # ------------------------------------------------------------------
    def _parse_response(self, raw: str) -> ClassificationResult:
        """Parse the model's JSON response, sanitizing the activity label."""
        raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Attempt to extract JSON substring in case of extra text
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                try:
                    data = json.loads(raw[start:end])
                except json.JSONDecodeError:
                    return ClassificationResult(
                        activity=config.DEFAULT_ACTIVITY,
                        confidence=0,
                        reasoning="",
                        raw_response=raw,
                        error="Could not parse JSON from API response.",
                    )
            else:
                return ClassificationResult(
                    activity=config.DEFAULT_ACTIVITY,
                    confidence=0,
                    reasoning="",
                    raw_response=raw,
                    error="No JSON object found in API response.",
                )

        activity = str(data.get("activity", config.DEFAULT_ACTIVITY)).strip()

        # Enforce the allowed-labels whitelist
        if activity not in config.ALLOWED_ACTIVITIES:
            activity = config.DEFAULT_ACTIVITY

        confidence = int(data.get("confidence", 0))
        confidence = max(0, min(100, confidence))

        reasoning = str(data.get("reasoning", "")).strip()

        return ClassificationResult(
            activity=activity,
            confidence=confidence,
            reasoning=reasoning,
            raw_response=raw,
        )
