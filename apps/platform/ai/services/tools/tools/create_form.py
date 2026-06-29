from __future__ import annotations

import logging
from typing import Any

from apps.platform.ai.services.tools.base import BaseTool
from apps.platform.ai.services.tools.registry import ToolRegistry
from apps.platform.ai.services.tools.result import ToolContext, ToolResult

logger = logging.getLogger(__name__)


class CreateFormTool(BaseTool):
    name = "create_form"
    description = "Crear un nuevo formulario en el sistema"
    dry_run_supported = True
    requires_confirmation = False

    def can_execute(self, intent: Any) -> bool:
        from apps.platform.ai.services.decision_engine import ChatIntent
        if not isinstance(intent, ChatIntent):
            return False
        if intent.intent_type == "form_creation":
            return True
        q = (getattr(intent, "explanation", "") or "").lower()
        create_kw = ["crear formulario", "nuevo formulario", "create form", "new form"]
        if any(k in q for k in create_kw):
            return True
        return False

    def execute(self, ctx: ToolContext, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            summary=(
                "Para crear un formulario nuevo, puedes:\n\n"
                "1. **Desde cero**: Ve a Formularios > Crear Formulario y define "
                "los campos manualmente.\n\n"
                "2. **Desde archivo**: Sube un Excel o PDF en Document Intelligence para "
                "que el sistema analice la estructura automaticamente.\n\n"
                "3. **Usar plantilla**: Si ya has creado formularios similares antes, "
                "el sistema puede sugerir una estructura.\n\n"
                "Dime que tipo de formulario necesitas y te guiare en el proceso."
            ),
            details={
                "options": [
                    "Crear desde cero",
                    "Crear desde archivo (Excel/PDF)",
                    "Usar plantilla existente",
                ]
            },
            followups=[
                "Quiero crear un formulario de Proveedores",
                "Ayudame a disenar los campos",
                "Sube un Excel para analizar",
            ],
        )


ToolRegistry.get_instance().register(CreateFormTool())
