# BACKEND ES LA APP PRINCIPAL (DASHBOARD)

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from decimal import Decimal

from django.shortcuts import redirect, render
from apps.shared.configuracion.models import ConfiguracionTienda
from apps.platform.dynamic_forms.models import Registro, ValorCampo
from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
from apps.legacy.productos.wrappers import DynamicProductWrapper, DynamicVentaWrapper
from .permissions import es_administrador, rol_usuario

logger = logging.getLogger(__name__)


@login_required(login_url='login')
def dashboard(request):
    """
    Dashboard usando DynamicService.
    
    Proporciona las mismas estadísticas:
    - Total ventas, productos, clientes
    - Stock bajo
    - Top productos vendidos
    - Ventas recientes
    """
    query = request.GET.get('q', '').strip()
    es_admin = es_administrador(request.user)
    configuracion = ConfiguracionTienda.obtener()
    stock_minimo = configuracion.stock_minimo_alerta

    try:
        # --- Estadísticas de productos ---
        total_productos = DS.contar('Productos')

        # Calcular stock bajo
        registros_productos = Registro.objects.filter(
            formulario=DS.obtener_formulario('Productos')
        )
        valores_prod = DS.cargar_valores_mapa(registros_productos)

        stock_bajo = 0
        productos_vendidos = []  # [(wrapper, total_vendidos)]

        for r in registros_productos:
            vals = valores_prod.get(r.id, {})
            try:
                stock = int(vals.get('stock', '0'))
            except (ValueError, TypeError):
                stock = 0

            if 1 <= stock <= stock_minimo:
                stock_bajo += 1

            pw = DynamicProductWrapper(r, vals)
            productos_vendidos.append(pw)

        # Calcular total_vendidos para cada producto
        try:
            form_ventas = DS.obtener_formulario('Ventas')
            campo_producto = form_ventas.campos.filter(
                nombre='producto', activo=True
            ).first()
            if campo_producto:
                from django.db.models import Count

                # Contar ventas por producto
                ventas_por_producto = {}
                for vc in ValorCampo.objects.filter(
                    campo=campo_producto,
                    registro__formulario=form_ventas
                ).values('valor').annotate(total=Count('id')):
                    prod_id = vc['valor']
                    if prod_id and prod_id.isdigit():
                        try:
                            # Obtener cantidad de cada venta para sumar unidades
                            campo_cantidad = form_ventas.campos.filter(
                                nombre='cantidad', activo=True
                            ).first()
                            if campo_cantidad:
                                from django.db.models import Sum
                                cant_sum = ValorCampo.objects.filter(
                                    campo=campo_cantidad,
                                    registro__formulario=form_ventas,
                                    registro__valores__campo=campo_producto,
                                    registro__valores__valor=prod_id
                                ).aggregate(total=Sum('valor'))
                                ventas_por_producto[int(prod_id)] = int(cant_sum['total'] or 0)
                        except Exception:
                            ventas_por_producto[int(prod_id)] = int(vc['total'])

                for pw in productos_vendidos:
                    pw.total_vendidos = ventas_por_producto.get(pw.id, 0)

            # Ordenar por total_vendidos descendente, tomar top 3
            productos_vendidos.sort(key=lambda p: p.total_vendidos, reverse=True)
            productos = productos_vendidos[:3]
        except Exception:
            productos = productos_vendidos[:3]

        # --- Estadísticas de ventas ---
        if es_admin:
            ventas_base = Registro.objects.filter(
                formulario=DS.obtener_formulario('Ventas')
            )
        else:
            ventas_base = Registro.objects.filter(
                formulario=DS.obtener_formulario('Ventas'),
                usuario=request.user
            )

        valores_ventas = DS.cargar_valores_mapa(ventas_base)
        total_ventas = Decimal('0')
        for r in ventas_base:
            vals = valores_ventas.get(r.id, {})
            try:
                total_ventas += Decimal(str(vals.get('total', '0')).replace(',', '.'))
            except Exception:
                pass

        total_ventas = total_ventas or Decimal('0')

        # Ventas recientes
        ventas_recientes_registros = ventas_base.order_by('-fecha_creacion')[:5]
        valores_recientes = DS.cargar_valores_mapa(ventas_recientes_registros)
        ventas_recientes = [
            DynamicVentaWrapper(r, valores_recientes.get(r.id, {}))
            for r in ventas_recientes_registros
        ]

        # --- Total clientes ---
        total_clientes = DS.contar('Clientes') if es_admin else None

    except Exception as e:
        logger.exception(f'Error en dashboard: {e}')
        productos = []
        ventas_recientes = []
        total_productos = 0
        stock_bajo = 0
        total_ventas = Decimal('0')
        total_clientes = None

    return render(request, 'dashboard/dashboard.html', {
        'query': query,
        'productos': productos,
        'ventas_recientes': ventas_recientes,
        'total_productos': total_productos,
        'stock_bajo': stock_bajo,
        'stock_minimo_alerta': stock_minimo,
        'total_ventas': total_ventas,
        'total_clientes': total_clientes,
        'es_admin': es_admin,
        'rol_usuario': rol_usuario(request.user),
    })


def inicio(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return redirect('login')


def formulario(request):
    return render(request, 'formularios/formulario.html')


def index(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return redirect('login')
