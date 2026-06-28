"""
document_classifier_tool.py — Classifies document type from content.
"""

from apps.platform.ai.tools.base import BaseTool, ExecutionContext, ToolResult, ToolSpec
from apps.platform.document_intelligence.services.structure_detector import StructureDetector
from apps.platform.document_intelligence.extractors.base import ExtractedDocument


class DocumentClassifierTool(BaseTool):
    """Detects document type (invoice, inventory, client list, etc.)."""

    spec = ToolSpec(
        name="document_classifier",
        description="Clasifica el tipo de documento basado en columnas y contenido",
        parameters={
            "columns": {"type": "list", "description": "Nombres de columnas"},
            "sample_text": {"type": "string", "description": "Texto de muestra"},
        },
        expected_output="Tipo de documento con confianza y explicación",
        estimated_cost=0.0,
        estimated_time_ms=50,
        category="classification",
        requires_provider=False,
    )

    def execute(self, context: ExecutionContext) -> ToolResult:
        extracted = context.extracted_data.get("extracted_doc")
        if not extracted and context.raw_text:
            extracted = ExtractedDocument(
                raw_text=context.raw_text,
                columns=[f.get("name", "") for f in context.fields],
            )

        detector = StructureDetector()
        classification = detector.classify(extracted) if extracted else None

        if not classification or classification.document_type == "unknown":
            return ToolResult(
                success=True,
                data={"document_type": "unknown", "confidence": 0.0},
                confidence=0.0,
                warnings=["Could not classify document type"],
            )

        return ToolResult(
            success=True,
            data={
                "document_type": classification.document_type,
                "confidence": classification.confidence,
                "method": classification.method,
                "explanation": classification.explanation,
            },
            confidence=classification.confidence,
        )
