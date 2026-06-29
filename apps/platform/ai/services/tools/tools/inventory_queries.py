from __future__ import annotations

import logging
from typing import Any

from apps.platform.ai.services.tools.base import BaseTool
from apps.platform.ai.services.tools.registry import ToolRegistry
from apps.platform.ai.services.tools.result import ToolContext, ToolResult

logger = logging.getLogger(__name__)


class InventoryQueriesTool(BaseTool):
    name = "inventory_queries"
    description = "Consultar inventario, stock bajo, movimientos y valor total"
    dry_run_supported = False
    requires_confirmation = False

    def can_execute(self, intent: Any) -> bool:
        from apps.platform.ai.services.decision_engine import ChatIntent
        if not isinstance(intent, ChatIntent):
            return False
        q = (getattr(intent, "explanation", "") or "").lower()
        inv_kw = [
            "inventario", "stock", "movimiento", "inventary", "inventory",
            "existencia", "bodega", "almacen",
        ]
        if any(k in q for k in inv_kw):
            return True
        if intent.form_alias and "inventario" in intent.form_alias.lower():
            return True
        return False

    def execute(self, ctx: ToolContext, params: dict[str, Any]) -> ToolResult:
        from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
        from apps.platform.dynamic_forms.models import Registro, ValorCampo, Campo

        sub = params.get("sub_intent", "list")

        try:
            formulario_prod = DS.obtener_formulario("Productos")
        except Exception:
            return ToolResult(
                success=False,
                summary="No se encontro el formulario Productos.",
                error="Form not found",
                error_code="FORM_NOT_FOUND",
            )

        registros = Registro.objects.filter(formulario=formulario_prod)
        valores = DS.cargar_valores_mapa(registros, formulario_prod)

        productos = []
        for reg in registros:
            vals = valores.get(reg.id, {})
            nombre = vals.get("nombre", f"Producto #{reg.id}")
            stock_str = vals.get("stock", "0")
            precio_str = vals.get("precio", "0")
            categoria = vals.get("categoria", "")
            try:
                stock = int(float(stock_str))
            except (ValueError, TypeError):
                stock = 0
            try:
                precio = float(precio_str)
            except (ValueError, TypeError):
                precio = 0
            productos.append({
                "nombre": nombre,
                "stock": stock,
                "precio": precio,
                "categoria": categoria,
                "valor_total": stock * precio,
            })

        total_productos = len(productos)
        total_stock = sum(p["stock"] for p in productos)
        valor_inventario = sum(p["valor_total"] for p in productos)
        stock_bajo = [p for p in productos if p["stock"] < 10]
        sin_stock = [p for p in productos if p["stock"] == 0]

        if sub == "count":
            text = (
                f"**Resumen de Inventario:**\n"
                f"  • Productos: {total_productos}\n"
                f"  • Total unidades: {total_stock}\n"
                f"  • Valor inventario: ${valor_inventario:,.0f}\n"
                f"  • Stock bajo (<10): {len(stock_bajo)}\n"
                f"  • Sin stock: {len(sin_stock)}"
            )
        elif sub in ("top", "bottom"):
            ordenado = sorted(productos, key=lambda p: p["stock"])
            if sub == "top":
                ordenado = list(reversed(ordenado))
            top = ordenado[:5]
            text = "**Productos con {} stock:**\n".format("mas" if sub == "top" else "menos")
            for p in top:
                text += f"  • {p['nombre']}: {p['stock']} unidades (${p['precio']:,.0f} c/u)\n"
        elif sub == "search":
            query = params.get("filter", {}).get("search", "")
            if query:
                filtrados = [p for p in productos if query.lower() in p["nombre"].lower()]
                text = f"**Resultados para '{query}':**\n" + "\n".join(
                    f"  • {p['nombre']}: {p['stock']} und, ${p['precio']:,.0f}" for p in filtrados
                ) if filtrados else f"No se encontraron productos para '{query}'."
            else:
                text = "Necesito un termino de busqueda."
        else:
            bajo_text = ""
            if stock_bajo:
                bajo_text = "\n**⚠ Stock bajo (<10):**\n" + "\n".join(
                    f"  • {p['nombre']}: {p['stock']} und" for p in stock_bajo[:5]
                )

            text = (
                f"**Inventario completo:**\n"
                f"  • {total_productos} productos\n"
                f"  • {total_stock} unidades en total\n"
                f"  • Valor total: ${valor_inventario:,.0f}\n"
                f"  • Sin stock: {len(sin_stock)} producto(s)"
                f"{bajo_text}"
            )

        return ToolResult(
            summary=text,
            details={
                "total_productos": total_productos,
                "total_stock": total_stock,
                "valor_inventario": round(valor_inventario, 2),
                "stock_bajo": len(stock_bajo),
                "sin_stock": len(sin_stock),
                "productos": productos,
            },
            followups=[
                "Que productos tienen stock bajo",
                "Movimientos de inventario recientes",
                "Cual es el valor total del inventario",
            ],
        )


ToolRegistry.get_instance().register(InventoryQueriesTool())
