import json
from pathlib import Path
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from config.pagination import OPCIONES_POR_PAGINA, obtener_por_pagina, parametros_sin_pagina
from config.permissions import admin_required
from apps.shared.configuracion.models import ConfiguracionTienda
from .forms import OPCIONES_TALLAS, ProductoEditForm, ProductoForm
from .models import Categoria, MovimientoInventario, Producto


def obtener_stock_minimo():
    return ConfiguracionTienda.obtener().stock_minimo_alerta


def preparar_post_producto(request):
    data = request.POST.copy()

    if data.get('usar_tallas_multiples') == '1':
        tallas = [talla.strip() for talla in request.POST.getlist('talla_variante')]
        stocks = [stock.strip() for stock in request.POST.getlist('stock_variante')]
        encontro_variante = False

        for indice, talla in enumerate(tallas):
            stock = stocks[indice] if indice < len(stocks) else ''

            if talla and stock != '':
                data['talla'] = talla
                data['stock'] = stock
                encontro_variante = True
                break

        if not encontro_variante:
            data['talla'] = 'S'
            data['stock'] = '0'

    return data


def obtener_variantes_tallas(request):
    if request.POST.get('usar_tallas_multiples') != '1':
        return []

    tallas = [talla.strip() for talla in request.POST.getlist('talla_variante')]
    stocks = [stock.strip() for stock in request.POST.getlist('stock_variante')]
    variantes = []
    tallas_usadas = set()

    for indice, talla in enumerate(tallas):
        stock_raw = stocks[indice] if indice < len(stocks) else ''

        if not talla and not stock_raw:
            continue

        if not talla:
            raise ValidationError('Debes seleccionar la talla en cada fila.')

        try:
            stock = int(stock_raw)
        except (TypeError, ValueError):
            raise ValidationError('El stock de cada talla debe ser un número válido.')

        if stock < 0:
            raise ValidationError('El stock de cada talla no puede ser negativo.')

        clave = talla.lower()

        if clave in tallas_usadas:
            raise ValidationError(f'La talla {talla} está repetida.')

        tallas_usadas.add(clave)
        variantes.append((talla, stock))

    if not variantes:
        raise ValidationError('Agrega al menos una talla con su stock.')

    return variantes


def crear_productos_por_tallas(form, variantes, imagen_archivo):
    datos = form.cleaned_data
    productos_creados = []
    imagen_bytes = None
    imagen_nombre = ''

    if imagen_archivo:
        imagen_bytes = imagen_archivo.read()
        imagen_nombre = imagen_archivo.name
        imagen_archivo.seek(0)

    for talla, stock in variantes:
        producto = Producto(
            nombre=datos['nombre'],
            categoria=datos['categoria'],
            talla=talla,
            color=datos['color'],
            precio=datos['precio'],
            stock=stock,
            imagen_url=datos.get('imagen_url') or None
        )

        if imagen_bytes:
            nombre = Path(imagen_nombre).stem or 'producto'
            extension = Path(imagen_nombre).suffix or '.jpg'
            nombre_archivo = f'{nombre}_{talla}_{uuid4().hex[:8]}{extension}'
            producto.imagen.save(nombre_archivo, ContentFile(imagen_bytes), save=False)

        producto.save()
        productos_creados.append(producto)

        if stock > 0:
            MovimientoInventario.objects.create(
                producto=producto,
                tipo='entrada',
                motivo='correccion_manual',
                cantidad=stock,
                stock_anterior=0,
                stock_nuevo=stock,
                observacion='Stock inicial al registrar el producto por talla.'
            )

    return productos_creados


@login_required(login_url='login')
@admin_required
def listar_productos(request):
    query = request.GET.get('q', '')
    categoria_id = request.GET.get('categoria', '')
    stock = request.GET.get('stock', '')
    stock_minimo = obtener_stock_minimo()
    per_page, per_page_int = obtener_por_pagina(request)

    productos = Producto.objects.select_related('categoria').all().order_by('nombre')
    categorias = Categoria.objects.all().order_by('nombre')

    if query:
        productos = productos.filter(
            Q(nombre__icontains=query) |
            Q(talla__icontains=query) |
            Q(color__icontains=query)
        )

    if categoria_id:
        productos = productos.filter(categoria_id=categoria_id)

    if stock == 'bajo':
        productos = productos.filter(stock__gte=1, stock__lte=stock_minimo)
    elif stock == 'sin_stock':
        productos = productos.filter(stock=0)

    total_productos = Producto.objects.count()
    stock_bajo = Producto.objects.filter(stock__gte=1, stock__lte=stock_minimo).count()
    sin_stock = Producto.objects.filter(stock=0).count()

    paginator = Paginator(productos, per_page_int)
    pagina = request.GET.get('page')
    productos_pagina = paginator.get_page(pagina)
    query_params = parametros_sin_pagina(request, ['page'])

    return render(request, 'productos/productos.html', {
        'productos': productos_pagina,
        'categorias': categorias,
        'query': query,
        'categoria_id': categoria_id,
        'stock': stock,
        'total_productos': total_productos,
        'stock_bajo': stock_bajo,
        'sin_stock': sin_stock,
        'stock_minimo_alerta': stock_minimo,
        'query_params': query_params,
        'per_page': per_page,
        'per_page_options': OPCIONES_POR_PAGINA,
    })


@login_required(login_url='login')
@admin_required
def agregar_producto(request):
    if request.method == 'POST':
        post_data = preparar_post_producto(request)
        form = ProductoForm(post_data, request.FILES)

        if form.is_valid():
            try:
                variantes = obtener_variantes_tallas(request)

                if variantes:
                    productos_creados = crear_productos_por_tallas(
                        form,
                        variantes,
                        request.FILES.get('imagen')
                    )
                    messages.success(request, f'Se agregaron {len(productos_creados)} tallas del producto "{form.cleaned_data["nombre"]}" correctamente.')
                    return redirect('productos')

                producto = form.save()

                if producto.stock > 0:
                    MovimientoInventario.objects.create(
                        producto=producto,
                        tipo='entrada',
                        motivo='correccion_manual',
                        cantidad=producto.stock,
                        stock_anterior=0,
                        stock_nuevo=producto.stock,
                        observacion='Stock inicial al registrar el producto.'
                    )

                messages.success(request, f'Producto "{producto.nombre}" agregado correctamente.')
                return redirect('productos')

            except ValidationError as error:
                mensaje = error.messages[0] if hasattr(error, 'messages') and error.messages else 'No se pudieron validar las tallas.'
                messages.error(request, mensaje)
        else:
            messages.error(request, 'No se pudo agregar el producto. Revisa los datos ingresados.')
    else:
        form = ProductoForm()

    return render(request, 'productos/agregar_producto.html', {
        'form': form,
        'opciones_tallas': OPCIONES_TALLAS,
    })


@login_required(login_url='login')
@admin_required
@login_required(login_url='login')
@admin_required
def editar_producto(request, producto_id):
    producto = get_object_or_404(Producto, id=producto_id)

    if request.method == 'POST':
        form = ProductoEditForm(request.POST, request.FILES, instance=producto)

        if form.is_valid():
            producto = form.save()
            messages.success(request, f'Producto "{producto.nombre}" actualizado correctamente.')
            return redirect('productos')

        messages.error(request, 'No se pudo actualizar el producto. Revisa los datos ingresados.')
    else:
        form = ProductoEditForm(instance=producto)

    return render(request, 'productos/editar_producto.html', {
        'form': form,
        'producto': producto
    })


@login_required(login_url='login')
@admin_required
def actualizar_stock(request, producto_id):
    producto = get_object_or_404(
        Producto.objects.select_related('categoria'),
        id=producto_id
    )
    stock_minimo = obtener_stock_minimo()

    if request.method == 'POST':
        tipo = request.POST.get('tipo')
        motivo = request.POST.get('motivo') or None
        cantidad_raw = request.POST.get('cantidad')
        observacion = request.POST.get('observacion', '').strip() or None

        if not tipo or cantidad_raw in [None, '']:
            messages.error(request, 'Debes completar tipo de movimiento y cantidad.')
            return redirect('actualizar_stock', producto_id=producto.id)

        try:
            cantidad = int(cantidad_raw)
        except ValueError:
            messages.error(request, 'La cantidad debe ser un numero valido.')
            return redirect('actualizar_stock', producto_id=producto.id)

        if cantidad < 0:
            messages.error(request, 'La cantidad no puede ser negativa.')
            return redirect('actualizar_stock', producto_id=producto.id)

        if tipo in ['entrada', 'salida'] and cantidad == 0:
            messages.error(request, 'Para entradas o salidas la cantidad debe ser mayor a 0.')
            return redirect('actualizar_stock', producto_id=producto.id)

        if tipo not in ['entrada', 'salida', 'correccion']:
            messages.error(request, 'El tipo de movimiento no es valido.')
            return redirect('actualizar_stock', producto_id=producto.id)

        try:
            with transaction.atomic():
                producto_bloqueado = Producto.objects.select_for_update().get(id=producto.id)
                stock_anterior = producto_bloqueado.stock

                if tipo == 'entrada':
                    stock_nuevo = stock_anterior + cantidad
                    cantidad_movimiento = cantidad
                elif tipo == 'salida':
                    stock_nuevo = stock_anterior - cantidad
                    cantidad_movimiento = cantidad

                    if stock_nuevo < 0:
                        raise ValidationError('No puedes retirar mas productos de los que hay actualmente.')
                else:
                    stock_nuevo = cantidad
                    cantidad_movimiento = abs(stock_nuevo - stock_anterior)

                producto_bloqueado.stock = stock_nuevo
                producto_bloqueado.save(update_fields=['stock'])

                MovimientoInventario.objects.create(
                    producto=producto_bloqueado,
                    tipo=tipo,
                    motivo=motivo,
                    cantidad=cantidad_movimiento,
                    stock_anterior=stock_anterior,
                    stock_nuevo=stock_nuevo,
                    observacion=observacion
                )

            messages.success(
                request,
                f'Stock de "{producto.nombre}" actualizado correctamente. Antes: {stock_anterior}, ahora: {stock_nuevo}.'
            )
            return redirect('inventario')

        except ValidationError as error:
            messages.error(request, error.messages[0] if error.messages else 'No se pudo actualizar el stock.')
            return redirect('actualizar_stock', producto_id=producto.id)

    movimientos_producto = MovimientoInventario.objects.select_related(
        'producto',
        'producto__categoria'
    ).filter(
        producto=producto
    ).order_by('-fecha')

    per_page, per_page_int = obtener_por_pagina(request)
    paginator = Paginator(movimientos_producto, per_page_int)
    pagina = request.GET.get('page')
    movimientos_pagina = paginator.get_page(pagina)
    query_params = parametros_sin_pagina(request, ['page'])

    return render(request, 'productos/actualizar_stock.html', {
        'producto': producto,
        'tipoElecciones': MovimientoInventario.tipoElecciones,
        'motivoElecciones': MovimientoInventario.motivoElecciones,
        'movimientos_producto': movimientos_pagina,
        'stock_minimo_alerta': stock_minimo,
        'query_params': query_params,
        'per_page': per_page,
        'per_page_options': OPCIONES_POR_PAGINA,
    })


@login_required(login_url='login')
@admin_required
def eliminar_producto(request, producto_id):
    producto = get_object_or_404(Producto, id=producto_id)

    if request.method == 'POST':
        confirmar = request.POST.get('confirmar')

        if confirmar == 'si':
            nombre_producto = producto.nombre

            try:
                producto.delete()
            except ProtectedError:
                messages.error(
                    request,
                    f'No se puede eliminar "{nombre_producto}" porque tiene ventas registradas.'
                )
                return redirect('productos')

            messages.success(request, f'Producto "{nombre_producto}" eliminado correctamente.')
            return redirect('productos')

        messages.error(request, 'Debes confirmar la eliminacion para continuar.')
        return render(request, 'productos/eliminar_producto.html', {
            'producto': producto,
            'error': 'Debes confirmar la eliminacion para continuar.'
        })

    return render(request, 'productos/eliminar_producto.html', {
        'producto': producto
    })


@login_required(login_url='login')
@admin_required
def inventario(request):
    query = request.GET.get('q', '')
    categoria_id = request.GET.get('categoria', '')
    stock = request.GET.get('stock', '')
    stock_minimo = obtener_stock_minimo()

    productos = Producto.objects.select_related('categoria').all().order_by('stock', 'nombre')
    categorias = Categoria.objects.all().order_by('nombre')

    if query:
        productos = productos.filter(
            Q(nombre__icontains=query) |
            Q(talla__icontains=query) |
            Q(color__icontains=query)
        )

    if categoria_id:
        productos = productos.filter(categoria_id=categoria_id)

    if stock == 'bajo':
        productos = productos.filter(stock__gte=1, stock__lte=stock_minimo)
    elif stock == 'sin_stock':
        productos = productos.filter(stock=0)
    elif stock == 'disponible':
        productos = productos.filter(stock__gt=stock_minimo)

    productos_lista = list(productos)

    for producto in productos_lista:
        producto.valor_stock = producto.precio * producto.stock

    todos_productos = Producto.objects.all()

    total_productos = Producto.objects.count()
    stock_bajo = Producto.objects.filter(stock__gte=1, stock__lte=stock_minimo).count()
    sin_stock = Producto.objects.filter(stock=0).count()
    disponibles = Producto.objects.filter(stock__gt=stock_minimo).count()
    valor_total = sum(producto.precio * producto.stock for producto in todos_productos)

    productos_criticos = Producto.objects.select_related('categoria').filter(
        stock__gte=0,
        stock__lte=stock_minimo
    ).order_by('stock', 'nombre')[:8]

    movimientos_recientes = MovimientoInventario.objects.select_related(
        'producto',
        'producto__categoria'
    ).all().order_by('-fecha')

    productos_per_page, productos_per_page_int = obtener_por_pagina(request, 'productos_per_page')
    movimientos_per_page, movimientos_per_page_int = obtener_por_pagina(request, 'movimientos_per_page')

    productos_paginator = Paginator(productos_lista, productos_per_page_int)
    productos_pagina_numero = request.GET.get('productos_page')
    productos_pagina = productos_paginator.get_page(productos_pagina_numero)

    movimientos_paginator = Paginator(movimientos_recientes, movimientos_per_page_int)
    movimientos_pagina_numero = request.GET.get('movimientos_page')
    movimientos_pagina = movimientos_paginator.get_page(movimientos_pagina_numero)

    productos_query_params = parametros_sin_pagina(request, ['productos_page'])
    movimientos_query_params = parametros_sin_pagina(request, ['movimientos_page'])

    total_movimientos = MovimientoInventario.objects.count()
    total_entradas = MovimientoInventario.objects.filter(tipo='entrada').count()
    total_salidas = MovimientoInventario.objects.filter(tipo='salida').count()
    total_correcciones = MovimientoInventario.objects.filter(tipo='correccion').count()

    return render(request, 'inventario/inventario.html', {
        'productos': productos_pagina,
        'categorias': categorias,
        'query': query,
        'categoria_id': categoria_id,
        'stock': stock,
        'total_productos': total_productos,
        'stock_bajo': stock_bajo,
        'sin_stock': sin_stock,
        'disponibles': disponibles,
        'valor_total': valor_total,
        'productos_criticos': productos_criticos,
        'stock_minimo_alerta': stock_minimo,
        'movimientos_recientes': movimientos_pagina,
        'total_movimientos': total_movimientos,
        'total_entradas': total_entradas,
        'total_salidas': total_salidas,
        'total_correcciones': total_correcciones,
        'productos_query_params': productos_query_params,
        'movimientos_query_params': movimientos_query_params,
        'productos_per_page': productos_per_page,
        'movimientos_per_page': movimientos_per_page,
        'per_page_options': OPCIONES_POR_PAGINA,
    })


def filtrar_movimientos_inventario(request):
    query = request.GET.get('q', '').strip()
    tipo = request.GET.get('tipo', '').strip()
    motivo = request.GET.get('motivo', '').strip()
    fecha_inicio = request.GET.get('fecha_inicio', '').strip()
    fecha_fin = request.GET.get('fecha_fin', '').strip()

    movimientos = MovimientoInventario.objects.select_related(
        'producto',
        'producto__categoria'
    ).all().order_by('-fecha')

    if query:
        movimientos = movimientos.filter(
            Q(producto__nombre__icontains=query) |
            Q(producto__categoria__nombre__icontains=query) |
            Q(producto__color__icontains=query) |
            Q(producto__talla__icontains=query) |
            Q(observacion__icontains=query)
        )

    if tipo:
        movimientos = movimientos.filter(tipo=tipo)

    if motivo:
        movimientos = movimientos.filter(motivo=motivo)

    fecha_inicio_parseada = parse_date(fecha_inicio) if fecha_inicio else None
    fecha_fin_parseada = parse_date(fecha_fin) if fecha_fin else None

    if fecha_inicio_parseada:
        movimientos = movimientos.filter(fecha__date__gte=fecha_inicio_parseada)

    if fecha_fin_parseada:
        movimientos = movimientos.filter(fecha__date__lte=fecha_fin_parseada)

    return movimientos, {
        'query': query,
        'tipo': tipo,
        'motivo': motivo,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
    }


@login_required(login_url='login')
@admin_required
def historial_inventario(request):
    movimientos, filtros = filtrar_movimientos_inventario(request)

    total_filtrado = movimientos.count()
    entradas_filtradas = movimientos.filter(tipo='entrada').count()
    salidas_filtradas = movimientos.filter(tipo='salida').count()
    correcciones_filtradas = movimientos.filter(tipo='correccion').count()

    per_page, per_page_int = obtener_por_pagina(request)
    paginator = Paginator(movimientos, per_page_int)
    pagina = request.GET.get('page')
    movimientos_pagina = paginator.get_page(pagina)
    query_params = parametros_sin_pagina(request, ['page'])

    return render(request, 'inventario/historial_inventario.html', {
        'movimientos': movimientos_pagina,
        'query': filtros['query'],
        'tipo': filtros['tipo'],
        'motivo': filtros['motivo'],
        'fecha_inicio': filtros['fecha_inicio'],
        'fecha_fin': filtros['fecha_fin'],
        'tipoElecciones': MovimientoInventario.tipoElecciones,
        'motivoElecciones': MovimientoInventario.motivoElecciones,
        'total_filtrado': total_filtrado,
        'entradas_filtradas': entradas_filtradas,
        'salidas_filtradas': salidas_filtradas,
        'correcciones_filtradas': correcciones_filtradas,
        'query_params': query_params,
        'per_page': per_page,
        'per_page_options': OPCIONES_POR_PAGINA,
    })


@login_required(login_url='login')
@admin_required
def exportar_historial_inventario_excel(request):
    movimientos, filtros = filtrar_movimientos_inventario(request)

    wb = Workbook()
    ws = wb.active
    ws.title = 'Historial inventario'

    encabezados = [
        'Producto',
        'Categoria',
        'Tipo',
        'Cantidad',
        'Stock anterior',
        'Stock nuevo',
        'Motivo',
        'Observacion',
        'Fecha'
    ]

    ws.append(['Historial de movimientos de inventario'])
    ws.append([
        f"Busqueda: {filtros['query'] or 'Todos'}",
        f"Tipo: {filtros['tipo'] or 'Todos'}",
        f"Motivo: {filtros['motivo'] or 'Todos'}",
        f"Desde: {filtros['fecha_inicio'] or 'Sin fecha'}",
        f"Hasta: {filtros['fecha_fin'] or 'Sin fecha'}"
    ])
    ws.append([])
    ws.append(encabezados)

    for movimiento in movimientos:
        ws.append([
            movimiento.producto.nombre,
            movimiento.producto.categoria.nombre if movimiento.producto.categoria else 'Sin categoria',
            movimiento.get_tipo_display(),
            movimiento.cantidad,
            movimiento.stock_anterior,
            movimiento.stock_nuevo,
            movimiento.get_motivo_display() if movimiento.motivo else 'Sin motivo',
            movimiento.observacion or '',
            timezone.localtime(movimiento.fecha).strftime('%d/%m/%Y %I:%M %p')
        ])

    titulo_fill = PatternFill('solid', fgColor='D41473')
    encabezado_fill = PatternFill('solid', fgColor='FCE7F3')
    titulo_font = Font(color='FFFFFF', bold=True, size=14)
    encabezado_font = Font(color='111827', bold=True)
    center = Alignment(horizontal='center', vertical='center')
    left = Alignment(horizontal='left', vertical='center')

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=9)
    ws['A1'].fill = titulo_fill
    ws['A1'].font = titulo_font
    ws['A1'].alignment = center
    ws.row_dimensions[1].height = 28

    for cell in ws[4]:
        cell.fill = encabezado_fill
        cell.font = encabezado_font
        cell.alignment = center

    for row in ws.iter_rows(min_row=5):
        for cell in row:
            cell.alignment = left

    anchos = {
        'A': 28,
        'B': 22,
        'C': 16,
        'D': 12,
        'E': 16,
        'F': 16,
        'G': 26,
        'H': 38,
        'I': 22,
    }

    for columna, ancho in anchos.items():
        ws.column_dimensions[columna].width = ancho

    ws.freeze_panes = 'A5'
    ws.auto_filter.ref = f'A4:I{ws.max_row}'

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="historial_inventario.xlsx"'

    wb.save(response)

    return response



