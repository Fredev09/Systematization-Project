from datetime import datetime, time, timedelta
from math import floor, log10

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from config.permissions import GRUPO_ADMINISTRADOR, admin_required, es_administrador, rol_usuario
from apps.legacy.productos.models import Categoria, Producto
from apps.legacy.productos.views_dynamic import _movimientos_recientes_dinamicos, _stock_stats_completo
from apps.legacy.productos.wrappers import DynamicProductWrapper
from apps.platform.dynamic_forms.models import Registro
from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
from apps.legacy.ventas.models import Cliente, Venta


def rango_dia(fecha):
    zona = timezone.get_current_timezone()
    inicio = datetime.combine(fecha, time.min)
    fin = inicio + timedelta(days=1)

    if timezone.is_naive(inicio):
        inicio = timezone.make_aware(inicio, zona)

    if timezone.is_naive(fin):
        fin = timezone.make_aware(fin, zona)

    return inicio, fin


def rango_mes(fecha):
    zona = timezone.get_current_timezone()
    inicio = datetime(fecha.year, fecha.month, 1)

    if fecha.month == 12:
        fin = datetime(fecha.year + 1, 1, 1)
    else:
        fin = datetime(fecha.year, fecha.month + 1, 1)

    if timezone.is_naive(inicio):
        inicio = timezone.make_aware(inicio, zona)

    if timezone.is_naive(fin):
        fin = timezone.make_aware(fin, zona)

    return inicio, fin


def vendedores_registrados():
    return User.objects.filter(
        is_active=True
    ).exclude(
        is_superuser=True
    ).exclude(
        groups__name=GRUPO_ADMINISTRADOR
    ).distinct().order_by('first_name', 'last_name', 'username')


def obtener_filtros_reportes(request):
    fecha_inicio = request.GET.get('fecha_inicio', '').strip()
    fecha_fin = request.GET.get('fecha_fin', '').strip()
    vendedor_id = request.GET.get('vendedor', '').strip()
    categoria_id = request.GET.get('categoria', '').strip()
    producto_id = request.GET.get('producto', '').strip()
    tipo_reporte = request.GET.get('tipo_reporte', 'general').strip() or 'general'

    return {
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'vendedor_id': vendedor_id,
        'categoria_id': categoria_id,
        'producto_id': producto_id,
        'tipo_reporte': tipo_reporte,
    }


def ventas_filtradas_reportes(request, ventas):
    filtros = obtener_filtros_reportes(request)

    fecha_inicio_parseada = parse_date(filtros['fecha_inicio']) if filtros['fecha_inicio'] else None
    fecha_fin_parseada = parse_date(filtros['fecha_fin']) if filtros['fecha_fin'] else None

    if fecha_inicio_parseada:
        inicio, _ = rango_dia(fecha_inicio_parseada)
        ventas = ventas.filter(fecha__gte=inicio)

    if fecha_fin_parseada:
        _, fin = rango_dia(fecha_fin_parseada)
        ventas = ventas.filter(fecha__lt=fin)

    if filtros['vendedor_id']:
        ventas = ventas.filter(vendedor_id=filtros['vendedor_id'])

    if filtros['categoria_id']:
        ventas = ventas.filter(producto__categoria_id=filtros['categoria_id'])

    if filtros['producto_id']:
        ventas = ventas.filter(producto_id=filtros['producto_id'])

    return ventas, filtros


def formato_pesos_pdf(valor):
    valor = int(valor or 0)
    return f"${valor:,}".replace(',', '.')


def formato_eje_pesos(valor):
    valor = int(valor or 0)

    if valor >= 1000000:
        numero = valor / 1000000

        if numero.is_integer():
            return f'${int(numero)}M'

        return f'${round(numero, 1)}M'.replace('.', ',')

    if valor >= 1000:
        numero = valor / 1000

        if numero.is_integer():
            return f'${int(numero)}K'

        return f'${round(numero, 1)}K'.replace('.', ',')

    return f'${valor}'


def formato_corto_pesos(valor):
    valor = int(valor or 0)

    if valor >= 1000000:
        numero = valor / 1000000

        if numero.is_integer():
            return f'${int(numero)}M'

        return f'${round(numero, 1)}M'.replace('.', ',')

    if valor >= 1000:
        numero = valor / 1000

        if numero.is_integer():
            return f'${int(numero)}K'

        return f'${round(numero)}K'

    return f'${valor}'


def calcular_maximo_eje(valor_maximo):
    valor_maximo = float(valor_maximo or 0)

    if valor_maximo <= 0:
        return 100000

    valor_maximo = valor_maximo * 1.12
    potencia = 10 ** floor(log10(valor_maximo))
    normalizado = valor_maximo / potencia

    if normalizado <= 1:
        escala = 1
    elif normalizado <= 2:
        escala = 2
    elif normalizado <= 5:
        escala = 5
    else:
        escala = 10

    return int(escala * potencia)


def construir_escala_y(maximo_eje):
    return [
        formato_eje_pesos(maximo_eje),
        formato_eje_pesos(maximo_eje * 5 / 6),
        formato_eje_pesos(maximo_eje * 4 / 6),
        formato_eje_pesos(maximo_eje * 3 / 6),
        formato_eje_pesos(maximo_eje * 2 / 6),
        formato_eje_pesos(maximo_eje * 1 / 6),
        '$0',
    ]


def calcular_porcentaje(actual, anterior):
    actual = float(actual or 0)
    anterior = float(anterior or 0)

    if anterior <= 0:
        return 0

    porcentaje = ((actual - anterior) / anterior) * 100
    return round(porcentaje, 1)


def construir_grafica_meses(ventas):
    hoy = timezone.localdate()
    meses = []

    for i in range(5, -1, -1):
        mes = hoy.month - i
        year = hoy.year

        while mes <= 0:
            mes += 12
            year -= 1

        inicio = datetime(year, mes, 1)

        if mes == 12:
            fin = datetime(year + 1, 1, 1)
        else:
            fin = datetime(year, mes + 1, 1)

        inicio = timezone.make_aware(inicio, timezone.get_current_timezone())
        fin = timezone.make_aware(fin, timezone.get_current_timezone())

        total = ventas.filter(
            fecha__gte=inicio,
            fecha__lt=fin
        ).aggregate(
            total=Sum('total')
        )['total'] or 0

        meses.append({
            'nombre': inicio.strftime('%b %Y'),
            'total': total,
        })

    maximo_real = max([float(mes['total'] or 0) for mes in meses] + [0])
    maximo_eje = calcular_maximo_eje(maximo_real)
    escala_y = construir_escala_y(maximo_eje)

    puntos = []

    for index, mes in enumerate(meses):
        total = float(mes['total'] or 0)
        x = 20 + (index * 112)
        proporcion = total / maximo_eje if maximo_eje > 0 else 0
        y = 230 - (proporcion * 210)

        puntos.append(f'{x} {y}')

        mes['left'] = round(4 + ((index / 5) * 92), 2) if len(meses) > 1 else 50
        mes['bottom'] = round(proporcion * 92, 2)

    line_path = 'M' + ' L'.join(puntos) if puntos else ''

    if puntos:
        primer_x = 20
        ultimo_x = 20 + ((len(meses) - 1) * 112)
        area_path = line_path + f' L{ultimo_x} 230 L{primer_x} 230 Z'
    else:
        area_path = ''

    return meses, line_path, area_path, escala_y


def construir_donut_categorias(categorias):
    colores = ['#d41473', '#ff7b8a', '#8b5cf6', '#f6c453', '#22c55e', '#0ea5e9']
    total_general = sum(float(categoria['total'] or 0) for categoria in categorias)

    if total_general <= 0:
        return '', []

    inicio = 0
    partes = []
    resultado = []

    for index, categoria in enumerate(categorias[:6]):
        total = float(categoria['total'] or 0)
        porcentaje = round((total / total_general) * 100, 1)
        fin = inicio + porcentaje
        color = colores[index % len(colores)]

        partes.append(f'{color} {inicio}% {fin}%')

        resultado.append({
            'nombre': categoria['producto__categoria__nombre'] or 'Sin categoría',
            'total': categoria['total'],
            'porcentaje': porcentaje,
            'color': color,
        })

        inicio = fin

    return ', '.join(partes), resultado


def obtener_datos_reportes(request):
    ventas_base = Venta.objects.select_related(
        'producto',
        'producto__categoria',
        'vendedor',
        'cliente'
    )

    ventas, filtros = ventas_filtradas_reportes(request, ventas_base)

    hoy = timezone.localdate()
    inicio_mes, fin_mes = rango_mes(hoy)

    if hoy.month == 1:
        fecha_mes_anterior = hoy.replace(year=hoy.year - 1, month=12)
    else:
        fecha_mes_anterior = hoy.replace(month=hoy.month - 1)

    inicio_mes_anterior, fin_mes_anterior = rango_mes(fecha_mes_anterior)

    ventas_mes_actual = ventas_base.filter(
        fecha__gte=inicio_mes,
        fecha__lt=fin_mes
    )

    ventas_mes_anterior = ventas_base.filter(
        fecha__gte=inicio_mes_anterior,
        fecha__lt=fin_mes_anterior
    )

    ventas_totales = ventas.aggregate(total=Sum('total'))['total'] or 0
    ingresos_mes = ventas_mes_actual.aggregate(total=Sum('total'))['total'] or 0
    ingresos_mes_anterior = ventas_mes_anterior.aggregate(total=Sum('total'))['total'] or 0
    productos_vendidos = ventas.aggregate(total=Sum('cantidad'))['total'] or 0

    clientes_nuevos = Cliente.objects.filter(
        fecha_registro__gte=inicio_mes,
        fecha_registro__lt=fin_mes
    ).count()

    cantidad_ventas = ventas.count()
    ticket_promedio = ventas_totales / cantidad_ventas if cantidad_ventas > 0 else 0

    porcentaje_mes = calcular_porcentaje(ingresos_mes, ingresos_mes_anterior)
    porcentaje_ventas = porcentaje_mes
    porcentaje_productos = 0
    porcentaje_clientes = 0

    ventas_meses, ventas_meses_line_path, ventas_meses_area_path, escala_y = construir_grafica_meses(ventas_base)

    categorias_ventas_raw = list(
        ventas.values('producto__categoria__nombre')
        .annotate(total=Sum('total'))
        .order_by('-total')[:6]
    )

    donut_gradient, ventas_categorias = construir_donut_categorias(categorias_ventas_raw)

    top_productos_raw = list(
        ventas.values('producto__nombre')
        .annotate(
            cantidad=Sum('cantidad'),
            total=Sum('total')
        )
        .order_by('-cantidad')[:5]
    )

    max_top = max([item['cantidad'] or 0 for item in top_productos_raw] + [1])
    top_productos = []

    for item in top_productos_raw:
        top_productos.append({
            'nombre': item['producto__nombre'],
            'cantidad': item['cantidad'] or 0,
            'total': item['total'] or 0,
            'porcentaje': max(12, round(((item['cantidad'] or 0) / max_top) * 100)),
        })

    categoria_top = 'Sin datos'

    if ventas_categorias:
        categoria_top = f"{ventas_categorias[0]['nombre']} ({ventas_categorias[0]['porcentaje']}%)"

    vendedor_top_raw = (
        ventas.values('vendedor__username')
        .annotate(total=Sum('total'))
        .order_by('-total')
        .first()
    )

    vendedor_top = 'Sin datos'

    if vendedor_top_raw:
        vendedor_top = f"{vendedor_top_raw['vendedor__username']} ({formato_corto_pesos(vendedor_top_raw['total'])})"

    productos_stock_critico = Producto.objects.filter(stock__lte=5).count()

    vendedores = vendedores_registrados()
    categorias = Categoria.objects.all().order_by('nombre')
    productos = Producto.objects.select_related('categoria').all().order_by('nombre')

    return {
        'ventas': ventas,
        'filtros': filtros,
        'vendedores': vendedores,
        'categorias': categorias,
        'productos': productos,
        'ventas_totales': ventas_totales,
        'ingresos_mes': ingresos_mes,
        'productos_vendidos': productos_vendidos,
        'clientes_nuevos': clientes_nuevos,
        'porcentaje_ventas': porcentaje_ventas,
        'porcentaje_mes': porcentaje_mes,
        'porcentaje_productos': porcentaje_productos,
        'porcentaje_clientes': porcentaje_clientes,
        'ventas_meses': ventas_meses,
        'ventas_meses_line_path': ventas_meses_line_path,
        'ventas_meses_area_path': ventas_meses_area_path,
        'escala_y': escala_y,
        'donut_gradient': donut_gradient,
        'ventas_categorias': ventas_categorias,
        'top_productos': top_productos,
        'categoria_top': categoria_top,
        'ticket_promedio': ticket_promedio,
        'vendedor_top': vendedor_top,
        'productos_stock_critico': productos_stock_critico,
    }


def crear_estilos_pdf():
    estilos = getSampleStyleSheet()

    return {
        'titulo': ParagraphStyle(
            'TituloReporte',
            parent=estilos['Title'],
            fontName='Helvetica-Bold',
            fontSize=20,
            leading=24,
            textColor=colors.HexColor('#111827'),
            alignment=TA_CENTER,
            spaceAfter=14,
        ),
        'subtitulo': ParagraphStyle(
            'SubtituloReporte',
            parent=estilos['Normal'],
            fontName='Helvetica-Bold',
            fontSize=13,
            leading=16,
            textColor=colors.HexColor('#d41473'),
            alignment=TA_LEFT,
            spaceBefore=12,
            spaceAfter=8,
        ),
        'normal': ParagraphStyle(
            'TextoReporte',
            parent=estilos['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=12,
            textColor=colors.HexColor('#374151'),
        ),
        'pequeno': ParagraphStyle(
            'TextoPequeno',
            parent=estilos['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor('#6b7280'),
        ),
    }


def tabla_pdf(data, col_widths=None, header=True):
    tabla = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)

    estilos = [
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#111827')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')]),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]

    if header:
        estilos.extend([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d41473')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ])

    tabla.setStyle(TableStyle(estilos))
    return tabla


def crear_pdf_response(nombre_archivo, titulo, elementos, pagesize=landscape(letter)):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'

    doc = SimpleDocTemplate(
        response,
        pagesize=pagesize,
        rightMargin=0.45 * inch,
        leftMargin=0.45 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
        title=titulo,
    )

    doc.build(elementos)
    return response


def agregar_encabezado_pdf(elementos, estilos, titulo, request, filtros):
    fecha_generacion = timezone.localtime(timezone.now()).strftime('%d/%m/%Y %I:%M %p')

    elementos.append(Paragraph(titulo, estilos['titulo']))

    resumen = [
        ['Generado por', request.user.username, 'Fecha de generación', fecha_generacion],
        ['Fecha inicial', filtros['fecha_inicio'] or 'Todas', 'Fecha final', filtros['fecha_fin'] or 'Todas'],
        ['Vendedor', filtros['vendedor_id'] or 'Todos', 'Tipo de reporte', filtros['tipo_reporte']],
    ]

    elementos.append(tabla_pdf(resumen, [1.3 * inch, 2.2 * inch, 1.5 * inch, 2.4 * inch], header=False))
    elementos.append(Spacer(1, 12))


@login_required(login_url='login')
@admin_required
def reportes(request):
    datos = obtener_datos_reportes(request)

    return render(request, 'reportes/reportes.html', {
        'fecha_inicio': datos['filtros']['fecha_inicio'],
        'fecha_fin': datos['filtros']['fecha_fin'],
        'vendedor_id': datos['filtros']['vendedor_id'],
        'categoria_id': datos['filtros']['categoria_id'],
        'producto_id': datos['filtros']['producto_id'],
        'tipo_reporte': datos['filtros']['tipo_reporte'],
        'vendedores': datos['vendedores'],
        'categorias': datos['categorias'],
        'productos': datos['productos'],
        'ventas_totales': datos['ventas_totales'],
        'ingresos_mes': datos['ingresos_mes'],
        'productos_vendidos': datos['productos_vendidos'],
        'clientes_nuevos': datos['clientes_nuevos'],
        'porcentaje_ventas': datos['porcentaje_ventas'],
        'porcentaje_mes': datos['porcentaje_mes'],
        'porcentaje_productos': datos['porcentaje_productos'],
        'porcentaje_clientes': datos['porcentaje_clientes'],
        'ventas_meses': datos['ventas_meses'],
        'ventas_meses_line_path': datos['ventas_meses_line_path'],
        'ventas_meses_area_path': datos['ventas_meses_area_path'],
        'escala_y': datos['escala_y'],
        'donut_gradient': datos['donut_gradient'],
        'ventas_categorias': datos['ventas_categorias'],
        'top_productos': datos['top_productos'],
        'categoria_top': datos['categoria_top'],
        'ticket_promedio': datos['ticket_promedio'],
        'vendedor_top': datos['vendedor_top'],
        'productos_stock_critico': datos['productos_stock_critico'],
        'es_admin': es_administrador(request.user),
        'rol_usuario': rol_usuario(request.user),
    })



@login_required(login_url='login')
@admin_required
def exportar_reporte_excel(request):
    datos = obtener_datos_reportes(request)
    ventas = datos['ventas'].order_by('-fecha')
    filtros = datos['filtros']

    vendedor_nombre = 'Todos'
    categoria_nombre = 'Todas'
    producto_nombre = 'Todos'

    if filtros['vendedor_id']:
        vendedor = User.objects.filter(id=filtros['vendedor_id']).first()
        if vendedor:
            vendedor_nombre = vendedor.get_full_name() or vendedor.username

    if filtros['categoria_id']:
        categoria = Categoria.objects.filter(id=filtros['categoria_id']).first()
        if categoria:
            categoria_nombre = categoria.nombre

    if filtros['producto_id']:
        producto = Producto.objects.filter(id=filtros['producto_id']).first()
        if producto:
            producto_nombre = producto.nombre

    wb = Workbook()
    ws = wb.active
    ws.title = 'Reporte'

    titulo_fill = PatternFill('solid', fgColor='D41473')
    encabezado_fill = PatternFill('solid', fgColor='FCE7F3')
    resumen_fill = PatternFill('solid', fgColor='FFF1F8')
    borde_color = Side(style='thin', color='E5E7EB')

    titulo_font = Font(color='FFFFFF', bold=True, size=15)
    encabezado_font = Font(color='111827', bold=True)
    resumen_font = Font(color='4B5563', bold=True)
    texto_font = Font(color='111827')

    center = Alignment(horizontal='center', vertical='center')
    left = Alignment(horizontal='left', vertical='center')

    ws.append(['Reporte general'])
    ws.append([
        f"Desde: {filtros['fecha_inicio'] or 'Todas'}",
        f"Hasta: {filtros['fecha_fin'] or 'Todas'}",
        f"Vendedor: {vendedor_nombre}",
        f"Categoria: {categoria_nombre}",
        f"Producto: {producto_nombre}",
        f"Tipo: {filtros['tipo_reporte'] or 'general'}"
    ])
    ws.append([])
    ws.append(['Indicador', 'Valor'])
    ws.append(['Ventas totales', float(datos['ventas_totales'] or 0)])
    ws.append(['Ingresos del mes', float(datos['ingresos_mes'] or 0)])
    ws.append(['Productos vendidos', datos['productos_vendidos'] or 0])
    ws.append(['Clientes nuevos', datos['clientes_nuevos'] or 0])
    ws.append(['Ticket promedio', float(datos['ticket_promedio'] or 0)])
    ws.append(['Categoria top', datos['categoria_top']])
    ws.append(['Vendedor top', datos['vendedor_top']])
    ws.append(['Productos con stock critico', datos['productos_stock_critico']])

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)
    ws['A1'].fill = titulo_fill
    ws['A1'].font = titulo_font
    ws['A1'].alignment = center
    ws.row_dimensions[1].height = 28

    for cell in ws[2]:
        cell.fill = resumen_fill
        cell.font = resumen_font
        cell.alignment = left
        cell.border = Border(left=borde_color, right=borde_color, top=borde_color, bottom=borde_color)

    for cell in ws[4]:
        cell.fill = encabezado_fill
        cell.font = encabezado_font
        cell.alignment = center
        cell.border = Border(left=borde_color, right=borde_color, top=borde_color, bottom=borde_color)

    for row in ws.iter_rows(min_row=5, max_row=12):
        for cell in row:
            cell.font = texto_font
            cell.alignment = left
            cell.border = Border(left=borde_color, right=borde_color, top=borde_color, bottom=borde_color)

    for cell in ws['B'][4:12]:
        if isinstance(cell.value, (int, float)):
            cell.number_format = '"$"#,##0'

    ws.column_dimensions['A'].width = 30
    ws.column_dimensions['B'].width = 28
    ws.column_dimensions['C'].width = 28
    ws.column_dimensions['D'].width = 28
    ws.column_dimensions['E'].width = 28
    ws.column_dimensions['F'].width = 24

    ventas_ws = wb.create_sheet('Ventas')
    encabezados_ventas = [
        'Fecha', 'Producto', 'Categoria', 'Color', 'Talla', 'Cantidad', 'Total',
        'Vendedor', 'Documento cliente', 'Cliente', 'Correo cliente'
    ]
    ventas_ws.append(['Detalle de ventas'])
    ventas_ws.append([
        f"Desde: {filtros['fecha_inicio'] or 'Todas'}",
        f"Hasta: {filtros['fecha_fin'] or 'Todas'}",
        f"Vendedor: {vendedor_nombre}",
        f"Categoria: {categoria_nombre}",
        f"Producto: {producto_nombre}",
        f"Registros: {ventas.count()}"
    ])
    ventas_ws.append([])
    ventas_ws.append(encabezados_ventas)

    for venta in ventas:
        ventas_ws.append([
            timezone.localtime(venta.fecha).strftime('%d/%m/%Y %I:%M %p'),
            venta.producto.nombre,
            venta.producto.categoria.nombre if venta.producto.categoria else 'Sin categoria',
            venta.producto.color,
            venta.producto.talla,
            venta.cantidad,
            float(venta.total or 0),
            venta.vendedor.username if venta.vendedor else '',
            venta.cliente.documento if venta.cliente else '',
            venta.cliente.nombre_completo if venta.cliente else 'Sin cliente',
            venta.cliente.correo if venta.cliente and venta.cliente.correo else '',
        ])

    ventas_ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=11)
    ventas_ws['A1'].fill = titulo_fill
    ventas_ws['A1'].font = titulo_font
    ventas_ws['A1'].alignment = center
    ventas_ws.row_dimensions[1].height = 28

    for cell in ventas_ws[2]:
        cell.fill = resumen_fill
        cell.font = resumen_font
        cell.alignment = left
        cell.border = Border(left=borde_color, right=borde_color, top=borde_color, bottom=borde_color)

    for cell in ventas_ws[4]:
        cell.fill = encabezado_fill
        cell.font = encabezado_font
        cell.alignment = center
        cell.border = Border(left=borde_color, right=borde_color, top=borde_color, bottom=borde_color)

    for row in ventas_ws.iter_rows(min_row=5):
        for cell in row:
            cell.font = texto_font
            cell.alignment = left
            cell.border = Border(left=borde_color, right=borde_color, top=borde_color, bottom=borde_color)

    for cell in ventas_ws['G'][4:]:
        cell.number_format = '"$"#,##0'

    anchos_ventas = {
        'A': 23, 'B': 28, 'C': 22, 'D': 16, 'E': 12, 'F': 12,
        'G': 16, 'H': 22, 'I': 20, 'J': 28, 'K': 30,
    }
    for columna, ancho in anchos_ventas.items():
        ventas_ws.column_dimensions[columna].width = ancho

    ventas_ws.freeze_panes = 'A5'
    ventas_ws.auto_filter.ref = f'A4:K{ventas_ws.max_row}'

    top_ws = wb.create_sheet('Top productos')
    top_ws.append(['Top productos'])
    top_ws.append(['Producto', 'Cantidad', 'Total'])
    for producto in datos['top_productos']:
        top_ws.append([producto['nombre'], producto['cantidad'], float(producto['total'] or 0)])

    top_ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=3)
    top_ws['A1'].fill = titulo_fill
    top_ws['A1'].font = titulo_font
    top_ws['A1'].alignment = center
    for cell in top_ws[2]:
        cell.fill = encabezado_fill
        cell.font = encabezado_font
        cell.alignment = center
    for row in top_ws.iter_rows(min_row=3):
        for cell in row:
            cell.font = texto_font
            cell.alignment = left
    for cell in top_ws['C'][2:]:
        cell.number_format = '"$"#,##0'
    top_ws.column_dimensions['A'].width = 32
    top_ws.column_dimensions['B'].width = 14
    top_ws.column_dimensions['C'].width = 18

    categorias_ws = wb.create_sheet('Categorias')
    categorias_ws.append(['Ventas por categoria'])
    categorias_ws.append(['Categoria', 'Total', 'Porcentaje'])
    for categoria in datos['ventas_categorias']:
        categorias_ws.append([categoria['nombre'], float(categoria['total'] or 0), f"{categoria['porcentaje']}%"])

    categorias_ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=3)
    categorias_ws['A1'].fill = titulo_fill
    categorias_ws['A1'].font = titulo_font
    categorias_ws['A1'].alignment = center
    for cell in categorias_ws[2]:
        cell.fill = encabezado_fill
        cell.font = encabezado_font
        cell.alignment = center
    for row in categorias_ws.iter_rows(min_row=3):
        for cell in row:
            cell.font = texto_font
            cell.alignment = left
    for cell in categorias_ws['B'][2:]:
        cell.number_format = '"$"#,##0'
    categorias_ws.column_dimensions['A'].width = 32
    categorias_ws.column_dimensions['B'].width = 18
    categorias_ws.column_dimensions['C'].width = 16

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="reporte_general.xlsx"'

    wb.save(response)
    return response

@login_required(login_url='login')
@admin_required
def exportar_reporte_completo_pdf(request):
    datos = obtener_datos_reportes(request)
    estilos = crear_estilos_pdf()
    elementos = []

    agregar_encabezado_pdf(elementos, estilos, 'Reporte completo - Tonjeo', request, datos['filtros'])

    elementos.append(Paragraph('Resumen general', estilos['subtitulo']))

    resumen = [
        ['Indicador', 'Valor'],
        ['Ventas totales', formato_pesos_pdf(datos['ventas_totales'])],
        ['Ingresos del mes', formato_pesos_pdf(datos['ingresos_mes'])],
        ['Productos vendidos', datos['productos_vendidos']],
        ['Clientes nuevos', datos['clientes_nuevos']],
        ['Ticket promedio', formato_pesos_pdf(datos['ticket_promedio'])],
        ['Categoría más vendida', datos['categoria_top']],
        ['Vendedor top', datos['vendedor_top']],
        ['Productos en stock crítico', datos['productos_stock_critico']],
    ]

    elementos.append(tabla_pdf(resumen, [3.2 * inch, 4.8 * inch]))
    elementos.append(Spacer(1, 12))

    elementos.append(Paragraph('Ventas por categoría', estilos['subtitulo']))

    categorias = [['Categoría', 'Total vendido', 'Participación']]

    for categoria in datos['ventas_categorias']:
        categorias.append([
            categoria['nombre'],
            formato_pesos_pdf(categoria['total']),
            f"{categoria['porcentaje']}%",
        ])

    if len(categorias) == 1:
        categorias.append(['Sin datos', '$0', '0%'])

    elementos.append(tabla_pdf(categorias, [3.2 * inch, 2.4 * inch, 1.6 * inch]))
    elementos.append(Spacer(1, 12))

    elementos.append(Paragraph('Top productos vendidos', estilos['subtitulo']))

    top_productos = [['Producto', 'Cantidad', 'Total vendido']]

    for producto in datos['top_productos']:
        top_productos.append([
            producto['nombre'],
            producto['cantidad'],
            formato_pesos_pdf(producto['total']),
        ])

    if len(top_productos) == 1:
        top_productos.append(['Sin datos', '0', '$0'])

    elementos.append(tabla_pdf(top_productos, [3.6 * inch, 1.6 * inch, 2.4 * inch]))

    return crear_pdf_response('reporte_completo.pdf', 'Reporte completo', elementos)


@login_required(login_url='login')
@admin_required
def exportar_reporte_ventas_pdf(request):
    datos = obtener_datos_reportes(request)
    estilos = crear_estilos_pdf()
    elementos = []

    agregar_encabezado_pdf(elementos, estilos, 'Reporte de ventas - Tonjeo', request, datos['filtros'])

    elementos.append(Paragraph('Resumen de ventas', estilos['subtitulo']))

    resumen = [
        ['Ventas totales', formato_pesos_pdf(datos['ventas_totales'])],
        ['Productos vendidos', datos['productos_vendidos']],
        ['Ticket promedio', formato_pesos_pdf(datos['ticket_promedio'])],
        ['Vendedor top', datos['vendedor_top']],
    ]

    elementos.append(tabla_pdf(resumen, [3.2 * inch, 4.8 * inch], header=False))
    elementos.append(Spacer(1, 12))

    elementos.append(Paragraph('Detalle de ventas', estilos['subtitulo']))

    ventas = datos['ventas'].order_by('-fecha')[:120]

    tabla_ventas = [['Fecha', 'Producto', 'Categoría', 'Cliente', 'Vendedor', 'Cantidad', 'Total']]

    for venta in ventas:
        fecha = timezone.localtime(venta.fecha).strftime('%d/%m/%Y %I:%M %p')
        categoria = venta.producto.categoria.nombre if venta.producto.categoria else 'Sin categoría'
        cliente = venta.cliente.nombre_completo if venta.cliente else 'Sin cliente'

        tabla_ventas.append([
            fecha,
            venta.producto.nombre,
            categoria,
            cliente,
            venta.vendedor.username,
            venta.cantidad,
            formato_pesos_pdf(venta.total),
        ])

    if len(tabla_ventas) == 1:
        tabla_ventas.append(['Sin datos', '', '', '', '', '', '$0'])

    elementos.append(tabla_pdf(
        tabla_ventas,
        [1.3 * inch, 1.6 * inch, 1.25 * inch, 1.4 * inch, 1.2 * inch, 0.75 * inch, 1.0 * inch]
    ))

    return crear_pdf_response('reporte_ventas.pdf', 'Reporte de ventas', elementos)


@login_required(login_url='login')
@admin_required
def exportar_reporte_inventario_pdf(request):
    filtros = obtener_filtros_reportes(request)
    estilos = crear_estilos_pdf()
    elementos = []

    agregar_encabezado_pdf(elementos, estilos, 'Reporte de inventario - Tonjeo', request, filtros)

    # -- Resumen con estadísticas desde Dynamic Forms --
    stats = _stock_stats_completo(stock_minimo=5)
    total_productos = stats['total_productos']
    productos_sin_stock = stats['sin_stock']
    # El legacy usa stock__lte=5 (incluye 0): sin_stock + stock_bajo = stock_critico
    productos_stock_critico = stats['sin_stock'] + stats['stock_bajo']
    valor_inventario = stats['valor_total']

    elementos.append(Paragraph('Resumen de inventario', estilos['subtitulo']))

    resumen = [
        ['Indicador', 'Valor'],
        ['Total de productos', total_productos],
        ['Productos sin stock', productos_sin_stock],
        ['Productos con stock crítico', productos_stock_critico],
        ['Valor total del inventario', formato_pesos_pdf(valor_inventario)],
    ]

    elementos.append(tabla_pdf(resumen, [3.2 * inch, 4.8 * inch]))
    elementos.append(Spacer(1, 12))

    # -- Inventario actual: productos desde Dynamic Forms --
    elementos.append(Paragraph('Inventario actual', estilos['subtitulo']))

    formulario = DS.obtener_formulario('Productos')
    registros = list(Registro.objects.filter(formulario=formulario))
    valores_map = DS.cargar_valores_mapa(registros)
    productos = [
        DynamicProductWrapper(r, valores_map.get(r.id, {}))
        for r in registros
    ]
    productos.sort(key=lambda p: p.nombre.lower())

    tabla_productos = [['Producto', 'Categoría', 'Color', 'Talla', 'Precio', 'Stock', 'Valor stock']]

    for producto in productos[:140]:
        tabla_productos.append([
            producto.nombre,
            producto.categoria_nombre or 'Sin categoría',
            producto.color or '',
            producto.talla or '',
            formato_pesos_pdf(producto.precio),
            producto.stock,
            formato_pesos_pdf(producto.valor_stock),
        ])

    if len(tabla_productos) == 1:
        tabla_productos.append(['Sin datos', '', '', '', '$0', '0', '$0'])

    elementos.append(tabla_pdf(
        tabla_productos,
        [1.7 * inch, 1.4 * inch, 1.1 * inch, 0.85 * inch, 1.0 * inch, 0.75 * inch, 1.1 * inch]
    ))
    elementos.append(Spacer(1, 12))

    # -- Movimientos recientes desde Dynamic Forms --
    elementos.append(Paragraph('Movimientos recientes de inventario', estilos['subtitulo']))

    movimientos = _movimientos_recientes_dinamicos(limite=60)

    tabla_movimientos = [['Fecha', 'Producto', 'Tipo', 'Cantidad', 'Stock antes', 'Stock nuevo', 'Motivo']]

    for movimiento in movimientos:
        fecha = timezone.localtime(movimiento.fecha).strftime('%d/%m/%Y %I:%M %p') if movimiento.fecha else ''

        tabla_movimientos.append([
            fecha,
            movimiento.producto.nombre,
            movimiento.get_tipo_display(),
            movimiento.cantidad,
            movimiento.stock_anterior,
            movimiento.stock_nuevo,
            movimiento.get_motivo_display() if movimiento.motivo else 'Sin motivo',
        ])

    if len(tabla_movimientos) == 1:
        tabla_movimientos.append(['Sin datos', '', '', '', '', '', ''])

    elementos.append(tabla_pdf(
        tabla_movimientos,
        [1.45 * inch, 1.7 * inch, 1.0 * inch, 0.85 * inch, 0.85 * inch, 0.85 * inch, 1.4 * inch]
    ))

    return crear_pdf_response('reporte_inventario.pdf', 'Reporte de inventario', elementos)