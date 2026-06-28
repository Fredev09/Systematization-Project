"""
ai_matcher.py — Capa de matching semántico multi-proveedor.

AHORA utiliza apps.platform.ai en lugar de llamar a DeepSeek directamente.
Soporta cualquier proveedor configurado (Gemini, OpenRouter, DeepSeek, Qwen).

Se activa únicamente cuando el matching clásico (ColumnMatcher)
no alcanza el umbral de confianza mínimo (<70%).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from django.conf import settings

from apps.platform.ai.providers import get_provider
from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.ai.services.prompt_manager import get_prompt_manager
from apps.platform.ai.types import ProviderType

from .column_matching import ColumnMatchResult, normalizar_columna

logger = logging.getLogger(__name__)

AI_TIMEOUT = 10
"""Tiempo máximo de espera para la respuesta del AI."""

MAX_COLUMNAS_POR_LOTE = 30
"""Máximo de columnas a enviar en un solo lote."""


class AIMatcher:
    """
    Matching semántico multi-proveedor usando apps.platform.ai.

    Ya no depende de DeepSeek directamente. Usa el proveedor configurado
    en settings.AI_PROVIDER (gemini, openrouter, deepseek, qwen).

    Uso:
        matcher = AIMatcher()
        resultados = matcher.match_unresolved(
            unresolved_columns=[(0, 'Precio Vta')],
            field_names=['precio', 'nombre', 'stock'],
        )
    """

    def __init__(
        self,
        provider: Optional[BaseAIProvider] = None,
        api_key: Optional[str] = None,
        timeout: int = AI_TIMEOUT,
    ):
        self._provider = provider
        if api_key:
            # If explicit api_key provided, use DeepSeek
            from apps.platform.ai.types import ProviderConfig
            from apps.platform.ai.providers.deepseek import DeepSeekProvider
            config = ProviderConfig(
                provider_type=ProviderType.DEEPSEEK,
                api_key=api_key,
                model='deepseek-chat',
            )
            self._provider = DeepSeekProvider(config)

        self.timeout = timeout
        self._pm = None
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    def _get_provider(self) -> BaseAIProvider:
        """Lazy-init provider from settings."""
        if self._provider is None:
            self._provider = get_provider()
        return self._provider

    def _get_pm(self):
        """Lazy-init prompt manager."""
        if self._pm is None:
            self._pm = get_prompt_manager()
        return self._pm

    def match_unresolved(
        self,
        unresolved: list[tuple[int, str]],
        field_names: list[str],
    ) -> list[ColumnMatchResult]:
        """
        Intenta resolver columnas no mapeadas usando el AI configurado.

        Args:
            unresolved: Lista de (column_index, column_name).
            field_names: Lista de nombres de campo disponibles.

        Returns:
            Lista de ColumnMatchResult.
        """
        if not unresolved:
            return []

        try:
            provider = self._get_provider()
        except Exception as e:
            logger.warning('AIMatcher: proveedor no disponible: %s', e)
            self._available = False
            return [
                ColumnMatchResult(
                    column_index=idx,
                    column_name=name,
                    matched_to=None,
                    method=None,
                    confidence=0.0,
                    explanation=f'AI no disponible: {e}',
                )
                for idx, name in unresolved
            ]

        # Procesar en lotes
        resultados: list[ColumnMatchResult] = []
        for i in range(0, len(unresolved), MAX_COLUMNAS_POR_LOTE):
            lote = unresolved[i:i + MAX_COLUMNAS_POR_LOTE]
            lote_resultados = self._consultar_lote(provider, lote, field_names)
            resultados.extend(lote_resultados)

        return resultados

    def _consultar_lote(
        self,
        provider: BaseAIProvider,
        lote: list[tuple[int, str]],
        field_names: list[str],
    ) -> list[ColumnMatchResult]:
        """Consulta al proveedor AI para resolver un lote de columnas."""
        column_names = [name for _, name in lote]

        prompt = self._construir_prompt(column_names, field_names)

        try:
            response = provider.generate_json(
                prompt=prompt,
                system_instruction=(
                    'Eres un asistente que responde ÚNICAMENTE con '
                    'JSON válido. Nunca incluyas texto adicional, '
                    'markdown, ni bloques de código en tu respuesta.'
                ),
                use_cache=True,
            )

            if not response.success or not response.json_data:
                raise RuntimeError(response.error or 'Respuesta no es JSON')

            resultado_json = response.json_data
        except Exception as e:
            logger.warning('AIMatcher: error en llamada AI: %s', e)
            return [
                ColumnMatchResult(
                    column_index=idx,
                    column_name=name,
                    matched_to=None,
                    method=None,
                    confidence=0.0,
                    explanation=f'AI matching falló: {e}',
                )
                for idx, name in lote
            ]

        # Construir resultados
        resultados: list[ColumnMatchResult] = []
        for idx, col_name in lote:
            norm = normalizar_columna(col_name)
            match_info = resultado_json.get(norm, {})

            matched_to = match_info.get('field')
            confianza = match_info.get('confidence', 0.0)
            razon = match_info.get('reason', '')

            if matched_to and matched_to in field_names:
                resultados.append(ColumnMatchResult(
                    column_index=idx,
                    column_name=col_name,
                    matched_to=matched_to,
                    method='ai',
                    confidence=min(confianza, 0.95),
                    explanation=(
                        f'Coincidencia por AI ({provider.config.provider_type.value}): {razon}'
                    ),
                ))
            else:
                resultados.append(ColumnMatchResult(
                    column_index=idx,
                    column_name=col_name,
                    matched_to=None,
                    method=None,
                    confidence=0.0,
                    explanation=f'AI no encontró coincidencia: {razon}',
                ))

        return resultados

    def _construir_prompt(
        self,
        column_names: list[str],
        field_names: list[str],
    ) -> str:
        """Construye el prompt usando el PromptManager del módulo AI."""
        cols_str = '\n'.join(f'- "{c}"' for c in column_names)
        fields_str = ', '.join(f'"{f}"' for f in field_names)
        try:
            pm = self._get_pm()
            return pm.render(
                "match_columns",
                column_names=cols_str,
                field_names=fields_str,
            )
        except Exception as e:
            logger.warning("PromptManager falló, usando fallback: %s", e)
            cols_str = '\n'.join(f'- "{c}"' for c in column_names)
            fields_str = ', '.join(f'"{f}"' for f in field_names)
            return (
                'Eres un experto en mapeo de columnas de archivos Excel '
                'a campos de formularios.\n\n'
                f'Columnas del Excel:\n{cols_str}\n\n'
                f'Campos disponibles: {fields_str}\n\n'
                'Responde SOLO con JSON: {"columna_normalizada": '
                '{"field": "nombre_campo", "confidence": 0.0, "reason": ""}}'
            )
