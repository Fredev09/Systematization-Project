from __future__ import annotations

import logging
from typing import Any

from apps.platform.ai.services.tools.base import BaseTool
from apps.platform.ai.services.tools.registry import ToolRegistry
from apps.platform.ai.services.tools.result import ToolContext, ToolResult

logger = logging.getLogger(__name__)


class SalesQueriesTool(BaseTool):
    name = "sales_queries"
    description = "Consultar ventas, ingresos, tickets promedio y totales"
    dry_run_supported = False
    requires_confirmation = False

    def can_execute(self, intent: Any) -> bool:
        from apps.platform.ai.services.decision_engine import ChatIntent
        if not isinstance(intent, ChatIntent):
            return False
        q = (getattr(intent, "explanation", "") or "").lower()
        sales_kw = [
            "venta", "ventas", "ingreso", "ingresos", "factura",
            "ticket", "pedido", "orden", "sales", "revenue",
        ]
        if any(k in q for k in sales_kw):
            return True
        if intent.form_alias and "venta" in intent.form_alias.lower():
            return True
        return False

    def execute(self, ctx: ToolContext, params: dict[str, Any]) -> ToolResult:
        from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
        from apps.platform.dynamic_forms.models import Registro, ValorCampo, Campo
        from django.utils import timezone
        from datetime import timedelta

        sub = params.get("sub_intent", "list")

        try:
            formulario = DS.obtener_formulario("Ventas")
        except Exception:
            return ToolResult(
                success=False,
                summary="No se encontro el formulario Ventas.",
                error="Form not found",
                error_code="FORM_NOT_FOUND",
            )

        registros = Registro.objects.filter(formulario=formulario).order_by("-fecha_creacion")
        valores = DS.cargar_valores_mapa(registros, formulario)

        ventas = []
        total_ingresos = 0.0
        total_unidades = 0

        for reg in registros:
            vals = valores.get(reg.id, {})
            total_str = vals.get("total", vals.get("subtotal", "0"))
            cantidad_str = vals.get("cantidad", "1")
            cliente = vals.get("cliente", vals.get("nombre_cliente", ""))
            producto = vals.get("producto", vals.get("nombre_producto", ""))
            fecha = reg.fecha_creacion

            try:
                total_val = float(total_str)
            except (ValueError, TypeError):
                total_val = 0.0
            try:
                cantidad = int(float(cantidad_str))
            except (ValueError, TypeError):
                cantidad = 1

            total_ingresos += total_val
            total_unidades += cantidad

            ventas.append({
                "id": reg.id,
                "total": total_val,
                "cantidad": cantidad,
                "cliente": cliente,
                "producto": producto,
                "fecha": fecha,
            })

        hoy = timezone.now()
        mes_inicio = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ventas_mes = [v for v in ventas if v["fecha"] >= mes_inicio]
        ingresos_mes = sum(v["total"] for v in ventas_mes)

        ticket_promedio = total_ingresos / len(ventas) if ventas else 0
        ticket_mes = ingresos_mes / len(ventas_mes) if ventas_mes else 0

        if sub in ("count", "sum"):
            text = (
                f"**Resumen de Ventas:**\n"
                f"  • Total ventas: {len(ventas)}\n"
                f"  • Ingresos totales: ${total_ingresos:,.0f}\n"
                f"  • Unidades vendidas: {total_unidades}\n"
                f"  • Ticket promedio: ${ticket_promedio:,.0f}\n"
                f"  • Ventas este mes: {len(ventas_mes)} (${ingresos_mes:,.0f})"
            )
        elif sub == "average":
            text = (
                f"**Ticket promedio:**\n"
                f"  • General: ${ticket_promedio:,.0f}\n"
                f"  • Este mes: ${ticket_mes:,.0f}\n"
                f"  • Unidades por venta: {total_unidades / len(ventas):.1f}" if ventas else "Sin ventas."
            )
        elif sub == "trend":
            semana_inicio = hoy - timedelta(days=7)
            ventas_semana = [v for v in ventas if v["fecha"] >= semana_inicio]
            text = (
                f"**Tendencia de Ventas:**\n"
                f"  • Ultima semana: {len(ventas_semana)} ventas\n"
                f"  • Este mes: {len(ventas_mes)} ventas\n"
                f"  • Total historico: {len(ventas)} ventas\n"
                f"  • Ingresos este mes: ${ingresos_mes:,.0f}"
            )
        else:
            text = (
                f"**Ventas ({len(ventas)} total):**\n"
                f"  • Ingresos totales: ${total_ingresos:,.0f}\n"
                f"  • Ticket promedio: ${ticket_promedio:,.0f}\n"
                f"  • Este mes: {len(ventas_mes)} ventas (${ingresos_mes:,.0f})\n"
            )
            if ventas[:3]:
                text += "\n**Ultimas ventas:**\n"
                for v in ventas[:3]:
                    fecha_str = v["fecha"].strftime("%d/%m/%Y")
                    text += f"  • ${v['total']:,.0f} ({v['producto'] or 'N/D'}) — {fecha_str}\n"

        return ToolResult(
            summary=text,
            details={
                "total_ventas": len(ventas),
                "total_ingresos": round(total_ingresos, 2),
                "total_unidades": total_unidades,
                "ticket_promedio": round(ticket_promedio, 2),
                "ventas_mes": len(ventas_mes),
                "ingresos_mes": round(ingresos_mes, 2),
                "ventas": ventas,
            },
            followups=[
                "Cual es el producto mas vendido",
                "Ventas de este mes vs mes anterior",
                "Exportame las ventas a Excel",
            ],
        )


ToolRegistry.get_instance().register(SalesQueriesTool())
