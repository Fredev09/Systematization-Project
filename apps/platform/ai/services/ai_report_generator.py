"""
ai_report_generator.py — Reusable AI report generator (FASE 7).

Generates automatic reports for ANY form:
  - Executive summary
  - Anomalies and trends
  - KPIs and insights
  - Recommendations and risks
  - Chart explanations
  - Period comparison
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.ai.providers import get_provider
from apps.platform.ai.services.prompt_manager import get_prompt_manager
from apps.platform.ai.utils import safe_json_parse, truncate_text

logger = logging.getLogger(__name__)


@dataclass
class AIReport:
    """Complete AI-generated report."""
    executive_summary: str = ""
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    trends: list[dict[str, Any]] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    kpis: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)
    chart_explanations: dict[str, str] = field(default_factory=dict)
    period_comparison: Optional[dict[str, Any]] = None
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    raw_data: Optional[dict[str, Any]] = None


class AIReportGenerator:
    """
    Generates AI-powered reports for any form or dataset.
    
    Usage:
        generator = AIReportGenerator(provider)
        report = generator.generate(
            form_name="Ventas",
            data={"headers": [...], "rows": [[...], [...]]},
        )
        print(report.executive_summary)
    """

    def __init__(self, provider: Optional[BaseAIProvider] = None):
        self.provider = provider or get_provider()
        self.pm = get_prompt_manager()

    def generate(
        self,
        form_name: str,
        data: dict[str, Any],
        period: Optional[str] = None,
        report_type: str = "completo",
        use_cache: bool = True,
    ) -> AIReport:
        """
        Generate a report from form data.

        Args:
            form_name: Name of the form/report.
            data: Dict with headers, rows, and metadata.
            period: Optional period description (e.g., "Enero 2025").
            report_type: "completo", "ejecutivo", "anomalias", "kpi".
            use_cache: Whether to use cached results.

        Returns:
            AIReport with all sections.
        """
        headers = data.get("headers", [])
        rows = data.get("rows", [])
        metadata = data.get("metadata", {})

        # Build prompt
        prompt = self._build_prompt(form_name, headers, rows, period, report_type, metadata)

        response = self.provider.generate_json(
            prompt=prompt,
            system_instruction=(
                "Eres un analista de negocios senior con 20 años de experiencia. "
                "Genera reportes ejecutivos claros, accionables y bien estructurados. "
                "Responde ÚNICAMENTE con JSON válido."
            ),
            use_cache=use_cache,
        )

        if not response.success:
            return AIReport(
                executive_summary="No se pudo generar el reporte.",
                confidence=0.0,
                warnings=[response.error or "Report generation failed"],
            )

        parsed = response.json_data or {}
        return AIReport(
            executive_summary=parsed.get("resumen_ejecutivo", parsed.get("executive_summary", "")),
            anomalies=parsed.get("anomalias", parsed.get("anomalies", [])),
            trends=parsed.get("tendencias", parsed.get("trends", [])),
            insights=parsed.get("insights", []),
            kpis=parsed.get("kpis", []),
            recommendations=parsed.get("recomendaciones", parsed.get("recommendations", [])),
            risks=parsed.get("riesgos", parsed.get("risks", [])),
            opportunities=parsed.get("oportunidades", parsed.get("opportunities", [])),
            chart_explanations=parsed.get("explicaciones_graficos", parsed.get("chart_explanations", {})),
            period_comparison=parsed.get("comparacion_periodos", parsed.get("period_comparison")),
            confidence=parsed.get("confidence", 0.7),
            raw_data=parsed,
        )

    def _build_prompt(
        self,
        form_name: str,
        headers: list[str],
        rows: list[list[str]],
        period: Optional[str],
        report_type: str,
        metadata: dict[str, Any],
    ) -> str:
        """Build the report generation prompt."""
        parts = [f"Genera un reporte '{report_type}' para el formulario: {form_name}"]

        if period:
            parts.append(f"Período: {period}")

        parts.append(f"\nEncabezados: {', '.join(headers)}")
        parts.append(f"Total registros: {len(rows)}")

        # Sample rows (first 20)
        if rows:
            sample = "\n".join(
                " | ".join(str(cell)[:30] for cell in row[:10])
                for row in rows[:20]
            )
            parts.append(f"\nMuestra de datos:\n{sample}")

        if metadata:
            parts.append(f"\nMetadata: {metadata}")

        parts.append(
            "\n\nResponde ÚNICAMENTE con JSON con estas claves: "
            "resumen_ejecutivo, anomalias, tendencias, insights, "
            "kpis, recomendaciones, riesgos, oportunidades, "
            "explicaciones_graficos, confidence"
        )

        return "\n".join(parts)

    def generate_dashboard_summary(
        self,
        form_name: str,
        stats: dict[str, Any],
        use_cache: bool = True,
    ) -> str:
        """Generate a short dashboard summary text."""
        prompt = (
            f"Genera un resumen ejecutivo de 2-3 párrafos para el dashboard de '{form_name}' "
            f"con estos datos:\n{stats}\n\n"
            "Sé conciso, ejecutivo y destaca los puntos más importantes."
        )

        response = self.provider.analyze_text(
            text=prompt,
            system_instruction=(
                "Eres un analista de negocios senior. "
                "Genera resúmenes ejecutivos claros y accionables."
            ),
            use_cache=use_cache,
        )

        return response.text or "No se pudo generar el resumen."
