---
name: dynamic-export
description: >-
  Exports Dynamic Forms data to Excel using openpyxl. Follows the exact
  styling and structure used in exportar_ventas(), exportar_historial_inventario_excel(),
  and exportar_reporte_excel(). Pink title row, light pink headers,
  frozen panes, auto-filter.
license: MIT
compatibility: opencode
metadata:
  audience: developer
  module: exports
  real_files: apps/legacy/ventas/views_dynamic.py, apps/legacy/productos/views_dynamic.py
---

# dynamic-export

Exports Dynamic Forms data to Excel (`.xlsx`) following the consistent
styling pattern used across all export functions in the project.

## When to use

- Exporting filtered lists (ventas, inventory, products, users).
- Creating report exports with summary rows.
- Generating Excel with multi-sheet workbooks.

## When NOT to use

- CSV exports (simple `csv.writer` is sufficient).
- PDF reports (use ReportLab pattern in reportes/views.py).
- Single-record exports (copy-paste is simpler).

## Real project pattern

All exports use openpyxl with an identical visual style:
- Pink title row (`D41473` / white text)
- Light pink header row (`FCE7F3` / dark text)
- Thin gray borders (`E5E7EB`)
- Frozen panes at the header row
- Auto-filter on header row
- Custom column widths

## Pattern: Excel export with filters + relations

The most complete example is `exportar_ventas` (ventas/views_dynamic.py:501-760):

```python
@login_required(login_url='login')
def exportar_ventas(request):
    # 1. Get filtered data (reuses the same helpers as list view)
    form = DS.obtener_formulario(FORM_VENTAS)
    registros = Registro.objects.filter(formulario=form).order_by('-fecha_creacion')
    valores_map = DS.cargar_valores_mapa(registros)

    registros_filtrados, query, fecha, vendedor_id = _aplicar_filtros_ventas_dinamico(
        request, list(registros), valores_map, es_admin
    )

    # 2. Pre-resolve relations (avoid N+1 in export)
    ventas = _envolver_ventas(registros_filtrados, valores_map)

    user_ids = {r.usuario_id for r in registros_filtrados if r.usuario_id}
    users_map = {}
    for u in User.objects.filter(id__in=user_ids).only('id', 'username'):
        users_map[u.id] = u.get_full_name() or u.username

    # 3. Build Excel workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'Historial ventas'

    headers = ['Fecha', 'Producto', 'Categoria', 'Cantidad', 'Total', ...]

    # Row 1: Title (merged)
    ws.append(['Historial de ventas'])

    # Row 2: Summary with filters applied
    ws.append([f"Busqueda: {query}", f"Ventas: {len(ventas)}", ...])

    # Row 3: Empty
    ws.append([])

    # Row 4: Headers
    ws.append(headers)

    # Rows 5+: Data
    for venta in ventas:
        ws.append([...])

    # 4. Apply consistent styles
    titulo_fill = PatternFill('solid', fgColor='D41473')
    encabezado_fill = PatternFill('solid', fgColor='FCE7F3')
    titulo_font = Font(color='FFFFFF', bold=True, size=15)
    encabezado_font = Font(color='111827', bold=True)
    center = Alignment(horizontal='center', vertical='center')
    borde_color = Side(style='thin', color='E5E7EB')

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    ws['A1'].fill = titulo_fill
    ws['A1'].font = titulo_font
    ws['A1'].alignment = center

    for cell in ws[4]:
        cell.fill = encabezado_fill
        cell.font = encabezado_font
        cell.alignment = center

    for row in ws.iter_rows(min_row=5):
        for cell in row:
            cell.border = Border(
                left=borde_color, right=borde_color,
                top=borde_color, bottom=borde_color
            )

    # 5. Column widths
    anchos = {'A': 23, 'B': 28, 'C': 22, ...}
    for columna, ancho in anchos.items():
        ws.column_dimensions[columna].width = ancho

    # 6. Freeze panes + auto-filter
    ws.freeze_panes = 'A5'
    ws.auto_filter.ref = f'A4:{chr(64+len(headers))}{ws.max_row}'

    # 7. Response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="export.xlsx"'
    wb.save(response)
    return response
```

## Styling constants

The project uses these exact style values in all exports:

| Element | Fill | Font |
|---------|------|------|
| Title row | `D41473` (pink) | White, bold, 14-15pt |
| Summary row | `FFF1F8` (light pink) | `4B5563`, bold |
| Header row | `FCE7F3` (pink tint) | `111827`, bold |
| Data rows | None | `111827` |
| Borders | `E5E7EB` thin | — |

## Checklist

- [ ] Data filtered using existing helpers (reuse `_filtrar_movimientos_dinamicos`,
      `_aplicar_filtros_ventas_dinamico`, etc.)
- [ ] Relations pre-resolved in batch before the data loop
- [ ] `PatternFill`, `Font`, `Alignment`, `Border`, `Side` imported from
      `openpyxl.styles`
- [ ] Title row merged across all columns
- [ ] Summary row with filter info (query, dates, totals)
- [ ] Header row with bold pink fill
- [ ] All data rows have thin gray borders
- [ ] Column widths set explicitly
- [ ] `freeze_panes` set below header row
- [ ] `auto_filter.ref` set on header range
- [ ] Content-Type set to `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- [ ] Content-Disposition with `attachment; filename="...xlsx"`

## Frequent errors

- **N+1 during export**: The export loop iterates all records. If each
  iteration resolves a relation, that's N extra queries. Pre-resolve
  like `_envolver_ventas` does (ventas/views_dynamic.py:560-594).
- **Missing openpyxl imports**: The specific style classes must be imported:
  `from openpyxl.styles import Alignment, Border, Font, PatternFill, Side`.
- **Wrong freeze panes**: Freeze at the row AFTER headers.
  If headers are row 4, freeze at `A5`.
- **Auto-filter out of range**: Build the range dynamically using
  `chr(64 + column_count)` for the last column letter.
- **Empty dataset crash**: Always handle empty `mov_list` / `ventas` by
  returning an empty workbook, not crashing.

## Reference files

| Export function | File | Lines |
|----------------|------|-------|
| exportar_ventas | ventas/views_dynamic.py | 501-760 |
| exportar_historial_inventario_excel | productos/views_dynamic.py | 992-1091 |
| exportar_reporte_excel | reportes/views.py | 949-1170 |
| exportar_reporte_completo_pdf | reportes/views.py | 1172-1231 |
