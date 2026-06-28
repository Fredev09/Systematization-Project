"""
similarity_finder_tool.py — Finds similar existing forms.
"""

from apps.platform.ai.tools.base import BaseTool, ExecutionContext, ToolResult, ToolSpec
from apps.platform.document_intelligence.services.form_similarity_finder import FormSimilarityFinder


class SimilarityFinderTool(BaseTool):
    """Finds existing forms similar to the proposed fields."""

    spec = ToolSpec(
        name="similarity_finder",
        description="Busca formularios existentes similares para evitar duplicación",
        parameters={
            "field_names": {"type": "list", "description": "Nombres de campos propuestos"},
        },
        expected_output="Lista de formularios similares con % de coincidencia",
        estimated_cost=0.0,
        estimated_time_ms=100,
        category="search",
        requires_provider=False,
    )

    def execute(self, context: ExecutionContext) -> ToolResult:
        field_names = [f.get("name", "") for f in context.fields]
        if not field_names:
            return ToolResult(
                success=False,
                warnings=["No field names to compare"],
                confidence=0.0,
            )

        finder = FormSimilarityFinder()
        similar = finder.find_similar([{"name": n} for n in field_names])

        return ToolResult(
            success=True,
            data={
                "similar_forms": [
                    {
                        "id": sf.get("id"),
                        "nombre": sf.get("nombre"),
                        "similitud": sf.get("similitud", 0),
                        "campos_coincidentes": sf.get("campos_coincidentes", 0),
                    }
                    for sf in similar
                ]
            },
            confidence=0.9 if similar else 0.0,
        )
