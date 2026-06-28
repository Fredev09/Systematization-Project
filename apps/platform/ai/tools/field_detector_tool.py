"""
field_detector_tool.py — Detects fields and their types from structured data.
"""

from apps.platform.ai.services.field_detector import FieldDetector
from apps.platform.ai.tools.base import BaseTool, ExecutionContext, ToolResult, ToolSpec
from apps.platform.ai.types import DetectedField


class FieldDetectorTool(BaseTool):
    """Detects fields, types, and validations from document headers and sample data."""

    spec = ToolSpec(
        name="field_detector",
        description="Detecta campos y tipos a partir de encabezados y datos de muestra",
        parameters={
            "headers": {"type": "list", "description": "Encabezados de columna"},
            "sample_rows": {"type": "list", "description": "Filas de muestra"},
        },
        expected_output="Lista de campos detectados con tipos y confianza",
        estimated_cost=0.002,
        estimated_time_ms=2000,
        category="analysis",
        requires_provider=True,
    )

    def execute(self, context: ExecutionContext) -> ToolResult:
        if not context.provider:
            return ToolResult(success=False, errors=["No provider available"], confidence=0.0)

        headers = context.extracted_data.get("headers", [f.get("name") for f in context.fields])
        sample_rows = context.extracted_data.get("sample_rows")

        detector = FieldDetector(context.provider)
        fields = detector.analyze_data(
            headers=headers,
            sample_rows=sample_rows,
            use_cache=context.use_cache,
        )

        if not fields:
            return ToolResult(
                success=True,
                data={"fields": []},
                confidence=0.3,
                warnings=["No fields detected"],
            )

        return ToolResult(
            success=True,
            data={
                "fields": [
                    {
                        "name": f.name,
                        "type": f.suggested_type,
                        "required": f.required,
                        "unique": f.unique,
                        "is_identifier": f.is_identifier,
                        "confidence": f.confidence,
                        "explanation": f.explanation,
                    }
                    for f in fields
                ]
            },
            confidence=min(f.confidence for f in fields) if fields else 0.5,
        )
