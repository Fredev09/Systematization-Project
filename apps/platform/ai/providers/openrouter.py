"""
openrouter.py — OpenRouter provider implementation.

OpenRouter provides access to dozens of models (Claude, GPT, DeepSeek, Gemini, etc.)
through a single API. This provider lets the user choose any available model.

Configuration (.env):
  OPENROUTER_API_KEY=your_key
  OPENROUTER_MODEL=openai/gpt-4o-mini    (default)
  AI_PROVIDER=openrouter
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

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"


class OpenRouterProvider(BaseAIProvider):
    """
    OpenRouter multi-model provider.
    """

    def __init__(self, config: ProviderConfig):
        super().__init__(config)

    def _validate_config(self) -> None:
        if not self.config.api_key:
            raise ProviderNotAvailable(
                "openrouter",
                "OPENROUTER_API_KEY is not configured. "
                "Set OPENROUTER_API_KEY in your .env or settings.",
            )

    def supports_images(self) -> bool:
        # Most OpenRouter models support images; falls back gracefully
        return True

    def _call_api(
        self,
        system_instruction: str,
        messages: list[dict[str, Any]],
        response_mime_type: str = "text/plain",
    ) -> dict[str, Any]:
        url = f"{OPENROUTER_API_BASE}/chat/completions"

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

        # Convert Gemini-style parts messages to OpenAI format
        for msg in messages:
            role = msg.get("role", "user")
            parts = msg.get("parts", [])
            content_parts = []
            for part in parts:
                if "text" in part:
                    content_parts.append({"type": "text", "text": part["text"]})
                if "inline_data" in part:
                    mime = part["inline_data"]["mime_type"]
                    data = part["inline_data"]["data"]
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{data}",
                        },
                    })
            body["messages"].append({
                "role": role,
                "content": content_parts if len(content_parts) > 1 else content_parts[0]["text"],
            })

        if response_mime_type == "application/json":
            body["response_format"] = {"type": "json_object"}

        logger.debug(
            "OpenRouter request: model=%s, messages=%d",
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
                "HTTP-Referer": "https://codebuff.app",
            },
        )

        if resp.status_code != 200:
            self._handle_http_error(resp.status_code, resp.text)

        data = resp.json()

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
            logger.warning("OpenRouter response parse warning: %s", e)

        return {
            "text": text,
            "json_data": json_data,
            "model": self.config.model,
            "provider": ProviderType.OPENROUTER.value,
            "usage": usage,
            "success": True,
            "error": None,
        }
