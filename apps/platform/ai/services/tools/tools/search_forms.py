from __future__ import annotations

import time
import logging
from typing import Any

from apps.platform.ai.services.tools.base import BaseTool
from apps.platform.ai.services.tools.registry import ToolRegistry
from apps.platform.ai.services.tools.result import ToolContext, ToolResult

logger = logging.getLogger(__name__)


class SearchFormsTool(BaseTool):
    name = "search_forms"
    description = "Buscar y listar formularios del sistema"
    dry_run_supported = False
    requires_confirmation = False

    def can_execute(self, intent: Any) -> bool:
        from apps.platform.ai.services.decision_engine import ChatIntent
        if not isinstance(intent, ChatIntent):
            return False
        if intent.intent_type == "data_query" and intent.target_model in ("formulario", "formularios", "form"):
            return True
        if intent.intent_type == "data_query" and "formulario" in (intent.form_alias or "").lower():
            return True
        if intent.intent_type == "data_query" and intent.sub_intent in ("list", "search", "count"):
            if intent.form_alias and "form" in intent.form_alias.lower():
                return True
            if intent.target_model in ("formulario", "formularios", "form"):
                return True
        return False

    def execute(self, ctx: ToolContext, params: dict[str, Any]) -> ToolResult:
        from apps.platform.dynamic_forms.models import Formulario

        sub = params.get("sub_intent", "list")
        qs = Formulario.objects.filter(activo=True)

        if sub == "count":
            count = qs.count()
            forms_list = [f.nombre for f in qs]
            return ToolResult(
                summary=f"Hay {count} formulario(s) en el sistema.",
                details={"total": count, "forms": forms_list},
                followups=[
                    "Muestrame los campos de un formulario",
                    "Cuantos registros tiene cada formulario",
                    "Crea un nuevo formulario",
                ],
            )

        forms = list(qs.order_by("nombre"))
        lines = [f"**{len(forms)} formulario(s) disponible(s):**"]
        for f in forms:
            campo_count = f.campos.filter(activo=True).count()
            reg_count = f.registros.count()
            lines.append(f"  • **{f.nombre}** — {campo_count} campo(s), {reg_count} registro(s)")
        text = "\n".join(lines)

        return ToolResult(
            summary=text,
            details={
                "total": len(forms),
                "forms": [
                    {"id": f.id, "nombre": f.nombre, "campos": f.campos.filter(activo=True).count(), "registros": f.registros.count()}
                    for f in forms
                ],
            },
            followups=[
                "Muestrame los campos de un formulario",
                "Cuantos registros tiene Productos",
            ],
        )


ToolRegistry.get_instance().register(SearchFormsTool())
