"""
import_tool.py — Imports data into Dynamic Forms from analyzed documents.
"""

from apps.platform.ai.tools.base import BaseTool, ExecutionContext, ToolResult, ToolSpec


class ImportTool(BaseTool):
    """Imports data rows into an existing form after creation."""

    spec = ToolSpec(
        name="import",
        description="Importa datos de un documento analizado a un formulario de Dynamic Forms",
        parameters={
            "formulario_id": {"type": "int", "description": "ID del formulario destino"},
            "file_path": {"type": "string", "description": "Ruta al archivo de datos"},
        },
        expected_output="Resultado de importación (creados, actualizados, errores)",
        estimated_cost=0.0,
        estimated_time_ms=2000,
        category="data",
        requires_provider=False,
        requires_db=True,
    )

    def execute(self, context: ExecutionContext) -> ToolResult:
        form_id = context.form_id
        file_path = context.file_path

        if not form_id:
            return ToolResult(success=False, errors=["No form ID provided"], confidence=0.0)
        if not file_path:
            return ToolResult(success=False, errors=["No file path for import"], confidence=0.0)

        try:
            from apps.platform.dynamic_forms.models import Formulario
            from apps.platform.dynamic_forms.import_service import (
                analyze_workbook,
                importar,
                previsualizar,
            )

            formulario = Formulario.objects.get(id=form_id)
            analysis = analyze_workbook(file_path, formulario)
            mapeo_idx = {}
            for r in analysis.get("match_results", []):
                if hasattr(r, "matched_to") and r.matched_to:
                    mapeo_idx[r.column_index] = r.matched_to

            preview = previsualizar(
                formulario,
                analysis["encabezados"],
                analysis["filas"],
                mapeo_idx,
            )
            valid_rows = [r for r in preview if r.get("valida")]

            if not valid_rows:
                return ToolResult(
                    success=True,
                    data={"creados": 0, "actualizados": 0, "errores": [], "total_validas": 0},
                    warnings=["No valid rows to import"],
                    confidence=0.5,
                )

            result = importar(
                formulario,
                valid_rows,
                usuario=context.user_id,
                modo="crear",
                mapeo=mapeo_idx,
            )

            return ToolResult(
                success=True,
                data={
                    "creados": result.get("creados", 0),
                    "actualizados": result.get("actualizados", 0),
                    "errores": result.get("errores", [])[:10],
                    "total_validas": len(valid_rows),
                },
                confidence=0.9 if result.get("creados", 0) > 0 else 0.5,
            )

        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Import failed")
            return ToolResult(
                success=False,
                errors=[f"Import error: {e}"],
                confidence=0.0,
            )
