"""
memory_tool.py — Accesses and updates the MemoryLearner knowledge base.
"""

from apps.platform.ai.tools.base import BaseTool, ExecutionContext, ToolResult, ToolSpec
from apps.platform.document_intelligence.services.memory_learner import MemoryLearner


class MemoryTool(BaseTool):
    """Applies learned corrections from past user decisions to current analysis."""

    spec = ToolSpec(
        name="memory",
        description="Aplica correcciones aprendidas de decisiones previas del usuario",
        parameters={
            "fields": {"type": "list", "description": "Campos propuestos para aplicar memoria"},
            "form_name": {"type": "string", "description": "Nombre del formulario"},
        },
        expected_output="Campos corregidos con lecciones aprendidas",
        estimated_cost=0.0,
        estimated_time_ms=50,
        category="learning",
        requires_provider=False,
    )

    def execute(self, context: ExecutionContext) -> ToolResult:
        learner = MemoryLearner()

        # Apply renames
        renamed_fields = []
        for f in context.fields:
            name = f.get("name", "")
            suggested = learner.suggest_rename(name)
            if suggested:
                renamed_fields.append({**f, "name": suggested, "was_renamed": True})
            else:
                renamed_fields.append(f)

        # Apply type corrections
        for f in renamed_fields:
            name = f.get("name", "")
            suggested = learner.suggest_type(name)
            if suggested:
                f["type"] = suggested
                f["type_corrected"] = True

        # Form name suggestion
        form_name = context.form_proposal.get("form_name", "") if context.form_proposal else ""
        if context.file_name:
            suggested_name = learner.suggest_form_name(context.file_name)
            if suggested_name:
                form_name = suggested_name

        return ToolResult(
            success=True,
            data={
                "fields": renamed_fields,
                "form_name": form_name,
                "memory_applied": True,
            },
            confidence=0.8,
        )
