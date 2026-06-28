"""
providers — AI Provider implementations.

Each provider implements the BaseAIProvider interface.
The factory function get_provider() returns the configured provider.
"""

from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings

from apps.platform.ai.exceptions import ProviderNotAvailable
from apps.platform.ai.types import ProviderConfig, ProviderType

logger = logging.getLogger(__name__)

_PROVIDER_CACHE: dict[str, "BaseAIProvider"] = {}


def get_provider(
    provider_type: Optional[ProviderType] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> "BaseAIProvider":
    """
    Factory: returns the configured AI provider instance.

    Resolution order:
      1. Explicit `provider_type` argument
      2. settings.AI_PROVIDER (string in .env)
      3. Default: GEMINI

    Caches the provider instance by provider_type.value so subsequent
    calls reuse the same connection configuration.
    """
    if provider_type is None:
        raw = getattr(settings, "AI_PROVIDER", "gemini")
        provider_type = ProviderType.from_string(raw)

    if provider_type in _PROVIDER_CACHE:
        return _PROVIDER_CACHE[provider_type]

    config = _build_config(provider_type, api_key=api_key, model=model)

    if provider_type == ProviderType.GEMINI:
        from apps.platform.ai.providers.gemini import GeminiProvider
        instance = GeminiProvider(config)
    elif provider_type == ProviderType.OPENROUTER:
        from apps.platform.ai.providers.openrouter import OpenRouterProvider
        instance = OpenRouterProvider(config)
    elif provider_type == ProviderType.DEEPSEEK:
        from apps.platform.ai.providers.deepseek import DeepSeekProvider
        instance = DeepSeekProvider(config)
    elif provider_type == ProviderType.QWEN:
        from apps.platform.ai.providers.qwen import QwenProvider
        instance = QwenProvider(config)
    else:
        raise ProviderNotAvailable(provider_type.value, "Unknown provider type")

    _PROVIDER_CACHE[provider_type] = instance
    logger.info(
        "AI provider initialized: %s (model=%s)",
        provider_type.value, config.model or "default"
    )
    return instance


def _build_config(
    provider_type: ProviderType,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> ProviderConfig:
    """Build ProviderConfig from settings or explicit arguments."""
    config = ProviderConfig(provider_type=provider_type)

    # Map provider -> setting attribute name
    key_attrs = {
        ProviderType.GEMINI: "GEMINI_API_KEY",
        ProviderType.OPENROUTER: "OPENROUTER_API_KEY",
        ProviderType.DEEPSEEK: "DEEPSEEK_API_KEY",
        ProviderType.QWEN: "QWEN_API_KEY",
    }
    model_attrs = {
        ProviderType.GEMINI: ("GEMINI_MODEL", "gemini-2.0-flash"),
        ProviderType.OPENROUTER: ("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        ProviderType.DEEPSEEK: ("DEEPSEEK_MODEL", "deepseek-chat"),
        ProviderType.QWEN: ("QWEN_MODEL", "qwen-plus"),
    }

    config.api_key = api_key or getattr(settings, key_attrs.get(provider_type, ""), "")
    attr, default = model_attrs.get(provider_type, ("", ""))
    config.model = model or getattr(settings, attr, default)
    config.temperature = getattr(settings, "AI_TEMPERATURE", 0.1)
    config.max_tokens = getattr(settings, "AI_MAX_TOKENS", 4096)
    config.timeout = getattr(settings, "AI_TIMEOUT", 30)

    return config


def clear_provider_cache() -> None:
    """Clear cached provider instances (useful for tests)."""
    _PROVIDER_CACHE.clear()


__all__ = [
    "get_provider",
    "clear_provider_cache",
]
