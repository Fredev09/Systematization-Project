"""
qwen.py — Alibaba Cloud Qwen provider implementation.

Uses the OpenAI-compatible API format (same as DeepSeek).
Qwen models are strong for Chinese documents but work excellently
for Spanish/Latin American business documents too.

Configuration (.env):
  QWEN_API_KEY=your_key
  QWEN_MODEL=qwen-plus    (default)
  AI_PROVIDER=qwen
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

QWEN_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class QwenProvider(BaseAIProvider):
    """
    Alibaba Cloud Qwen provider (OpenAI-compatible API).
    """

    def __init__(self, config: ProviderConfig):
        super().__init__(config)

    def _validate_config(self) -> None:
        if not self.config.api_key:
            raise ProviderNotAvailable(
                "qwen",
                "QWEN_API_KEY is not configured. "
                "Set QWEN_API_KEY in your .env or settings.",
            )

    def supports_images(self) -> bool:
        # Qwen-VL supports images; default model may not
        return "vl" in self.config.model.lower()

    def _call_api(
        self,
        system_instruction: str,
        messages: list[dict[str, Any]],
        response_mime_type: str = "text/plain",
    ) -> dict[str, Any]:
        url = f"{QWEN_API_BASE}/chat/completions"

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

        for msg in messages:
            role = msg.get("role", "user")
            parts = msg.get("parts", [])
            text_parts = [p["text"] for p in parts if "text" in p]
            content = " ".join(text_parts) if text_parts else ""
            body["messages"].append({"role": role, "content": content})

        if response_mime_type == "application/json":
            body["response_format"] = {"type": "json_object"}

        logger.debug(
            "Qwen request: model=%s, messages=%d",
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
            logger.warning("Qwen response parse warning: %s", e)

        return {
            "text": text,
            "json_data": json_data,
            "model": self.config.model,
            "provider": ProviderType.QWEN.value,
            "usage": usage,
            "success": True,
            "error": None,
        }
