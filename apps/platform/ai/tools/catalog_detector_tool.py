"""
catalog_detector_tool.py — Detects catalog (list) columns from data.
"""

from apps.platform.ai.tools.base import BaseTool, ExecutionContext, ToolResult, ToolSpec
from apps.platform.document_intelligence.extractors.base import ExtractedDocument
from apps.platform.document_intelligence.services.catalog_detector import CatalogDetector


class CatalogDetectorTool(BaseTool):
    """Detects columns that should be List (catalog) fields based on repeated values."""

    spec = ToolSpec(
        name="catalog_detector",
        description="Detecta columnas con valores repetidos que deberían ser campos tipo Lista",
        parameters={
            "columns": {"type": "list", "description": "Nombres de columnas"},
            "rows": {"type": "list", "description": "Datos del documento"},
        },
        expected_output="Sugerencias de catálogo con opciones y confianza",
        estimated_cost=0.0,
        estimated_time_ms=50,
        category="analysis",
        requires_provider=False,
    )

    def execute(self, context: ExecutionContext) -> ToolResult:
        columns = context.extracted_data.get("columns", [f.get("name") for f in context.fields])
        rows = context.extracted_data.get("rows", [])

        if not columns or not rows:
            return ToolResult(
                success=False,
                warnings=["No columns or rows to analyze"],
                confidence=0.0,
            )

        doc = ExtractedDocument(columns=columns, rows=rows)
        detector = CatalogDetector()
        suggestions = detector.detect(doc)

        return ToolResult(
            success=True,
            data={
                "catalogs": [
                    {
                        "column": s.column_name,
                        "options": s.options,
                        "unique_count": s.unique_count,
                        "confidence": s.confidence,
                    }
                    for s in suggestions
                ]
            },
            confidence=min((s.confidence for s in suggestions), default=0.0),
        )
