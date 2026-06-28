"""
form_generator_tool.py — Generates form proposals from detected fields.
"""

from apps.platform.ai.services.form_generator import FormGenerator
from apps.platform.ai.tools.base import BaseTool, ExecutionContext, ToolResult, ToolSpec


class FormGeneratorTool(BaseTool):
    """Generates a complete form proposal from detected fields."""

    spec = ToolSpec(
        name="form_generator",
        description="Genera una propuesta completa de formulario con nombre, descripción y campos",
        parameters={
            "fields": {"type": "list", "description": "Campos detectados"},
            "source_name": {"type": "string", "description": "Nombre del documento origen"},
        },
        expected_output="FormProposal con nombre, descripción y campos",
        estimated_cost=0.001,
        estimated_time_ms=1500,
        category="generation",
        requires_provider=True,
    )

    def execute(self, context: ExecutionContext) -> ToolResult:
        if not context.provider:
            return ToolResult(success=False, errors=["No provider available"], confidence=0.0)

        from apps.platform.ai.types import DetectedField

        fields = [
            DetectedField(
                name=f.get("name", ""),
                suggested_type=f.get("type", "texto"),
                required=f.get("required", False),
                unique=f.get("unique", False),
                is_identifier=f.get("is_identifier", False),
                confidence=f.get("confidence", 0.5),
            )
            for f in context.fields
        ]

        source_name = context.file_name or "documento"
        generator = FormGenerator(context.provider)
        proposal = generator.generate(
            fields=fields,
            source_name=source_name,
            use_cache=context.use_cache,
        )

        return ToolResult(
            success=True,
            data={
                "form_name": proposal.form_name,
                "form_description": proposal.form_description,
                "fields": [
                    {
                        "name": f.name,
                        "type": f.suggested_type,
                        "required": f.required,
                        "unique": f.unique,
                        "is_identifier": f.is_identifier,
                        "confidence": f.confidence,
                    }
                    for f in proposal.fields
                ],
                "confidence": proposal.confidence,
            },
            confidence=proposal.confidence,
        )
