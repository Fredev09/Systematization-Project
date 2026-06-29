from __future__ import annotations

import logging
from typing import Any

from apps.platform.ai.services.tools.base import BaseTool
from apps.platform.ai.services.tools.registry import ToolRegistry
from apps.platform.ai.services.tools.result import ToolContext, ToolResult

logger = logging.getLogger(__name__)


class ExportRecordsTool(BaseTool):
    name = "export_records"
    description = "Exportar registros de un formulario a Excel"
    dry_run_supported = True
    requires_confirmation = False

    def can_execute(self, intent: Any) -> bool:
        from apps.platform.ai.services.decision_engine import ChatIntent
        if not isinstance(intent, ChatIntent):
            return False
        q = (getattr(intent, "explanation", "") or "").lower()
        export_kw = ["export", "exportar", "descargar", "excel", "xlsx"]
        if any(k in q for k in export_kw) and intent.sub_intent != "import":
            return True
        if intent.sub_intent in ("export", "exportar", "download"):
            return True
        return False

    def execute(self, ctx: ToolContext, params: dict[str, Any]) -> ToolResult:
        from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
        from apps.platform.dynamic_forms.services import exportar_registros_excel
        from apps.platform.dynamic_forms.models import Registro, Campo

        form_name = params.get("form_filter") or params.get("form_alias") or ""

        if not form_name:
            return ToolResult(
                success=False,
                summary="Necesito saber que formulario quieres exportar.",
                error="Missing form name",
                error_code="MISSING_PARAM",
                followups=[
                    "Exportame Productos a Excel",
                    "Descarga los datos de Ventas",
                ],
            )

        try:
            formulario = DS.obtener_formulario(form_name)
        except Exception:
            return ToolResult(
                success=False,
                summary=f"No se encontro el formulario '{form_name}'.",
                error=f"Form {form_name} not found",
                error_code="FORM_NOT_FOUND",
            )

        registros = Registro.objects.filter(formulario=formulario)
        campos = Campo.objects.filter(formulario=formulario, activo=True).order_by("orden", "nombre")

        total = registros.count()
        if total == 0:
            return ToolResult(
                summary=f"El formulario **{form_name}** no tiene registros para exportar.",
                details={"form": form_name, "total": 0},
                followups=["Importa datos en este formulario", "Crea un nuevo registro"],
            )

        try:
            response = exportar_registros_excel(registros, campos, form_name)
        except Exception as e:
            logger.exception("Export failed")
            return ToolResult(
                success=False,
                summary=f"No se pudo generar el Excel: {e}",
                error=str(e),
                error_code="EXPORT_ERROR",
            )

        return ToolResult(
            summary=(
                f"**Exportacion lista:**\n"
                f"  • Formulario: {form_name}\n"
                f"  • Registros: {total}\n"
                f"  • Archivo: registros_{form_name}.xlsx\n\n"
                "El archivo se ha generado. Usa el enlace de descarga para obtenerlo."
            ),
            details={
                "form": form_name,
                "total": total,
                "filename": f"registros_{form_name}.xlsx",
                "download_url": response.get("Content-Disposition", ""),
            },
            followups=[
                f"Exporta otro formulario",
                "Muestrame los datos en pantalla",
                "Cuantos registros hay en total",
            ],
        )


ToolRegistry.get_instance().register(ExportRecordsTool())
