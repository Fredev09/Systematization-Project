"""
relationship_detector_tool.py — Detects field relationships and foreign keys.
"""

from apps.platform.ai.tools.base import BaseTool, ExecutionContext, ToolResult, ToolSpec
from apps.platform.document_intelligence.extractors.base import ExtractedDocument
from apps.platform.document_intelligence.services.relationship_detector import (
    RelationshipDetector,
)


class RelationshipDetectorTool(BaseTool):
    """Detects relationships between form fields (e.g., product_id → Productos)."""

    spec = ToolSpec(
        name="relationship_detector",
        description="Detecta relaciones entre campos de diferentes formularios",
        parameters={
            "fields": {"type": "list", "description": "Campos del formulario actual"},
        },
        expected_output="Lista de relaciones sugeridas con confianza",
        estimated_cost=0.001,
        estimated_time_ms=1500,
        category="analysis",
        requires_provider=True,
    )

    def execute(self, context: ExecutionContext) -> ToolResult:
        if not context.provider:
            return ToolResult(success=False, errors=["No provider"], confidence=0.0)

        from apps.platform.ai.types import DetectedField

        fields = [
            DetectedField(
                name=f.get("name", ""),
                suggested_type=f.get("type", "texto"),
            )
            for f in context.fields
        ]

        from apps.platform.document_intelligence.services.auto_form_creator import (
            FormCreationProposal,
        )
        proposal = FormCreationProposal(
            form_name=context.form_proposal.get("form_name", "") if context.form_proposal else "",
            fields=fields,
        )

        detector = RelationshipDetector(context.provider)
        result = detector.detect(
            extracted_doc=context.extracted_data.get("extracted_doc"),
            classification=None,
            form_proposal=proposal,
            use_cache=context.use_cache,
        )

        return ToolResult(
            success=True,
            data={
                "relationships": [
                    {
                        "field": getattr(r, "field_name", ""),
                        "related_form": getattr(r, "related_form_name", ""),
                        "confidence": getattr(r, "confidence", 0.0),
                    }
                    for r in (result.relationships if result else [])
                ]
            },
            confidence=0.7,
        )
