from __future__ import annotations

import logging
from typing import Any

from apps.platform.ai.services.tools.base import BaseTool
from apps.platform.ai.services.tools.registry import ToolRegistry
from apps.platform.ai.services.tools.result import ToolContext, ToolResult

logger = logging.getLogger(__name__)


class ImportRecordsTool(BaseTool):
    name = "import_records"
    description = "Importar registros desde un archivo Excel al sistema"
    dry_run_supported = True
    requires_confirmation = True

    def can_execute(self, intent: Any) -> bool:
        from apps.platform.ai.services.decision_engine import ChatIntent
        if not isinstance(intent, ChatIntent):
            return False
        q = (getattr(intent, "explanation", "") or "").lower()
        import_kw = ["import", "importar", "cargar", "subir", "excel", "xlsx"]
        if any(k in q for k in import_kw):
            return True
        if intent.sub_intent in ("import", "importar", "upload"):
            return True
        return False

    def execute(self, ctx: ToolContext, params: dict[str, Any]) -> ToolResult:
        from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
        from apps.platform.dynamic_forms.import_service import (
            _validar_archivo_importacion,
            leer_excel,
            detectar_columnas,
            construir_mapeo_completo,
            previsualizar,
            importar,
        )

        form_name = params.get("form_filter") or params.get("form_alias") or ""
        file_path = params.get("file_path", "")
        modo = params.get("modo", "crear")

        if not form_name:
            return ToolResult(
                success=False,
                summary="Necesito saber en que formulario quieres importar y el archivo.",
                error="Missing form name",
                error_code="MISSING_PARAM",
                followups=[
                    "Importa este Excel en Productos",
                    "Cargame estos datos en Ventas",
                ],
            )

        if not file_path:
            return ToolResult(
                summary="Para importar, primero debes subir un archivo Excel (.xlsx).\n\n"
                        "Paso 1: Ve a la seccion **Importar** del formulario **{}**.\n"
                        "Paso 2: Sube tu archivo Excel.\n"
                        "Paso 3: Confirma la importacion.\n\n"
                        "O dime exactamente que archivo quieres importar.".format(form_name),
                details={"form": form_name, "required": "Excel file"},
                followups=[
                    f"Llevame al importador de {form_name}",
                    "Que formularios estan disponibles para importar?",
                ],
            )

        try:
            _validar_archivo_importacion(file_path)
        except Exception as e:
            return ToolResult(
                success=False,
                summary=f"El archivo no es valido: {e}",
                error=str(e),
                error_code="INVALID_FILE",
            )

        try:
            formulario = DS.obtener_formulario(form_name)
            encabezados, filas = leer_excel(file_path)
            mapeo, _ = construir_mapeo_completo(encabezados, formulario)
            preview = previsualizar(formulario, encabezados, filas, mapeo)
        except Exception as e:
            logger.exception("Import dry-run failed")
            return ToolResult(
                success=False,
                summary=f"No se pudo analizar el archivo: {e}",
                error=str(e),
                error_code="PARSE_ERROR",
            )

        validos = [r for r in preview if r.get("valida")]
        invalidos = [r for r in preview if not r.get("valida")]

        return ToolResult(
            requires_confirmation=True,
            summary=(
                f"**Previsualizacion de importacion en {form_name}:**\n"
                f"  • Total filas: {len(preview)}\n"
                f"  • Validas: {len(validos)}\n"
                f"  • Con errores: {len(invalidos)}\n"
                f"  • Modo: {modo}\n\n"
                "¿Confirmas la importacion?"
            ),
            details={
                "form": form_name,
                "total": len(preview),
                "validas": len(validos),
                "errores": len(invalidos),
                "modo": modo,
                "columnas_mapeadas": list(mapeo.keys()),
                "errores_detalle": [
                    {"fila": r.get("fila_idx", "?"), "campos": r.get("errores", [])}
                    for r in preview if not r.get("valida")
                ],
            },
            followups=[
                "Si, confirma la importacion",
                "No, cancela la importacion",
                "Muestrame los errores en detalle",
            ],
        )


ToolRegistry.get_instance().register(ImportRecordsTool())
