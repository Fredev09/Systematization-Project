"""
deepseek.py — DeepSeek provider implementation.

Supports DeepSeek Chat and DeepSeek Reasoner models.

Configuration (.env):
  DEEPSEEK_API_KEY=your_key
  DEEPSEEK_MODEL=deepseek-chat    (default)
  AI_PROVIDER=deepseek
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

DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"


class DeepSeekProvider(BaseAIProvider):
    """
    DeepSeek provider (OpenAI-compatible API).
    """

    def __init__(self, config: ProviderConfig):
        super().__init__(config)

    def _validate_config(self) -> None:
        if not self.config.api_key:
            raise ProviderNotAvailable(
                "deepseek",
                "DEEPSEEK_API_KEY is not configured. "
                "Set DEEPSEEK_API_KEY in your .env or settings.",
            )

    def supports_images(self) -> bool:
        return False  # DeepSeek's current models are text-only

    def _call_api(
        self,
        system_instruction: str,
        messages: list[dict[str, Any]],
        response_mime_type: str = "text/plain",
    ) -> dict[str, Any]:
        url = f"{DEEPSEEK_API_BASE}/chat/completions"

        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        if system_instruction:
            body["messages"].append({
                "role": "system",
                "content": system_instruction,
            })

        # Convert Gemini-style messages to OpenAI format
        for msg in messages:
            role = msg.get("role", "user")
            parts = msg.get("parts", [])
            text_parts = [p["text"] for p in parts if isinstance(p, dict) and "text" in p]
            content = " ".join(text_parts) if text_parts else ""
            body["messages"].append({"role": role, "content": content})

        if response_mime_type == "application/json":
            body["response_format"] = {"type": "json_object"}

        logger.debug(
            "DeepSeek request: model=%s, messages=%d",
            self.config.model,
            len(body["messages"]),
        )

        resp = requests.post(
            url,
            json=body,
            timeout=self.config.timeout,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
        )

        if resp.status_code != 200:
            self._handle_http_error(resp.status_code, resp.text)

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("[DEEPSEEK] Invalid JSON response: %s", e)
            return {
                "text": "",
                "json_data": None,
                "model": self.config.model,
                "provider": ProviderType.DEEPSEEK.value,
                "usage": {},
                "success": False,
                "error": f"Respuesta inválida del proveedor DeepSeek: {e}",
            }

        text = ""
        usage: dict[str, int] = {}
        json_data: Optional[dict] = None

        try:
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content", "")
            text = content or ""

            if "usage" in data:
                usage = {
                    "prompt_tokens": data["usage"].get("prompt_tokens", 0),
                    "completion_tokens": data["usage"].get("completion_tokens", 0),
                    "total_tokens": data["usage"].get("total_tokens", 0),
                }

            if response_mime_type == "application/json" or text.strip().startswith("{"):
                try:
                    json_data = json.loads(text)
                except json.JSONDecodeError:
                    pass

        except (KeyError, IndexError, TypeError) as e:
            logger.warning("DeepSeek response parse warning: %s", e)

        return {
            "text": text,
            "json_data": json_data,
            "model": self.config.model,
            "provider": ProviderType.DEEPSEEK.value,
            "usage": usage,
            "success": True,
            "error": None,
        }
