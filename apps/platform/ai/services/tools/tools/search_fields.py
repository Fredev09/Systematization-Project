from __future__ import annotations

import logging
from typing import Any

from apps.platform.ai.services.tools.base import BaseTool
from apps.platform.ai.services.tools.registry import ToolRegistry
from apps.platform.ai.services.tools.result import ToolContext, ToolResult

logger = logging.getLogger(__name__)


class SearchFieldsTool(BaseTool):
    name = "search_fields"
    description = "Buscar y listar campos de un formulario"
    dry_run_supported = False
    requires_confirmation = False

    def can_execute(self, intent: Any) -> bool:
        from apps.platform.ai.services.decision_engine import ChatIntent
        if not isinstance(intent, ChatIntent):
            return False
        if intent.intent_type == "data_query" and intent.target_model in ("campo", "campos", "field", "fields"):
            return True
        if intent.sub_intent in ("list", "search", "count") and "campo" in (intent.form_alias or "").lower():
            return True
        return False

    def execute(self, ctx: ToolContext, params: dict[str, Any]) -> ToolResult:
        from apps.platform.dynamic_forms.models import Formulario, Campo
        from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS

        form_name = params.get("form_filter") or params.get("form_alias") or ""
        sub = params.get("sub_intent", "list")

        if not form_name:
            return ToolResult(
                success=False,
                summary="Necesito saber de que formulario quieres ver los campos. Por ejemplo: 'campos de Productos'.",
                error="No form specified",
                error_code="MISSING_PARAM",
                followups=[
                    "Muestrame los campos de Productos",
                    "Muestrame los campos de Ventas",
                ],
            )

        try:
            formulario = DS.obtener_formulario(form_name)
        except Exception:
            return ToolResult(
                success=False,
                summary=f"No se encontro el formulario '{form_name}'.",
                error=f"Form '{form_name}' not found",
                error_code="FORM_NOT_FOUND",
                followups=["Muestrame los formularios disponibles", "Crea un nuevo formulario"],
            )

        campos = Campo.objects.filter(formulario=formulario, activo=True).order_by("orden", "nombre")

        if sub == "count":
            return ToolResult(
                summary=f"El formulario **{form_name}** tiene {campos.count()} campo(s).",
                details={"form": form_name, "total": campos.count()},
                followups=["Muestrame los campos", "Cuantos registros tiene"],
            )

        lines = [f"**Campos de {form_name} ({campos.count()}):**"]
        for c in campos:
            req = " *" if c.obligatorio else ""
            unico = " (unico)" if c.unico else ""
            ident = " (ID)" if c.identificador_principal else ""
            lines.append(f"  • **{c.nombre}**{req} — {c.tipo}{unico}{ident}")
        text = "\n".join(lines)

        return ToolResult(
            summary=text,
            details={
                "form": form_name,
                "total": campos.count(),
                "fields": [
                    {"nombre": c.nombre, "tipo": c.tipo, "obligatorio": c.obligatorio, "unico": c.unico, "identificador_principal": c.identificador_principal}
                    for c in campos
                ],
            },
            followups=[f"Cuantos registros tiene {form_name}", "Exportame los datos", "Busca en los registros"],
        )


ToolRegistry.get_instance().register(SearchFieldsTool())
