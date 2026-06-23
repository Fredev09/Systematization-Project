from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side


def exportar_registros_excel(registros, campos, formulario_nombre):
    """
    Genera un archivo Excel con los registros de un formulario dinámico.

    Args:
        registros: QuerySet de Registro
        campos: QuerySet de Campo ordenados
        formulario_nombre: Nombre del formulario para el título

    Returns:
        HttpResponse con el archivo Excel
    """
    wb = Workbook()
    ws = wb.active
    ws.title = 'Registros'

    # Estilos
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

    # Construir encabezados
    encabezados = ['#', 'Fecha']
    for campo in campos:
        encabezados.append(campo.nombre)
    encabezados.append('Usuario')

    # Título y resumen
    ws.append([f'Registros: {formulario_nombre}'])
    ws.append([
        f'Total de registros: {registros.count()}',
        f'Generado: {timezone.localtime(timezone.now()).strftime("%d/%m/%Y %I:%M %p")}'
    ])
    ws.append([])
    ws.append(encabezados)

    # Mapa de valores por registro: {registro_id: {campo_id: valor}}
    from .models import ValorCampo
    valores_qs = ValorCampo.objects.filter(
        registro__in=registros
    ).select_related('campo', 'registro')

    valores_map = {}
    for vc in valores_qs:
        if vc.registro_id not in valores_map:
            valores_map[vc.registro_id] = {}
        valores_map[vc.registro_id][vc.campo_id] = vc.valor

    # Datos
    campos_ids = [c.id for c in campos]
    for registro in registros:
        fecha = timezone.localtime(registro.fecha_creacion).strftime(
            '%d/%m/%Y %I:%M %p'
        )
        usuario = registro.usuario.username if registro.usuario else ''

        fila = [registro.id, fecha]
        valores_reg = valores_map.get(registro.id, {})
        for campo_id in campos_ids:
            fila.append(valores_reg.get(campo_id, ''))

        fila.append(usuario)
        ws.append(fila)

    # Formato del título
    num_columnas = len(encabezados)
    ws.merge_cells(
        start_row=1, start_column=1,
        end_row=1, end_column=num_columnas
    )
    ws['A1'].fill = titulo_fill
    ws['A1'].font = titulo_font
    ws['A1'].alignment = center
    ws.row_dimensions[1].height = 28

    # Formato del resumen
    for cell in ws[2]:
        cell.fill = resumen_fill
        cell.font = resumen_font
        cell.alignment = left
        cell.border = Border(
            left=borde_color, right=borde_color,
            top=borde_color, bottom=borde_color
        )

    # Formato de encabezados
    for cell in ws[4]:
        cell.fill = encabezado_fill
        cell.font = encabezado_font
        cell.alignment = center
        cell.border = Border(
            left=borde_color, right=borde_color,
            top=borde_color, bottom=borde_color
        )

    # Formato de datos
    for row in ws.iter_rows(min_row=5):
        for cell in row:
            cell.font = texto_font
            cell.alignment = left
            cell.border = Border(
                left=borde_color, right=borde_color,
                top=borde_color, bottom=borde_color
            )

    def _col_letter(n):
        letters = ''
        while n > 0:
            n -= 1
            letters = chr(65 + (n % 26)) + letters
            n //= 26
        return letters

    # Anchos de columna
    ws.column_dimensions['A'].width = 8
    ws.column_dimensions['B'].width = 22
    for i, _ in enumerate(campos, start=3):
        col_letter = _col_letter(i)
        ws.column_dimensions[col_letter].width = 28

    ultima_col = _col_letter(num_columnas)

    if num_columnas >= 3:
        letra_usuario = _col_letter(num_columnas)
        ws.column_dimensions[letra_usuario].width = 22

    ws.freeze_panes = 'A5'
    ws.auto_filter.ref = f'A4:{ultima_col}{ws.max_row}'

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = (
        f'attachment; filename="registros_{formulario_nombre.lower().replace(" ", "_")}.xlsx"'
    )

    wb.save(response)
    return response
