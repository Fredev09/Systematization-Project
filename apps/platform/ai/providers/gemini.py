"""
gemini.py — Google Gemini provider implementation.

Supports:
  - Gemini 2.5 Flash (default, recommended by Google AI Studio)
  - Gemini 2.5 Flash-Lite, Gemini 3 Flash / Pro (via GEMINI_MODEL env var)
  - Image analysis (base64 inline)
  - JSON mode via response_mime_type
  - System instructions

Configuration (.env):
  GEMINI_API_KEY=your_key
  GEMINI_MODEL=gemini-2.5-flash    (default)
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
            "[GEMINI] model=%s | endpoint=%s | messages=%d | temperature=%s | max_tokens=%s",
            self.config.model,
            url,
            len(messages),
            self.config.temperature,
            self.config.max_tokens,
        )

        # SAFE: API Key se envía como header X-Goog-Api-Key, NO en URL
        # (los parámetros URL pueden quedar registrados en logs de proxy/server)
        resp = requests.post(
            url,
            json=body,
            timeout=self.config.timeout,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.config.api_key,
            },
        )

        # Sanitizar: ocultar API key en caso de que aparezca en la respuesta
        resp_safe = resp.text[:1000].replace(self.config.api_key, "***") if self.config.api_key else resp.text[:1000]

        if resp.status_code != 200:
            logger.warning(
                "[GEMINI] HTTP %s | body=%s",
                resp.status_code,
                resp_safe,
            )
            self._handle_http_error(resp.status_code, resp.text)

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("[GEMINI] Invalid JSON response: %s", e)
            return {
                "text": "",
                "json_data": None,
                "model": self.config.model,
                "provider": ProviderType.GEMINI.value,
                "usage": {},
                "success": False,
                "error": f"Respuesta inválida del proveedor Gemini: {e}",
            }

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

    def stream_chat(
        self,
        system_instruction: str,
        messages: list[dict[str, Any]],
    ):
        """
        Stream Gemini response using server-sent events (alt=sse).
        """
        import json as _json
        import requests as _requests

        url = (
            f"{GEMINI_API_BASE}/{self.config.model}:streamGenerateContent"
        )

        body: dict[str, Any] = {
            "contents": messages,
            "generationConfig": {
                "temperature": self.config.temperature,
                "maxOutputTokens": self.config.max_tokens,
            },
        }

        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        resp = _requests.post(
            url,
            json=body,
            timeout=self.config.timeout,
            stream=True,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.config.api_key,
            },
        )

        if resp.status_code != 200:
            self._handle_http_error(resp.status_code, resp.text)
            return

        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = _json.loads(data_str)
                    candidates = data.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])
                        for part in parts:
                            text_chunk = part.get("text", "")
                            if text_chunk:
                                yield text_chunk
                except (_json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue

        resp.close()
