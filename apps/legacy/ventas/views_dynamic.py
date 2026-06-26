"""
Vistas paralelas para Ventas usando DynamicService.

Mantiene exactamente la misma experiencia de usuario:
- Misma URL, mismos parametros POST/GET
- Mismos templates (nueva_venta.html, historial_ventas.html)
- Mismas validaciones y mensajes de error
- Mismas estadisticas en la sidebar

Pero toda la persistencia va a Dynamic Forms.
"""

import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import redirect, render, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date

from config.pagination import OPCIONES_POR_PAGINA, obtener_por_pagina, parametros_sin_pagina
from config.permissions import GRUPO_ADMINISTRADOR, admin_required, es_administrador, rol_usuario
from apps.platform.dynamic_forms.models import Campo, Formulario, Registro
from apps.platform.dynamic_forms.services_dynamic import (
    DynamicService as DS,
    ValidacionError,
)
from apps.legacy.productos.wrappers import (
    DynamicClienteWrapper,
    DynamicProductWrapper,
    DynamicVentaWrapper,
)

logger = logging.getLogger(__name__)


# ======================================================================
# CONSTANTES
# ======================================================================

FORM_PRODUCTOS = 'Productos'
FORM_CLIENTES = 'Clientes'
FORM_VENTAS = 'Ventas'


# ======================================================================
# HELPERS
# ======================================================================


def _entero(valor, default=0):
    try:
        return int(float(str(valor).replace(',', '.')))
    except (ValueError, TypeError):
        return default


def _decimal(valor, default=Decimal('0')):
    try:
        return Decimal(str(valor).replace(',', '.'))
    except (ValueError, TypeError):
        return default


def _obtener_opciones_productos():
    """Obtiene productos activos como [(id, display_text)] para el select."""
    try:
        form = DS.obtener_formulario(FORM_PRODUCTOS)
        registros = Registro.objects.filter(formulario=form).order_by('-fecha_creacion')
        valores = DS.cargar_valores_mapa(registros)
        opciones = []
        for r in registros:
            vals = valores.get(r.id, {})
            nombre = vals.get('nombre', '')
            stock = vals.get('stock', '0')
            precio = vals.get('precio', '0')
            display = f'{nombre} (Stock: {stock}) - ${_decimal(precio):,.0f}'
            opciones.append((r.id, display))
        return opciones
    except Exception:
        return []


def _obtener_opciones_clientes():
    """Obtiene clientes activos como [(id, display_text)] para el select."""
    try:
        form = DS.obtener_formulario(FORM_CLIENTES)
        registros = Registro.objects.filter(formulario=form).order_by('id')
        valores = DS.cargar_valores_mapa(registros)
        opciones = []
        for r in registros:
            vals = valores.get(r.id, {})
            nombre = vals.get('nombre', '')
            documento = vals.get('documento', '')
            display = f'{nombre} - {documento}' if documento else nombre
            opciones.append((r.id, display))
        return opciones
    except Exception:
        return []


def _vendedores_registrados():
    """Retorna vendedores (usuarios no-admin activos)."""
    return User.objects.filter(
        is_active=True
    ).exclude(
        is_superuser=True
    ).exclude(
        groups__name=GRUPO_ADMINISTRADOR
    ).distinct().order_by('first_name', 'last_name', 'username')


def _stats_ventas(usuario, es_admin):
    """Calcula estadisticas de ventas: total, hoy, mes."""
    try:
        form = DS.obtener_formulario(FORM_VENTAS)
        registros = Registro.objects.filter(formulario=form)
        valores = DS.cargar_valores_mapa(registros)

        total = Decimal('0')
        total_hoy = Decimal('0')
        total_mes = Decimal('0')
        unidades = 0

        now = timezone.now()
        inicio_hoy = now.replace(hour=0, minute=0, second=0, microsecond=0)
        inicio_mes = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        for r in registros:
            vals = valores.get(r.id, {})
            total_val = _decimal(vals.get('total', '0'))
            cantidad = _entero(vals.get('cantidad', '0'))

            total += total_val
            unidades += cantidad

            if r.fecha_creacion >= inicio_hoy:
                total_hoy += total_val
            if r.fecha_creacion >= inicio_mes:
                total_mes += total_val

        return total, total_hoy, total_mes, unidades
    except Exception:
        return Decimal('0'), Decimal('0'), Decimal('0'), 0


def _ventas_recientes(limite=5):
    """Retorna las ultimas N ventas."""
    try:
        form = DS.obtener_formulario(FORM_VENTAS)
        registros = Registro.objects.filter(formulario=form).order_by('-fecha_creacion')[:limite]
        valores = DS.cargar_valores_mapa(registros)

        ventas = []
        for r in registros:
            vals = valores.get(r.id, {})
            ventas.append(DynamicVentaWrapper(r, vals))
        return ventas
    except Exception:
        return []


# ======================================================================
# VISTA: NUEVA VENTA (SOLO DYNAMIC SERVICE)
# ======================================================================


@login_required(login_url='login')
def nueva_venta(request):
    """
    Nueva venta usando DynamicService.

    Flujo:
        1. Renderizar formulario con productos y clientes desde dynamic_forms.
        2. Al POST, crear registro en formulario "Ventas".
        3. El hook post_crear_venta se encarga de descontar stock
           y crear movimiento de inventario.
    """
    es_admin = es_administrador(request.user)

    # Cargar opciones para los selects del template
    productos_opciones = _obtener_opciones_productos()
    productos_disponibles = [p for p in productos_opciones if p[0]]  # Solo IDs validos
    vendedores = _vendedores_registrados()
    clientes_opciones = _obtener_opciones_clientes()

    error = None
    success = False

    if request.method == 'POST':
        vendedor_id = request.POST.get('vendedor', '').strip()

        # Recolectar productos y cantidades del POST
        producto_ids = request.POST.getlist('producto')
        cantidades_raw = request.POST.getlist('cantidad')

        # Validar vendedor
        vendedor = request.user
        if es_admin:
            if not vendedor_id:
                error = 'Debes seleccionar el vendedor que realizo la venta.'
            else:
                vendedor = _vendedores_registrados().filter(id=vendedor_id).first()
                if vendedor is None:
                    error = 'El vendedor seleccionado no es valido.'

        if not error:
            # Agrupar productos (mismo producto en varias filas = sumar cantidades)
            productos_agrupados = {}
            for idx, prod_id in enumerate(producto_ids):
                prod_id = prod_id.strip()
                cant_raw = cantidades_raw[idx] if idx < len(cantidades_raw) else ''

                if not prod_id and not cant_raw:
                    continue
                if not prod_id:
                    error = 'Debes seleccionar un producto en todas las filas.'
                    break
                try:
                    pid = int(prod_id)
                    cant = int(cant_raw)
                except (ValueError, TypeError):
                    error = 'Todas las cantidades deben ser numeros validos.'
                    break
                if cant <= 0:
                    error = 'Todas las cantidades deben ser mayores a 0.'
                    break
                productos_agrupados[pid] = productos_agrupados.get(pid, 0) + cant

            if not error and not productos_agrupados:
                error = 'Debes agregar al menos un producto a la venta.'

        if not error:
            try:
                with transaction.atomic():
                    for producto_id, cantidad in productos_agrupados.items():
                        # Obtener precio del producto desde dynamic_forms
                        try:
                            form_prod = DS.obtener_formulario(FORM_PRODUCTOS)
                            reg_prod = Registro.objects.get(id=producto_id, formulario=form_prod)
                            prod_valores = DS.obtener_valores(reg_prod)
                            precio_raw = prod_valores.get('precio', '0')
                            precio = str(_decimal(precio_raw))
                        except (Registro.DoesNotExist, Exception) as e:
                            raise ValueError(f'Producto #{producto_id} no encontrado.')

                        # Crear la venta usando DynamicService
                        # El hook post_crear_venta hara el resto
                        DS.crear(FORM_VENTAS, {
                            'producto': str(producto_id),
                            'cantidad': str(cantidad),
                            'precio_unitario': precio,
                        }, usuario=request.user)

                messages.success(request, 'Venta registrada correctamente.')
                return redirect('nueva_venta')

            except (ValidacionError, ValueError) as e:
                error = str(e)
            except Exception as e:
                logger.exception(f'Error en nueva_venta (dinamico): {e}')
                error = 'No se pudo registrar la venta. Revisa los datos e intenta de nuevo.'

    # Estadisticas para la sidebar
    total_ventas, total_hoy, total_mes, unidades_vendidas = _stats_ventas(
        request.user, es_admin
    )
    ventas_recientes = _ventas_recientes()

    return render(request, 'ventas/nueva_venta.html', {
        'productos': productos_opciones,
        'productos_disponibles': productos_disponibles,
        'vendedores_registrados': vendedores,
        'clientes_registrados': clientes_opciones,
        'ventas_recientes': ventas_recientes,
        'error': error,
        'es_admin': es_admin,
        'rol_usuario': rol_usuario(request.user),
        'total_ventas': total_ventas,
        'total_hoy': total_hoy,
        'total_mes': total_mes,
        'unidades_vendidas': unidades_vendidas,
        # Valores por defecto para los campos del formulario
        'vendedor_id_seleccionado': '',
        'cliente_modo_seleccionado': 'rapida',
        'cliente_id_seleccionado': '',
        'documento_cliente': '',
        'nombre_cliente': '',
        'apellido_cliente': '',
        'correo_cliente': '',
        'telefono_cliente': '',
    })


# ======================================================================
# HELPERS PARA HISTORIAL Y DETALLE
# ======================================================================


def _aplicar_filtros_ventas_dinamico(request, registros, valores_map, es_admin):
    """
    Aplica los mismos filtros que la vista legacy historial_ventas,
    pero sobre registros dinámicos.
    """
    query = request.GET.get('q', '').strip()
    fecha_raw = request.GET.get('fecha', '').strip()
    vendedor_id = request.GET.get('vendedor', '').strip()

    if query:
        query_lower = query.lower()
        # Búsqueda en valores de campos de la venta y relaciones
        ids_filtrados = set()
        for r in registros:
            vals = valores_map.get(r.id, {})
            texto = ' '.join(v.lower() for v in vals.values() if v)
            if query_lower in texto:
                ids_filtrados.add(r.id)

        # También buscar en registros relacionados (producto, cliente)
        # que ya están precargados en valores_map
        registros = [r for r in registros if r.id in ids_filtrados]
    else:
        registros = list(registros)

    if fecha_raw:
        fecha_parseada = parse_date(fecha_raw)
        if fecha_parseada:
            registros = [
                r for r in registros
                if r.fecha_creacion.date() == fecha_parseada
            ]

    if es_admin and vendedor_id:
        registros = [
            r for r in registros
            if str(r.usuario_id or '') == vendedor_id
        ]

    return registros, query, fecha_raw, vendedor_id


def _envolver_ventas(registros, valores_map):
    """Convierte registros de Ventas en DynamicVentaWrapper con relaciones resueltas."""
    # Precargar datos de productos relacionados
    producto_ids = set()
    for r in registros:
        vals = valores_map.get(r.id, {})
        prod_id = vals.get('producto', '').strip()
        if prod_id and prod_id.isdigit():
            producto_ids.add(int(prod_id))

    # Precargar wrappers de productos
    producto_wrappers = {}
    if producto_ids:
        try:
            form_prod = DS.obtener_formulario(FORM_PRODUCTOS)
            prod_registros = Registro.objects.filter(id__in=list(producto_ids), formulario=form_prod)
            prod_valores = DS.cargar_valores_mapa(prod_registros)
            for pr in prod_registros:
                producto_wrappers[pr.id] = DynamicProductWrapper(pr, prod_valores.get(pr.id, {}))
        except Exception:
            pass

    # Precargar datos de clientes relacionados
    cliente_ids = set()
    for r in registros:
        vals = valores_map.get(r.id, {})
        cli_id = vals.get('cliente', '').strip()
        if cli_id and cli_id.isdigit():
            cliente_ids.add(int(cli_id))

    cliente_wrappers = {}
    if cliente_ids:
        try:
            form_cli = DS.obtener_formulario(FORM_CLIENTES)
            cli_registros = Registro.objects.filter(id__in=list(cliente_ids), formulario=form_cli)
            cli_valores = DS.cargar_valores_mapa(cli_registros)
            for cr in cli_registros:
                cliente_wrappers[cr.id] = DynamicClienteWrapper(cr, cli_valores.get(cr.id, {}))
        except Exception:
            pass

    # Resolver vendedores
    user_ids = {r.usuario_id for r in registros if r.usuario_id}
    users = {}
    if user_ids:
        for u in User.objects.filter(id__in=list(user_ids)).only('id', 'username'):
            users[u.id] = u.username

    # Envolver cada venta
    ventas = []
    for r in registros:
        vals = valores_map.get(r.id, {})
        prod_id_str = vals.get('producto', '').strip()
        prod_id = int(prod_id_str) if prod_id_str and prod_id_str.isdigit() else None
        cli_id_str = vals.get('cliente', '').strip()
        cli_id = int(cli_id_str) if cli_id_str and cli_id_str.isdigit() else None

        producto_w = producto_wrappers.get(prod_id) if prod_id else None
        cliente_w = cliente_wrappers.get(cli_id) if cli_id else None
        vendedor_username = users.get(r.usuario_id, '') if r.usuario_id else ''

        ventas.append(DynamicVentaWrapper(
            r, vals,
            producto_wrapper=producto_w,
            cliente_wrapper=cliente_w,
            vendedor_username=vendedor_username,
        ))

    return ventas


# ======================================================================
# VISTA: HISTORIAL DE VENTAS (DINÁMICO)
# ======================================================================


@login_required(login_url='login')
def historial_ventas(request):
    """
    Historial de ventas usando DynamicService.
    Mantiene exactamente la misma interfaz que la vista legacy:
    - Mismos filtros (q, fecha, vendedor)
    - Mismas estadísticas (total_filtrado, unidades_filtradas, cantidad_ventas)
    - Mismo template (ventas/historial_ventas.html)
    - Mismas variables de contexto para compatibilidad
    """
    es_admin = es_administrador(request.user)

    try:
        form = DS.obtener_formulario(FORM_VENTAS)
    except Exception:
        return _render_historial_vacio(request, es_admin)

    # Obtener todas las ventas
    registros = Registro.objects.filter(formulario=form).order_by('-fecha_creacion')

    # Filtrar por vendedor si no es admin
    if not es_admin:
        registros = registros.filter(usuario=request.user)

    # Precargar valores
    valores_map = DS.cargar_valores_mapa(registros)

    # Aplicar filtros
    registros_filtrados, query, fecha, vendedor_id = _aplicar_filtros_ventas_dinamico(
        request, registros, valores_map, es_admin
    )

    # Calcular estadísticas
    cantidad_ventas = len(registros_filtrados)
    total_filtrado = Decimal('0')
    unidades_filtradas = 0
    for r in registros_filtrados:
        vals = valores_map.get(r.id, {})
        total_filtrado += _decimal(vals.get('total', '0'))
        unidades_filtradas += _entero(vals.get('cantidad', '0'))

    # Envolver ventas
    ventas = _envolver_ventas(registros_filtrados, valores_map)

    # Paginación
    vendedores = _vendedores_registrados() if es_admin else User.objects.none()
    per_page, per_page_int = obtener_por_pagina(request)
    paginator = Paginator(ventas, per_page_int)
    pagina = request.GET.get('page')
    ventas_pagina = paginator.get_page(pagina)
    query_params = parametros_sin_pagina(request, ['page'])

    return render(request, 'ventas/historial_ventas.html', {
        'ventas': ventas_pagina,
        'vendedores': vendedores,
        'query': query,
        'fecha': fecha,
        'vendedor_id': vendedor_id,
        'es_admin': es_admin,
        'rol_usuario': rol_usuario(request.user),
        'total_filtrado': total_filtrado,
        'unidades_filtradas': unidades_filtradas,
        'cantidad_ventas': cantidad_ventas,
        'query_params': query_params,
        'per_page': per_page,
        'per_page_options': OPCIONES_POR_PAGINA,
    })


def _render_historial_vacio(request, es_admin):
    """Renderiza el historial vacío cuando no hay formulario Ventas."""
    return render(request, 'ventas/historial_ventas.html', {
        'ventas': [],
        'vendedores': User.objects.none(),
        'query': '',
        'fecha': '',
        'vendedor_id': '',
        'es_admin': es_admin,
        'rol_usuario': rol_usuario(request.user),
        'total_filtrado': Decimal('0'),
        'unidades_filtradas': 0,
        'cantidad_ventas': 0,
        'query_params': '',
        'per_page': '10',
        'per_page_options': OPCIONES_POR_PAGINA,
    })


# ======================================================================
# VISTA: DETALLE DE CLIENTE (DINÁMICO)
# ======================================================================


@login_required(login_url='login')
def detalle_cliente(request, cliente_id):
    """
    Detalle de cliente usando DynamicService.
    Muestra datos del cliente y sus compras asociadas mediante relaciones dinámicas.
    Mantiene el mismo template (clientes/detalle_cliente.html).
    """
    try:
        form_clientes = DS.obtener_formulario(FORM_CLIENTES)
        cliente_registro = get_object_or_404(
            Registro.objects.filter(formulario=form_clientes),
            id=cliente_id
        )
    except Exception:
        return redirect('clientes')

    # Obtener valores del cliente
    cliente_valores = DS.obtener_valores(cliente_registro)
    cliente = DynamicClienteWrapper(cliente_registro, cliente_valores)

    # Obtener ventas asociadas a este cliente mediante relación dinámica
    try:
        form_ventas = DS.obtener_formulario(FORM_VENTAS)
        campo_cliente = Campo.objects.filter(
            formulario=form_ventas,
            nombre='cliente',
            activo=True
        ).first()

        if campo_cliente:
            # Buscar ventas donde valores__campo=campo_cliente AND valores__valor=str(cliente_id)
            ventas_registros = Registro.objects.filter(
                formulario=form_ventas,
                valores__campo=campo_cliente,
                valores__valor=str(cliente_id)
            ).order_by('-fecha_creacion')
        else:
            ventas_registros = Registro.objects.filter(
                formulario=form_ventas
            ).order_by('-fecha_creacion')[:0]
    except Exception:
        ventas_registros = []

    # Precargar valores de las ventas
    ventas_valores_map = DS.cargar_valores_mapa(ventas_registros)

    # Envolver ventas con relaciones
    ventas = _envolver_ventas(ventas_registros, ventas_valores_map)

    # Calcular estadísticas del cliente
    total_comprado = sum(_decimal(v.total) for v in ventas)
    cantidad_ventas = len(ventas)
    unidades_compradas = sum(_entero(v.cantidad) for v in ventas)
    productos_ids = set()
    for v in ventas:
        prod_id_str = ventas_valores_map.get(v.id, {}).get('producto', '').strip()
        if prod_id_str and prod_id_str.isdigit():
            productos_ids.add(prod_id_str)
    productos_diferentes = len(productos_ids)

    # Setear estadísticas en el wrapper
    cliente.cantidad_ventas = cantidad_ventas
    cliente.total_comprado = total_comprado
    cliente.ultima_compra = ventas[0].fecha if ventas else None

    # Paginación
    per_page, per_page_int = obtener_por_pagina(request)
    paginator = Paginator(ventas, per_page_int)
    pagina = request.GET.get('page')
    ventas_pagina = paginator.get_page(pagina)
    query_params = parametros_sin_pagina(request, ['page'])

    return render(request, 'clientes/detalle_cliente.html', {
        'cliente': cliente,
        'ventas': ventas_pagina,
        'total_comprado': total_comprado,
        'cantidad_ventas': cantidad_ventas,
        'unidades_compradas': unidades_compradas,
        'productos_diferentes': productos_diferentes,
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
        'query_params': query_params,
        'per_page': per_page,
        'per_page_options': OPCIONES_POR_PAGINA,
    })


# ======================================================================
# VISTA: LISTADO DE CLIENTES (DINÁMICO)
# ======================================================================


@login_required(login_url='login')
@admin_required
def clientes(request):
    """
    Listado de clientes con estadísticas usando DynamicService.

    Reemplazo completo de la vista legacy apps.legacy.ventas.views.clientes.
    Mantiene el mismo template, los mismos filtros, paginación y estadísticas.

    Las estadísticas de ventas (cantidad_ventas, total_comprado) se obtienen
    consultando los registros del formulario Ventas relacionados.
    """
    es_admin = es_administrador(request.user)
    query = request.GET.get('q', '').strip()

    try:
        form = DS.obtener_formulario(FORM_CLIENTES)
    except Exception:
        return render(request, 'clientes/clientes.html', {
            'clientes': [],
            'query': query,
            'total_clientes': 0,
            'clientes_con_compras': 0,
            'total_compras': Decimal('0'),
            'es_admin': es_admin,
            'rol_usuario': rol_usuario(request.user),
            'query_params': '',
            'per_page': '10',
        'per_page_options': OPCIONES_POR_PAGINA,
    })


    registros = Registro.objects.filter(formulario=form)
    valores_map = DS.cargar_valores_mapa(registros)

    # Filtrar por texto de búsqueda
    if query:
        query_lower = query.lower()
        registros = [
            r for r in registros
            if query_lower in ' '.join(
                v.lower() for v in valores_map.get(r.id, {}).values() if v
            )
        ]

    # Ordenar por nombre, apellido (mismo orden que legacy Cliente.Meta.ordering)
    registros.sort(key=lambda r: (
        valores_map.get(r.id, {}).get('nombre', '').lower(),
        valores_map.get(r.id, {}).get('apellido', '').lower(),
    ))

    total_clientes = len(registros)
    cliente_ids_filtrados = {str(r.id) for r in registros}

    # Obtener estadísticas de ventas para los clientes filtrados
    cliente_stats = {}
    total_compras = Decimal('0')
    try:
        form_ventas = DS.obtener_formulario(FORM_VENTAS)
        campo_cliente = Campo.objects.get(
            formulario=form_ventas,
            nombre='cliente',
            activo=True
        )
        ventas_registros = Registro.objects.filter(
            formulario=form_ventas,
            valores__campo=campo_cliente,
            valores__valor__in=cliente_ids_filtrados
        ).order_by('-fecha_creacion')
        ventas_valores = DS.cargar_valores_mapa(ventas_registros)

        for vr in ventas_registros:
            vvals = ventas_valores.get(vr.id, {})
            cli_id = vvals.get('cliente', '').strip()
            if not cli_id or cli_id not in cliente_ids_filtrados:
                continue
            total = _decimal(vvals.get('total', '0'))
            if cli_id not in cliente_stats:
                cliente_stats[cli_id] = {
                    'cantidad_ventas': 0,
                    'total_comprado': Decimal('0'),
                    'ultima_compra': None,
                }
            cliente_stats[cli_id]['cantidad_ventas'] += 1
            cliente_stats[cli_id]['total_comprado'] += total
            total_compras += total
            if cliente_stats[cli_id]['ultima_compra'] is None:
                cliente_stats[cli_id]['ultima_compra'] = vr.fecha_creacion
    except Exception:
        pass

    clientes_con_compras = len(cliente_stats)

    # Envolver en wrappers con estadísticas
    clientes_lista = []
    for r in registros:
        vals = valores_map.get(r.id, {})
        wrapper = DynamicClienteWrapper(r, vals)
        stats = cliente_stats.get(str(r.id), {})
        wrapper.cantidad_ventas = stats.get('cantidad_ventas', 0)
        wrapper.total_comprado = stats.get('total_comprado', Decimal('0'))
        wrapper.ultima_compra = stats.get('ultima_compra', None)
        clientes_lista.append(wrapper)

    # Paginación
    per_page, per_page_int = obtener_por_pagina(request)
    paginator = Paginator(clientes_lista, per_page_int)
    pagina = request.GET.get('page')
    clientes_pagina = paginator.get_page(pagina)
    query_params = parametros_sin_pagina(request, ['page'])

    return render(request, 'clientes/clientes.html', {
        'clientes': clientes_pagina,
        'query': query,
        'total_clientes': total_clientes,
        'clientes_con_compras': clientes_con_compras,
        'total_compras': total_compras,
        'es_admin': es_admin,
        'rol_usuario': rol_usuario(request.user),
        'query_params': query_params,
        'per_page': per_page,
        'per_page_options': OPCIONES_POR_PAGINA,
    })


# ======================================================================
# VISTA: EDITAR CLIENTE (DINÁMICO)
# ======================================================================


@login_required(login_url='login')
@admin_required
def editar_cliente(request, cliente_id):
    """
    Edición de cliente usando DynamicService.

    Reemplazo completo de la vista legacy apps.legacy.ventas.views.editar_cliente.
    - GET: carga el registro dinámico + valores y renderiza el template existente.
    - POST: valida campos obligatorios y delega la actualización en DS.actualizar().
    """
    try:
        form = DS.obtener_formulario(FORM_CLIENTES)
        registro = get_object_or_404(
            Registro.objects.filter(formulario=form),
            id=cliente_id
        )
    except Exception:
        return redirect('clientes')

    valores_actuales = DS.obtener_valores(registro)
    cliente = DynamicClienteWrapper(registro, valores_actuales)

    if request.method == 'POST':
        documento = request.POST.get('documento', '').strip()
        nombre = request.POST.get('nombre', '').strip()
        apellido = request.POST.get('apellido', '').strip()
        correo = request.POST.get('correo', '').strip()
        telefono = request.POST.get('telefono', '').strip()

        if not documento or not nombre or not apellido:
            messages.error(request, 'Documento, nombre y apellido son obligatorios.')
            return redirect('editar_cliente', cliente_id=cliente_id)

        try:
            DS.actualizar(registro, {
                'documento': documento,
                'nombre': nombre,
                'apellido': apellido,
                'correo': correo,
                'telefono': telefono,
            }, usuario=request.user)
            messages.success(request, 'Cliente actualizado correctamente.')
            return redirect('clientes')
        except Exception as e:
            logger.exception(f'Error actualizando cliente #{cliente_id}: {e}')
            messages.error(request, f'No se pudo actualizar el cliente: {e}')
            return redirect('editar_cliente', cliente_id=cliente_id)

    return render(request, 'clientes/editar_cliente.html', {
        'cliente': cliente,
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })
