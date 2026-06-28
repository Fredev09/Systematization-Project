"""
report_tool.py — Generates AI-powered reports and summaries.
"""

from apps.platform.ai.tools.base import BaseTool, ExecutionContext, ToolResult, ToolSpec


class ReportTool(BaseTool):
    """Generates executive summaries, KPIs, trends, and insights from form data."""

    spec = ToolSpec(
        name="report",
        description="Genera reportes inteligentes: resumen ejecutivo, tendencias, KPIs, anomalías",
        parameters={
            "form_name": {"type": "string", "description": "Nombre del formulario"},
            "period": {"type": "string", "description": "Período del reporte"},
        },
        expected_output="Reporte estructurado con insights y recomendaciones",
        estimated_cost=0.003,
        estimated_time_ms=4000,
        category="reporting",
        requires_provider=True,
    )

    def execute(self, context: ExecutionContext) -> ToolResult:
        if not context.provider:
            return ToolResult(success=False, errors=["No provider"], confidence=0.0)

        form_name = context.form_proposal.get("form_name", "") if context.form_proposal else ""
        fields = context.fields

        prompt = (
            "Genera un reporte estructurado JSON con estos datos: "
            f"Formulario: {form_name}\n"
            f"Campos: {[f.get('name', '') for f in fields]}\n\n"
            "Incluye: resumen_ejecutivo, anomalías, tendencias, "
            "insights, KPIs, recomendaciones, riesgos, oportunidades."
        )

        response = context.provider.generate_json(
            prompt=prompt,
            system_instruction=(
                "Eres un analista de negocios experto. "
                "Genera reportes ejecutivos claros y accionables. "
                "Responde SIEMPRE con JSON válido."
            ),
            use_cache=context.use_cache,
        )

        if not response.success:
            return ToolResult(
                success=False,
                errors=[response.error or "Report generation failed"],
                confidence=0.0,
            )

        data = response.json_data or {}
        return ToolResult(
            success=True,
            data=data,
            confidence=data.get("confidence", 0.7),
        )
