"""
gemini.py — Google Gemini provider implementation.

Supports:
  - Gemini 2.0 Flash (default, fast + cheap)
  - Gemini 2.5 Flash / Pro (configure via GEMINI_MODEL env var)
  - Image analysis (base64 inline)
  - JSON mode via response_mime_type
  - System instructions

Configuration (.env):
  GEMINI_API_KEY=your_key
  GEMINI_MODEL=gemini-2.0-flash    (default)
  AI_PROVIDER=gemini
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import requests

from apps.platform.ai.exceptions import ProviderNotAvailable
from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.ai.types import ProviderConfig, ProviderType

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(BaseAIProvider):
    """
    Google Gemini provider using the REST API.
    """

    def __init__(self, config: ProviderConfig):
        super().__init__(config)

    def _validate_config(self) -> None:
        if not self.config.api_key:
            raise ProviderNotAvailable(
                "gemini",
                "GEMINI_API_KEY is not configured. "
                "Set GEMINI_API_KEY in your .env or settings.",
            )

    def supports_images(self) -> bool:
        return True

    def _call_api(
        self,
        system_instruction: str,
        messages: list[dict[str, Any]],
        response_mime_type: str = "text/plain",
    ) -> dict[str, Any]:
        """
        Call Gemini API with the given messages.
        Returns a dict compatible with BaseAIProvider._call_api spec.
        """
        url = (
            f"{GEMINI_API_BASE}/{self.config.model}:generateContent"
            f"?key={self.config.api_key}"
        )

        body: dict[str, Any] = {
            "contents": messages,
            "generationConfig": {
                "temperature": self.config.temperature,
                "maxOutputTokens": self.config.max_tokens,
            },
        }

        if response_mime_type == "application/json":
            body["generationConfig"]["response_mime_type"] = "application/json"

        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        logger.debug(
            "Gemini request: model=%s, parts=%d",
            self.config.model,
            len(messages),
        )

        resp = requests.post(
            url,
            json=body,
            timeout=self.config.timeout,
            headers={"Content-Type": "application/json"},
        )

        if resp.status_code != 200:
            self._handle_http_error(resp.status_code, resp.text)

        data = resp.json()

        # Parse response
        text = ""
        usage: dict[str, int] = {}

        try:
            candidates = data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                text = "".join(p.get("text", "") for p in parts)

            # Usage metadata
            if "usageMetadata" in data:
                meta = data["usageMetadata"]
                usage = {
                    "prompt_tokens": meta.get("promptTokenCount", 0),
                    "completion_tokens": meta.get("candidatesTokenCount", 0),
                    "total_tokens": meta.get("totalTokenCount", 0),
                }
        except (KeyError, IndexError, TypeError) as e:
            logger.warning("Gemini response parse warning: %s", e)

        # Attempt JSON parse
        json_data: Optional[dict] = None
        if response_mime_type == "application/json" or text.strip().startswith("{"):
            try:
                json_data = json.loads(text)
            except json.JSONDecodeError:
                pass

        return {
            "text": text,
            "json_data": json_data,
            "model": self.config.model,
            "provider": ProviderType.GEMINI.value,
            "usage": usage,
            "success": True,
            "error": None,
        }
