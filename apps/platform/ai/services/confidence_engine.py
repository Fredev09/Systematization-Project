"""
confidence_engine.py — Structured confidence scoring (FASE 6).

Every AI result must produce a ConfidenceScore with:
  - overall: 0.0 to 1.0
  - reason: why this score
  - warnings: what to watch for
  - missing_information: what's missing
  - recommendations: what to do next
  - next_actions: suggested next steps

The application NEVER trusts AI blindly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from apps.platform.ai.services.reasoning_engine import ReasoningPath
from apps.platform.ai.tools.base import ToolResult

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceScore:
    """
    Structured confidence score for any AI result.
    
    Every AI response in the platform produces this.
    """
    overall: float = 0.0
    stars: int = 0
    label: str = "Sin evaluar"
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    field_scores: dict[str, float] = field(default_factory=dict)

    @property
    def is_reliable(self) -> bool:
        """Result is reliable enough to use without human review."""
        return self.overall >= 0.7

    @property
    def needs_review(self) -> bool:
        """Result needs human review before use."""
        return 0.3 <= self.overall < 0.7

    @property
    def needs_retry(self) -> bool:
        """Result confidence too low — should retry."""
        return self.overall < 0.3


_LABELS = {
    5: "Excelente",
    4: "Buena",
    3: "Regular",
    2: "Mala",
    1: "Muy mala",
}


class ConfidenceEngine:
    """
    Evaluates confidence of tool results and overall analysis.
    
    Factors:
      - Tool success rate (40%)
      - Individual tool confidences (30%)
      - Reasoning path confidence (20%)
      - Data completeness (10%)
    """

    def validate(
        self,
        results: list[ToolResult],
        reasoning: Optional[ReasoningPath] = None,
    ) -> ConfidenceScore:
        """
        Validate results and produce a confidence score.
        
        Args:
            results: Tool execution results.
            reasoning: Original reasoning path.
            
        Returns:
            ConfidenceScore with evaluation.
        """
        if not results:
            return ConfidenceScore(
                overall=0.0,
                stars=1,
                label="Sin datos",
                reason="No hay resultados de herramientas para evaluar",
                recommendations=["Ejecuta al menos una herramienta primero"],
                next_actions=["Revisar la configuración del análisis"],
            )

        score = ConfidenceScore()

        # Factor 1: Tool success rate (40%)
        success_rate = sum(1 for r in results if r.success) / len(results)
        score.field_scores["tool_success_rate"] = success_rate

        # Factor 2: Average confidence (30%)
        confidences = [r.confidence for r in results if r.confidence > 0]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        score.field_scores["avg_confidence"] = avg_confidence

        # Factor 3: Reasoning confidence (20%)
        reasoning_conf = reasoning.confidence if reasoning else 0.5
        score.field_scores["reasoning_confidence"] = reasoning_conf

        # Factor 4: Data quality (10%)
        has_data = sum(1 for r in results if r.data is not None) / len(results) if results else 0.0
        score.field_scores["data_quality"] = has_data

        # Weighted overall
        weights = {
            "tool_success_rate": 0.40,
            "avg_confidence": 0.30,
            "reasoning_confidence": 0.20,
            "data_quality": 0.10,
        }
        score.overall = sum(
            score.field_scores.get(k, 0.0) * v
            for k, v in weights.items()
        )

        # Stars
        score.stars = max(1, min(5, round(score.overall * 5)))
        score.label = _LABELS.get(score.stars, "Desconocida")

        # Reason
        if score.overall >= 0.8:
            score.reason = "Resultado confiable. Puede usarse sin revisión."
        elif score.overall >= 0.5:
            score.reason = "Resultado moderado. Se recomienda revisión humana."
        else:
            score.reason = "Confianza baja. Se requiere retry o intervención manual."

        # Warnings from results
        for r in results:
            score.warnings.extend(r.warnings)
            if not r.success:
                score.warnings.append(f"'{r.tool_name}' falló: {r.errors[:1]}")

        # Missing information
        for r in results:
            if r.missing_information:
                score.missing_information.extend(r.missing_information)

        # Recommendations
        if score.needs_review:
            score.recommendations.append("Revisa los resultados antes de continuar")
        if score.needs_retry:
            score.recommendations.append("Intenta con un proveedor AI diferente")
            score.next_actions.append("Cambiar proveedor y reintentar")
        if any("ocr" in r.tool_name and not r.success for r in results):
            score.recommendations.append("El OCR falló: intenta con una imagen de mejor calidad")
        if any("field_detector" in r.tool_name and not r.success for r in results):
            score.recommendations.append("La detección de campos falló: el documento podría no tener estructura clara")

        # Next actions
        if score.is_reliable:
            score.next_actions.append("Proceder con los resultados actuales")
            score.next_actions.append("Crear formulario y continuar")
        elif score.needs_review:
            score.next_actions.append("Revisar campos detectados manualmente")
            score.next_actions.append("Corregir tipos de campo si es necesario")
        else:
            score.next_actions.append("Reintentar con un documento más estructurado")
            score.next_actions.append("Usar un proveedor AI diferente")

        return score

    def score_field(
        self,
        field_name: str,
        field_type: str,
        confidence: float,
        has_data: bool = True,
    ) -> float:
        """Score individual field confidence."""
        base = confidence * 0.6
        type_known = 0.2 if field_type != "texto" else 0.1
        data_available = 0.2 if has_data else 0.0
        return min(base + type_known + data_available, 1.0)

    def compare(
        self,
        ai_result: ConfidenceScore,
        expected: Optional[ConfidenceScore] = None,
    ) -> dict[str, Any]:
        """Compare actual confidence vs expected."""
        if not expected:
            return {"difference": 0, "is_better": True}
        diff = ai_result.overall - expected.overall
        return {
            "difference": round(diff, 2),
            "is_better": diff >= 0,
            "ai_stars": ai_result.stars,
            "expected_stars": expected.stars,
        }
