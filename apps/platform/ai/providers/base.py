"""
base.py — Abstract interface for all AI providers.

Every provider must implement the BaseAIProvider interface.
This guarantees that services never depend on a specific provider.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from apps.platform.ai.cache import DiskCache, get_cache
from apps.platform.ai.exceptions import (
    JSONParseError,
    ProviderAuthError,
    ProviderNotAvailable,
    ProviderRateLimit,
)
from apps.platform.ai.types import AIResponse, ProviderConfig
from apps.platform.ai.utils import compute_content_hash, safe_json_parse

logger = logging.getLogger(__name__)


class BaseAIProvider(ABC):
    """
    Abstract interface for AI providers.

    All providers must implement these methods.
    Subclasses can override _call_api() which is the single
    point of contact with the external API.

    Caching is handled automatically by analyze_document, analyze_image,
    analyze_text, chat, and generate_json.
    """

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._cache: Optional[DiskCache] = None
        self._validate_config()

    # ──────────────────────────────────────────────
    # Subclass hooks
    # ──────────────────────────────────────────────

    @abstractmethod
    def _validate_config(self) -> None:
        """
        Validate provider configuration on init.
        Raise ProviderNotAvailable if the API key is missing.
        """
        ...

    @abstractmethod
    def _call_api(
        self,
        system_instruction: str,
        messages: list[dict[str, Any]],
        response_mime_type: str = "text/plain",
    ) -> dict[str, Any]:
        """
        Single point of contact with the external API.
        Must return a dict with keys:
          - text: str
          - json_data: dict | None
          - model: str
          - provider: str
          - usage: dict (prompt_tokens, completion_tokens, total_tokens)
          - success: bool
          - error: str | None
        """
        ...

    @abstractmethod
    def supports_images(self) -> bool:
        """Return True if this provider can process images."""
        ...

    # ──────────────────────────────────────────────
    # Streaming interface
    # ──────────────────────────────────────────────

    def stream_chat(
        self,
        system_instruction: str,
        messages: list[dict[str, Any]],
    ):
        """
        Stream a chat response token by token.

        Yields strings (text chunks) as they arrive from the provider.
        Default implementation wraps _call_api() in a single yield.
        Providers that support native streaming SHOULD override this.

        Args:
            system_instruction: System prompt text.
            messages: List of dicts with 'role' and 'parts' keys.

        Yields:
            str: text chunks as they arrive.
        """
        result = self._call_api(
            system_instruction=system_instruction,
            messages=messages,
        )
        text = result.get("text", "")
        if text:
            # Yield in word-sized chunks for progressive rendering
            words = text.split(" ")
            for i, word in enumerate(words):
                yield word + (" " if i < len(words) - 1 else "")
            yield "\n\n"

    def _stream_openai_compatible(
        self,
        api_url: str,
        api_key: str,
        body: dict[str, Any],
        provider_name: str,
        extra_headers: dict[str, str] | None = None,
    ):
        """
        Stream helper for OpenAI-compatible APIs (DeepSeek, OpenRouter, Qwen).

        These APIs all use the same SSE streaming format:
          data: {"choices":[{"delta":{"content":"..."}}]}
          data: [DONE]

        Args:
            api_url: Full URL endpoint.
            api_key: Bearer token.
            body: Request body dict (must NOT have stream=True — added here).
            provider_name: For logging.
            extra_headers: Optional extra HTTP headers.

        Yields:
            str: text chunks.
        """
        import json as _json

        body = dict(body)
        body["stream"] = True

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        logger.info("[DIAG] ENTER _stream_openai_compatible | provider=%s | url=%s | model=%s", provider_name, api_url, body.get("model", "?"))

        import requests as _requests
        resp = _requests.post(
            api_url,
            json=body,
            headers=headers,
            timeout=self.config.timeout,
            stream=True,
        )

        logger.info("[DIAG] _stream_openai_compatible HTTP | provider=%s | status=%d", provider_name, resp.status_code)

        if resp.status_code != 200:
            logger.info("[DIAG] _stream_openai_compatible non-200 | provider=%s | status=%d | body=%s", provider_name, resp.status_code, resp.text[:500])
            self._handle_http_error(resp.status_code, resp.text)
            return

        _yielded_count = 0
        _sse_line_count = 0
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            _sse_line_count += 1
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    logger.info("[DIAG] _stream_openai_compatible [DONE] | provider=%s | lines=%d | yielded=%d", provider_name, _sse_line_count, _yielded_count)
                    break
                try:
                    data = _json.loads(data_str)
                    choices = data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            _yielded_count += 1
                            if _yielded_count == 1:
                                logger.info("[DIAG] FIRST CHUNK from %s | len=%d | start='%s'", provider_name, len(content), content[:100])
                            if _yielded_count % 10 == 0:
                                logger.info("[DIAG] TOKEN COUNT in %s | yielded=%d", provider_name, _yielded_count)
                            yield content
                except (_json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
                    logger.warning("[DIAG] %s SSE parse error at line %d: %s | line='%s'", provider_name, _sse_line_count, str(e), line[:200])
                    continue

        logger.info("[DIAG] EXIT _stream_openai_compatible | provider=%s | lines=%d | yielded=%d", provider_name, _sse_line_count, _yielded_count)
        resp.close()

    # ──────────────────────────────────────────────
    # Public interface (with caching)
    # ──────────────────────────────────────────────

    def analyze_document(
        self,
        content: str,
        system_instruction: str = "",
        use_cache: bool = True,
    ) -> AIResponse:
        """
        Analyze a text document (Excel text, CSV text, etc.).
        Caching is based on SHA256(content + system_instruction).
        """
        return self._cached_call(
            content=content,
            system_instruction=system_instruction,
            use_cache=use_cache,
        )

    def analyze_image(
        self,
        image_data: str,  # base64
        mime_type: str = "image/jpeg",
        system_instruction: str = "",
        use_cache: bool = True,
    ) -> AIResponse:
        """
        Analyze an image (photo, scan, screenshot) via the provider.
        Only works if supports_images() returns True.
        """
        if not self.supports_images():
            raise ProviderNotAvailable(
                self.config.provider_type.value,
                "This provider does not support image analysis",
            )
        return self._cached_call(
            content=image_data,
            system_instruction=system_instruction,
            use_cache=use_cache,
            mime_type=mime_type,
        )

    def analyze_text(
        self,
        text: str,
        system_instruction: str = "",
        use_cache: bool = True,
    ) -> AIResponse:
        """
        Analyze plain text.
        """
        return self._cached_call(
            content=text,
            system_instruction=system_instruction,
            use_cache=use_cache,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        system_instruction: str = "",
        use_cache: bool = True,
    ) -> AIResponse:
        """
        Multi-turn chat. Caching uses the full messages list.
        """
        content = str(messages)
        return self._cached_call(
            content=content,
            system_instruction=system_instruction,
            use_cache=use_cache,
        )

    def generate_json(
        self,
        prompt: str,
        system_instruction: str = "",
        schema: Optional[dict[str, Any]] = None,
        use_cache: bool = True,
    ) -> AIResponse:
        """
        Generate a JSON response from the provider.
        Automatically parses the response and validates against schema hint.
        """
        raw = self._cached_call(
            content=prompt,
            system_instruction=system_instruction,
            use_cache=use_cache,
        )

        if raw.text:
            parsed = safe_json_parse(raw.text)
            if parsed is not None:
                raw.json_data = parsed
            else:
                raw.success = False
                raw.error = "Failed to parse JSON from response"

        return raw

    # ──────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────

    def _cached_call(
        self,
        content: str,
        system_instruction: str = "",
        use_cache: bool = True,
        mime_type: str = "",
    ) -> AIResponse:
        """
        Execute API call with optional caching.

        Si se proporciona mime_type (ej: 'image/jpeg'), construye los mensajes
        usando _build_messages_for_image() para enviar la imagen como inline_data
        en lugar de texto plano. Esto permite OCR real.
        """
        cache = self._get_cache()
        content_hash = compute_content_hash(content)
        cache_key = cache.build_key(
            prompt_text=system_instruction,
            content_hash=content_hash,
            provider=self.config.provider_type.value,
            model=self.config.model,
        )

        # Cache lookup
        if use_cache:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.info("Cache HIT for %s", self.config.provider_type.value)
                response = AIResponse(
                    text=cached.get("text", ""),
                    json_data=cached.get("json_data"),
                    model=cached.get("model", self.config.model),
                    provider=cached.get("provider", self.config.provider_type.value),
                    usage=cached.get("usage", {}),
                    success=True,
                    cached=True,
                )
                return response

        # API call
        t0 = time.perf_counter()
        try:
            # ── Construir mensajes según el tipo ──
            if mime_type and mime_type.startswith("image/"):
                # Enviar imagen como inline_data (OCR real)
                # system_instruction se pasa por separado a _call_api,
                # no se duplica en los mensajes de usuario.
                messages = self._build_messages_for_image(
                    image_data=content,
                    mime_type=mime_type,
                    system_instruction=system_instruction,
                    text_prompt="",
                )
            else:
                # Texto plano
                messages = [{"role": "user", "parts": [{"text": content}]}]

            result = self._call_api(
                system_instruction=system_instruction,
                messages=messages,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000

            response = AIResponse(
                text=result.get("text", ""),
                json_data=result.get("json_data"),
                model=result.get("model", self.config.model),
                provider=result.get("provider", self.config.provider_type.value),
                usage=result.get("usage", {}),
                processing_time_ms=elapsed_ms,
                success=result.get("success", True),
                error=result.get("error"),
            )

            # Cache the result
            if use_cache and response.success:
                cache.set(
                    key=cache_key,
                    data={
                        "text": response.text,
                        "json_data": response.json_data,
                        "model": response.model,
                        "provider": response.provider,
                        "usage": response.usage,
                    },
                    provider=response.provider,
                    model=response.model,
                )

            return response

        except ProviderRateLimit:
            raise
        except ProviderAuthError:
            raise
        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.error("AI provider call failed: %s", e, exc_info=True)
            return AIResponse(
                text="",
                success=False,
                error=str(e),
                processing_time_ms=elapsed_ms,
                provider=self.config.provider_type.value,
                model=self.config.model,
            )

    def _get_cache(self) -> DiskCache:
        if self._cache is None:
            self._cache = get_cache()
        return self._cache

    def _build_messages_for_image(
        self,
        image_data: str,
        mime_type: str,
        system_instruction: str,
        text_prompt: str = "",
    ) -> list[dict[str, Any]]:
        """
        Build messages list for image analysis (OCR real).
        
        Envía la imagen como inline_data con su mime_type real.
        Si hay system_instruction, se incluye como texto adicional.
        """
        parts: list[dict[str, Any]] = [
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": image_data,
                }
            },
        ]
        prompt_text = text_prompt or system_instruction
        if prompt_text:
            parts.append({"text": prompt_text})
        return [{"role": "user", "parts": parts}]

    def _handle_http_error(self, status_code: int, body: Any) -> None:
        """
        Handle common HTTP error codes from providers.
        
        Extrae el mensaje de error real del JSON de respuesta del provider
        (ej: Google Gemini devuelve {"error": {"message": "..."}})
        y lo incluye en la excepción para diagnóstico.
        
        SAFE: El body se trunca y sanitiza para evitar exponer
        datos sensibles (API keys, tokens) en logs y excepciones.
        """
        body_str = str(body)[:500] if body else ""
        
        # Intentar extraer error.message del JSON del provider
        error_message = ""
        try:
            import json
            error_data = json.loads(body_str)
            err_obj = error_data.get("error", {})
            if isinstance(err_obj, dict):
                error_message = err_obj.get("message", "")
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
        
        # Log completo a DEBUG para diagnóstico
        if body_str:
            logger.debug(
                "Provider HTTP %d body: %s",
                status_code,
                body_str[:500],
            )
        
        import re
        body_safe = re.sub(
            r'(api[_-]?key|authorization|bearer|token|secret|apikey)[=: ]+[^\s,;"]+',
            r'\1=***',
            body_str,
            flags=re.IGNORECASE,
        )[:200]
        
        if status_code == 400:
            raise ProviderNotAvailable(
                self.config.provider_type.value,
                f"HTTP 400: {error_message or body_safe}",
            )
        elif status_code == 401 or status_code == 403:
            raise ProviderAuthError(
                self.config.provider_type.value,
                detail=error_message,
            )
        elif status_code == 404:
            raise ProviderNotAvailable(
                self.config.provider_type.value,
                f"HTTP 404: {error_message or 'Modelo/servicio no encontrado. Verifica el modelo configurado.'}",
            )
        elif status_code == 429:
            raise ProviderRateLimit(
                self.config.provider_type.value,
                detail=error_message or body_safe,
            )
        elif status_code >= 500:
            raise ProviderNotAvailable(
                self.config.provider_type.value,
                f"HTTP {status_code}: {error_message or body_safe}",
            )
        else:
            raise ProviderNotAvailable(
                self.config.provider_type.value,
                f"HTTP {status_code}: {error_message or body_safe}",
            )
