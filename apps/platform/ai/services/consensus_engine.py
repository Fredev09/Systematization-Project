"""
consensus_engine.py — Consensus Engine (FASE 6, v4.0 FREE-FIRST).

Para tareas importantes, consulta múltiples modelos gratuitos:

  1. Consultar dos modelos gratuitos diferentes
  2. Comparar respuestas
  3. Si coinciden → aceptar con alta confianza
  4. Si difieren → tercera validación heurística

Esto NO se aplica a todas las llamadas — solo cuando:
  - La confianza inicial es baja (< 0.7)
  - Es una tarea crítica (crear formulario, importar datos)
  - El costo de la llamada es bajo (texto corto, sin imágenes)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from apps.platform.ai.providers import get_provider
from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.ai.services.budget_manager import get_budget_manager
from apps.platform.ai.services.confidence_engine import ConfidenceEngine
from apps.platform.ai.types import AIResponse, ProviderType

logger = logging.getLogger(__name__)


# ======================================================================
# Data Classes
# ======================================================================

@dataclass
class ConsensusVote:
    """Voto de un modelo en el consenso."""
    provider: str
    model: str
    response_text: str
    confidence: float
    tokens: int
    time_ms: float
    success: bool


@dataclass
class ConsensusResult:
    """Resultado completo del consenso entre modelos."""
    task: str
    votes: list[ConsensusVote] = field(default_factory=list)
    consensus_text: str = ""
    consensus_json: Optional[dict[str, Any]] = None
    agreement: float = 0.0  # 0.0 a 1.0
    is_reliable: bool = False
    tiebreaker_needed: bool = False
    tiebreaker_result: str = ""
    processing_time_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)


# ======================================================================
# Consensus Engine
# ======================================================================

class ConsensusEngine:
    """
    Consulta múltiples modelos gratuitos y construye consenso.

    Proceso:
      1. Seleccionar 2 proveedores gratuitos diferentes
      2. Consultar ambos con el mismo prompt
      3. Comparar respuestas (JSON o texto estructurado)
      4. Si coinciden → aceptar (agreement ≥ 0.7)
      5. Si difieren → validación heurística adicional

    FREE-FIRST: Solo usa modelos gratuitos.
    Solo se activa para tareas importantes con bajo costo estimado.

    Usage:
        engine = ConsensusEngine()
        result = engine.run(
            prompt="Extrae los campos de: nombre, precio, stock",
            providers=["deepseek", "qwen"],  # opcional
        )
        if result.is_reliable:
            print(result.consensus_json)
    """

    # Costo máximo (en tokens de entrada) para aplicar consenso
    # Si el prompt es muy largo, el consenso costaría demasiado
    MAX_PROMPT_TOKENS_CONSENSUS = 2000

    def __init__(self):
        self.budget = get_budget_manager()

    def run(
        self,
        prompt: str,
        system_instruction: str = "",
        providers: Optional[list[str]] = None,
        expected_type: str = "json",
        use_cache: bool = True,
    ) -> ConsensusResult:
        """
        Ejecuta consenso entre múltiples modelos gratuitos.

        Args:
            prompt: Prompt a enviar.
            system_instruction: Instrucción del sistema.
            providers: Lista de proveedores a consultar (mínimo 2).
            expected_type: "json" o "text" — afecta cómo se comparan.
            use_cache: Usar caché.

        Returns:
            ConsensusResult con acuerdo o desacuerdo.
        """
        t0 = time.perf_counter()
        result = ConsensusResult(task=prompt[:100])

        # 0. Validar tamaño del prompt (FREE-FIRST: solo consenso en prompts pequeños)
        estimated_tokens = len(prompt) // 3  # chars → tokens approx
        if estimated_tokens > self.MAX_PROMPT_TOKENS_CONSENSUS:
            result.warnings.append(
                f"Prompt demasiado grande (~{estimated_tokens} tokens, máx {self.MAX_PROMPT_TOKENS_CONSENSUS}). "
                "Consenso saltado para ahorrar tokens. Usando un solo proveedor."
            )
            vote = self._query_provider(providers[0] if providers else "deepseek", prompt, system_instruction, use_cache)
            if vote:
                result.votes = [vote]
                result.consensus_text = vote.response_text
                result.is_reliable = False
                result.agreement = 0.5
            return result

        # 1. Determinar proveedores
        if not providers:
            providers = self._select_providers()

        if not providers:
            result.warnings.append("Ningún proveedor disponible para consenso.")
            return result

        if len(providers) < 2:
            result.warnings.append(
                f"Solo {len(providers)} proveedor(es) disponible(s). "
                "Se necesita al menos 2 para consenso."
            )
            vote = self._query_provider(providers[0], prompt, system_instruction, use_cache)
            if vote:
                result.votes.append(vote)
                result.consensus_text = vote.response_text
                result.is_reliable = False
                result.agreement = 0.5
            return result

        # 2. Consultar primer proveedor
        vote1 = self._query_provider(providers[0], prompt, system_instruction, use_cache)
        if vote1:
            result.votes.append(vote1)

        # 2b. Si el primer proveedor ya es confiable, saltar el segundo (FREE-FIRST)
        confidence_engine = ConfidenceEngine()
        if vote1 and vote1.confidence >= 0.8:
            # Crear un ToolResult simulado para ConfidenceEngine
            from apps.platform.ai.tools.base import ToolResult
            from apps.platform.ai.services.reasoning_engine import ReasoningPath
            mock_result = ToolResult(
                success=vote1.success,
                tool_name="consensus_vote",
                confidence=vote1.confidence,
            )
            mock_reasoning = ReasoningPath(task=prompt[:100], confidence=vote1.confidence)
            cs = confidence_engine.validate([mock_result], mock_reasoning)

            if cs.is_reliable:
                result.is_reliable = True
                result.agreement = 1.0
                result.consensus_text = vote1.response_text
                try:
                    result.consensus_json = json.loads(vote1.response_text)
                except (json.JSONDecodeError, TypeError):
                    pass
                result.processing_time_ms = (time.perf_counter() - t0) * 1000
                logger.info(
                    "Consensus: skipped 2nd model — %s already reliable (%.0f%%)",
                    vote1.provider, vote1.confidence * 100,
                )
                return result

        # 3. Consultar segundo proveedor (solo si el primero no fue confiable)
        if len(providers) >= 2:
            vote2 = self._query_provider(providers[1], prompt, system_instruction, use_cache)
            if vote2:
                result.votes.append(vote2)

        # 4. Comparar respuestas
        if len(result.votes) >= 2:
            v1, v2 = result.votes[0], result.votes[1]

            if expected_type == "json":
                agreement = self._compare_json(v1, v2)
            else:
                agreement = self._compare_text(v1, v2)

            result.agreement = agreement

            if agreement >= 0.7:
                # Consenso alcanzado
                result.is_reliable = True
                result.consensus_text = v1.response_text
                if v1.response_text and v2.response_text:
                    # Usar la respuesta con mayor confianza
                    primary = v1 if v1.confidence >= v2.confidence else v2
                    result.consensus_text = primary.response_text
                    try:
                        result.consensus_json = json.loads(primary.response_text)
                    except (json.JSONDecodeError, TypeError):
                        pass
                logger.info(
                    "Consensus: AGREEMENT %.0f%% entre %s y %s",
                    agreement * 100, v1.provider, v2.provider,
                )
            else:
                # Desacuerdo — necesitamos tiebreaker
                result.tiebreaker_needed = True
                result.warnings.append(
                    f"Bajo acuerdo ({agreement:.0%}) entre {v1.provider} y {v2.provider}. "
                    "Aplicando tiebreaker heurístico."
                )

                # Tiebreaker: usar el que tenga mayor confianza
                primary = v1 if v1.confidence >= v2.confidence else v2
                result.consensus_text = primary.response_text
                try:
                    result.consensus_json = json.loads(primary.response_text)
                except (json.JSONDecodeError, TypeError):
                    pass
                result.tiebreaker_result = (
                    f"Tiebreaker: {primary.provider} (confianza {primary.confidence:.0%})"
                )
                result.is_reliable = primary.confidence >= 0.7

                logger.info(
                    "Consensus: DISAGREEMENT (%.0f%%). Tiebreaker → %s",
                    agreement * 100, primary.provider,
                )

        elif len(result.votes) == 1:
            result.consensus_text = result.votes[0].response_text
            result.is_reliable = False
            result.warnings.append("Solo 1 voto obtenido. No hay consenso real.")

        result.processing_time_ms = (time.perf_counter() - t0) * 1000
        return result

    def _select_providers(self) -> list[str]:
        """Selecciona 2 proveedores gratuitos diferentes disponibles."""
        available = []
        for p in ["deepseek", "qwen", "gemini", "openrouter"]:
            if self.budget.can_call(p, estimated_tokens=500):
                available.append(p)
        return available[:3]  # Hasta 3 para tener margen

    def _query_provider(
        self,
        provider_name: str,
        prompt: str,
        system_instruction: str,
        use_cache: bool,
    ) -> Optional[ConsensusVote]:
        """Consulta a un proveedor y registra el resultado."""
        try:
            t0 = time.perf_counter()
            provider = get_provider(
                provider_type=ProviderType.from_string(provider_name)
            )

            response = provider.generate_json(
                prompt=prompt,
                system_instruction=system_instruction,
                use_cache=use_cache,
            )

            elapsed_ms = (time.perf_counter() - t0) * 1000

            # Registrar en budget
            usage_data = response.usage if isinstance(response.usage, dict) else {}
            total_tokens = usage_data.get("total_tokens", 0)
            self.budget.record_call(
                provider=provider_name,
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
            )

            return ConsensusVote(
                provider=provider_name,
                model=response.model or provider_name,
                response_text=response.text or "",
                confidence=0.8 if response.success else 0.0,
                tokens=total_tokens,
                time_ms=elapsed_ms,
                success=response.success,
            )

        except Exception as e:
            logger.warning("Consensus: %s failed: %s", provider_name, e)
            return None

    def _compare_json(self, v1: ConsensusVote, v2: ConsensusVote) -> float:
        """Compara dos respuestas JSON y calcula acuerdo."""
        try:
            j1 = json.loads(v1.response_text)
            j2 = json.loads(v2.response_text)
        except (json.JSONDecodeError, TypeError):
            return self._compare_text(v1, v2)

        if not isinstance(j1, dict) or not isinstance(j2, dict):
            return self._compare_text(v1, v2)

        return self._dict_agreement(j1, j2)

    def _compare_text(self, v1: ConsensusVote, v2: ConsensusVote) -> float:
        """Compara dos respuestas de texto y calcula acuerdo."""
        t1 = v1.response_text.strip().lower()
        t2 = v2.response_text.strip().lower()

        if not t1 or not t2:
            return 0.0

        # Jaccard similarity de palabras
        words1 = set(t1.split())
        words2 = set(t2.split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    def _dict_agreement(self, d1: dict, d2: dict) -> float:
        """Calcula acuerdo entre dos diccionarios JSON."""
        if not d1 and not d2:
            return 1.0
        if not d1 or not d2:
            return 0.0

        keys1 = set(d1.keys())
        keys2 = set(d2.keys())

        if not keys1 and not keys2:
            return 1.0
        if not keys1 or not keys2:
            return 0.0

        # Acuerdo de keys
        key_agreement = len(keys1 & keys2) / len(keys1 | keys2)

        # Acuerdo de valores (para keys comunes)
        common_keys = keys1 & keys2
        if not common_keys:
            return key_agreement * 0.5

        value_matches = sum(
            1 for k in common_keys
            if str(d1.get(k, "")).lower() == str(d2.get(k, "")).lower()
        )
        value_agreement = value_matches / len(common_keys)

        return key_agreement * 0.3 + value_agreement * 0.7


# Singleton
_default_consensus: Optional[ConsensusEngine] = None


def get_consensus_engine() -> ConsensusEngine:
    """Return the default ConsensusEngine instance (singleton)."""
    global _default_consensus
    if _default_consensus is None:
        _default_consensus = ConsensusEngine()
    return _default_consensus
