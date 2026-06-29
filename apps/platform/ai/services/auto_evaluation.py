"""
auto_evaluation.py — Auto Evaluation Service (FASE 9, v4.0 FREE-FIRST).

Después de cada llamada AI, evalúa automáticamente:

  - ¿Respuesta útil? (no vacía, no error)
  - ¿JSON válido? (si se esperaba JSON)
  - ¿Campos completos? (si se esperaban campos específicos)
  - ¿Confianza adecuada?
  - ¿Errores?

Guarda estadísticas para mejorar el sistema con el tiempo.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from apps.platform.ai.services.confidence_engine import ConfidenceEngine, ConfidenceScore
from apps.platform.ai.types import AIResponse

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """Resultado de la evaluación automática de una respuesta AI."""
    success: bool
    is_useful: bool = False
    is_valid_json: bool = False
    has_required_fields: bool = False
    confidence_adequate: bool = False
    has_errors: bool = False
    error_count: int = 0
    missing_fields: list[str] = field(default_factory=list)
    score: float = 0.0  # 0.0 a 1.0
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    evaluation_time_ms: float = 0.0


class AutoEvaluator:
    """
    Evalúa automáticamente la calidad de respuestas AI.

    Se ejecuta después de cada llamada AI para:
      1. Verificar que la respuesta sea utilizable
      2. Detectar problemas temprano
      3. Acumular estadísticas de calidad
      4. Sugerir mejoras

    Usage:
        evaluator = AutoEvaluator()
        evaluation = evaluator.evaluate(response, expected_type="json")
        if not evaluation.is_useful:
            logger.warning("Respuesta AI no utilizable: %s", evaluation.warnings)
    """

    def __init__(self):
        self.confidence_engine = ConfidenceEngine()

    def evaluate(
        self,
        response: AIResponse,
        expected_type: str = "text",
        required_fields: Optional[list[str]] = None,
        prompt: str = "",
    ) -> EvaluationResult:
        """
        Evalúa una respuesta AI.

        Args:
            response: Respuesta AI a evaluar.
            expected_type: "json", "text", o "any".
            required_fields: Campos que deben estar presentes (si expected_type="json").
            prompt: Prompt original (para estadísticas).

        Returns:
            EvaluationResult con puntuación y advertencias.
        """
        t0 = time.perf_counter()
        result = EvaluationResult(success=False)

        # 1. ¿Respuesta útil?
        result.is_useful = bool(response.text) and response.success
        if not result.is_useful:
            result.warnings.append(response.error or "Respuesta vacía o fallida")
            result.suggestions.append("Reintentar con un proveedor diferente")
            result.suggestions.append("Verificar que el prompt tenga suficiente contexto")
            result.score = 0.0
            result.evaluation_time_ms = (time.perf_counter() - t0) * 1000
            return result

        # 2. ¿JSON válido?
        if expected_type == "json":
            result.is_valid_json = response.json_data is not None
            if not result.is_valid_json:
                result.warnings.append("Se esperaba JSON pero la respuesta no es JSON válido")
                result.suggestions.append("Agregar 'Responde ÚNICAMENTE con JSON' al prompt")
            elif required_fields:
                # 3. ¿Campos completos?
                missing = [
                    f for f in required_fields
                    if f not in response.json_data
                ]
                if missing:
                    result.missing_fields = missing
                    result.has_required_fields = False
                    result.warnings.append(f"Campos faltantes: {', '.join(missing)}")
                    result.suggestions.append(f"Agregar instrucción específica para incluir: {', '.join(missing)}")
                else:
                    result.has_required_fields = True

        # 4. ¿Confianza adecuada?
        cs = self.confidence_engine.score_field(
            field_name="ai_response",
            field_type=expected_type,
            confidence=0.8 if response.success else 0.0,
            has_data=bool(response.text),
        )
        result.confidence_adequate = cs >= 0.5

        # 5. ¿Errores?
        result.has_errors = not response.success or bool(response.error)
        if response.error:
            result.error_count = 1
            result.warnings.append(response.error)

        # 6. Score general
        scores = []
        if result.is_useful:
            scores.append(0.4)
        if result.is_valid_json or expected_type != "json":
            scores.append(0.3)
        if result.has_required_fields or not required_fields:
            scores.append(0.2)
        if result.confidence_adequate:
            scores.append(0.1)
        result.score = sum(scores)
        result.success = result.score >= 0.5

        # Si la puntuación es baja, sugerir acciones
        if result.score < 0.5:
            result.suggestions.append("Usar un proveedor AI más potente")
            result.suggestions.append("Simplificar el prompt")

        result.evaluation_time_ms = (time.perf_counter() - t0) * 1000
        return result

    def evaluate_batch(
        self,
        responses: list[AIResponse],
        expected_type: str = "text",
        required_fields: Optional[list[str]] = None,
    ) -> list[EvaluationResult]:
        """Evalúa múltiples respuestas."""
        return [
            self.evaluate(r, expected_type, required_fields)
            for r in responses
        ]

    def get_summary_stats(
        self,
        evaluations: list[EvaluationResult],
    ) -> dict[str, Any]:
        """Genera estadísticas resumidas de un conjunto de evaluaciones."""
        if not evaluations:
            return {"total": 0}

        total = len(evaluations)
        useful = sum(1 for e in evaluations if e.is_useful)
        valid_json = sum(1 for e in evaluations if e.is_valid_json)
        complete = sum(1 for e in evaluations if e.has_required_fields)
        avg_score = sum(e.score for e in evaluations) / total

        return {
            "total": total,
            "useful": useful,
            "useful_pct": round(useful / total * 100, 1),
            "valid_json": valid_json,
            "valid_json_pct": round(valid_json / total * 100, 1),
            "complete": complete,
            "complete_pct": round(complete / total * 100, 1),
            "avg_score": round(avg_score, 2),
            "common_warnings": self._most_common_warnings(evaluations),
        }

    def _most_common_warnings(self, evaluations: list[EvaluationResult], top: int = 5) -> list[str]:
        """Obtiene las advertencias más comunes."""
        from collections import Counter
        all_warnings = [w for e in evaluations for w in e.warnings]
        return [w for w, _ in Counter(all_warnings).most_common(top)]


_default_evaluator: Optional[AutoEvaluator] = None


def get_auto_evaluator() -> AutoEvaluator:
    global _default_evaluator
    if _default_evaluator is None:
        _default_evaluator = AutoEvaluator()
    return _default_evaluator
