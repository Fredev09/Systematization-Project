from __future__ import annotations

import logging
from typing import Any

from apps.platform.ai.services.tools.base import BaseTool
from apps.platform.ai.services.tools.registry import ToolRegistry
from apps.platform.ai.services.tools.result import ToolContext, ToolResult

logger = logging.getLogger(__name__)


class GenerateStatisticsTool(BaseTool):
    name = "generate_statistics"
    description = "Generar estadisticas y resumenes del sistema"
    dry_run_supported = False
    requires_confirmation = False

    def can_execute(self, intent: Any) -> bool:
        from apps.platform.ai.services.decision_engine import ChatIntent
        if not isinstance(intent, ChatIntent):
            return False
        q = (getattr(intent, "explanation", "") or "").lower()
        stat_kw = [
            "estadistica", "estadisticas", "resumen", "kpi", "dashboard",
            "totales", "reporte", "report", "summary", "statistics", "stats",
        ]
        if any(k in q for k in stat_kw):
            return True
        if intent.sub_intent in ("statistics", "stats", "sum", "average", "trend"):
            return True
        return False

    def execute(self, ctx: ToolContext, params: dict[str, Any]) -> ToolResult:
        from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS

        parts = []

        try:
            prod_count = DS.contar("Productos")
            parts.append(f"  • **Productos**: {prod_count}")
        except Exception:
            parts.append("  • **Productos**: N/D")

        try:
            ventas_count = DS.contar("Ventas")
            parts.append(f"  • **Ventas**: {ventas_count}")
        except Exception:
            parts.append("  • **Ventas**: N/D")

        try:
            clientes_count = DS.contar("Clientes")
            parts.append(f"  • **Clientes**: {clientes_count}")
        except Exception:
            parts.append("  • **Clientes**: N/D")

        try:
            mov_count = DS.contar("MovimientosInventario")
            parts.append(f"  • **Movimientos de Inventario**: {mov_count}")
        except Exception:
            parts.append("  • **Movimientos de Inventario**: N/D")

        try:
            forms = __import__("apps.platform.dynamic_forms.models", fromlist=["Formulario"]).Formulario
            total_forms = forms.objects.filter(activo=True).count()
            parts.append(f"  • **Formularios activos**: {total_forms}")
        except Exception:
            parts.append("  • **Formularios activos**: N/D")

        text = "**Resumen del sistema:**\n" + "\n".join(parts)

        return ToolResult(
            summary=text,
            details={
                "productos": prod_count if 'prod_count' in dir() else None,
                "ventas": ventas_count if 'ventas_count' in dir() else None,
                "clientes": clientes_count if 'clientes_count' in dir() else None,
                "movimientos": mov_count if 'mov_count' in dir() else None,
            },
            followups=[
                "Muestrame los detalles de Productos",
                "Cual es el producto mas vendido",
                "Cuantas ventas se hicieron este mes",
            ],
        )


ToolRegistry.get_instance().register(GenerateStatisticsTool())
