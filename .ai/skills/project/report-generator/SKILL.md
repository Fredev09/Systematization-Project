---
name: report-generator
description: >-
  Generates report data from Dynamic Forms following the Fase 1 migration
  pattern in obtener_datos_reportes_dinamico(). Covers KPI aggregation,
  monthly breakdowns, product/vendor/category grouping, chart data
  (SVG line, donut), and PDF/Excel export for reports.
license: MIT
compatibility: opencode
metadata:
  audience: developer
  module: reports
  real_files: apps/shared/reportes/views.py
---

# report-generator

Generates report data and visualizations from Dynamic Forms, following
the exact pattern used in `apps/shared/reportes/views.py`.

## When to use

- Building dashboard KPIs from Dynamic Forms data.
- Creating monthly sales aggregations with period comparison.
- Generating chart data (SVG line chart, conic-gradient donut).
- Building top-N rankings (products, vendors, categories).
- Exporting reports to PDF or Excel.

## When NOT to use

- Simple record counts — use `DS.contar()`.
- Real-time data (<1s refresh) — EAV aggregation is too slow.
- Complex SQL aggregations with nested subqueries.

## Real project pattern

The function `obtener_datos_reportes_dinamico()` (reportes/views.py:456-801)
migrated the legacy report data layer to Dynamic Forms in Fase 1. It
aggregates KPIs, monthly sales, product rankings, and category breakdowns
all in a single pass over the data.

## Pattern: Single-pass KPI aggregation

```python
# From obtener_datos_reportes_dinamico (reportes/views.py:563-643)
# Accumulators
ventas_totales = Decimal('0')
productos_vendidos = 0
cantidad_ventas = 0
ingresos_mes = Decimal('0')
ingresos_mes_anterior = Decimal('0')
mes_totales = [Decimal('0') for _ in range(6)]
producto_data = {}     # {prod_id: {'cantidad': int, 'total': Decimal}}
vendedor_data = {}     # {user_id: {'total': Decimal}}
categoria_data = {}    # {cat_name: {'total': Decimal}}

# Single pass
form_ventas = DS.obtener_formulario('Ventas')
registros_qs = Registro.objects.filter(formulario=form_ventas)
valores_map = DS.cargar_valores_mapa(registros_qs)

for r in registros_qs:
    vals = valores_map.get(r.id, {})
    total = _decimal_seguro(vals.get('total', '0'))
    cantidad = _entero_seguro(vals.get('cantidad', '0'))
    prod_id_str = vals.get('producto', '').strip()
    prod_id = int(prod_id_str) if prod_id_str and prod_id_str.isdigit() else None

    ventas_totales += total
    productos_vendidos += cantidad
    cantidad_ventas += 1

    # Monthly filtering
    if inicio_mes <= r.fecha_creacion < fin_mes:
        ingresos_mes += total
    if inicio_mes_anterior <= r.fecha_creacion < fin_mes_anterior:
        ingresos_mes_anterior += total
```

## Pattern: Monthly ranges for chart data

```python
# From obtener_datos_reportes_dinamico (reportes/views.py:544-560)
hoy = timezone.localdate()
month_ranges = []
for i in range(5, -1, -1):
    mes = hoy.month - i
    year = hoy.year
    while mes <= 0:
        mes += 12
        year -= 1
    m_inicio = datetime(year, mes, 1)
    if mes == 12:
        m_fin = datetime(year + 1, 1, 1)
    else:
        m_fin = datetime(year, mes + 1, 1)
    m_inicio = timezone.make_aware(m_inicio)
    m_fin = timezone.make_aware(m_fin)
    month_ranges.append((m_inicio, m_fin, m_inicio.strftime('%b %Y')))
```

## Pattern: Top-N ranking

```python
# From obtener_datos_reportes_dinamico (reportes/views.py:716-733)
productos_ordenados = sorted(
    [(pid, pd['cantidad'], pd['total']) for pid, pd in producto_data.items()],
    key=lambda x: x[1],
    reverse=True
)[:5]

max_top = max([p[1] or 0 for p in productos_ordenados] + [1])
top_productos = [
    {
        'nombre': prod_nombre.get(pid, f'Producto #{pid}'),
        'cantidad': cant,
        'total': tot,
        'porcentaje': max(12, round((cant / max_top) * 100)),
    }
    for pid, cant, tot in productos_ordenados
]
```

## Pattern: Category donut data

```python
# From obtener_datos_reportes_dinamico (reportes/views.py:700-711)
categorias_ordenadas = sorted(
    [{'nombre': k, 'total': v['total']} for k, v in categoria_data.items()],
    key=lambda x: x['total'],
    reverse=True
)[:6]
donut_gradient, ventas_categorias = construir_donut_categorias(
    [{'producto__categoria__nombre': c['nombre'], 'total': c['total']}
     for c in categorias_ordenadas]
)
```

## Checklist

- [ ] Single-pass data aggregation (never iterate registros twice)
- [ ] `DS.cargar_valores_mapa()` used once before the loop
- [ ] Month ranges pre-computed before the main loop
- [ ] `_decimal_seguro()` / `_entero_seguro()` for safe conversion
- [ ] Product/vendor/category data accumulated in dicts during pass
- [ ] Top-N computed after the pass via `sorted()[:N]`
- [ ] Percentage bars clamped to minimum visible width (`max(12, ...)`)
- [ ] try/except around all DS calls for graceful fallback

## Frequent errors

- **Double iteration**: Iterating registros once for KPIs and again for
  rankings. Do everything in a single pass using accumulator dicts.
- **Not using timezone-aware dates**: `r.fecha_creacion` is timezone-aware
  but `datetime(year, mes, 1)` is naive. Always use `timezone.make_aware()`.
- **Division by zero**: `ticket_promedio = total / cantidad_ventas` crashes
  when `cantidad_ventas == 0`. Always check: `if cantidad_ventas > 0`.
- **Hardcoded form names**: Use constants or literal 'FormName' strings
  consistently. The report module uses literal 'Ventas', 'Productos'.

## Reference files

| Component | File | Lines |
|-----------|------|-------|
| Dynamic KPI aggregation | reportes/views.py | 456-801 |
| Legacy report (reference) | reportes/views.py | 304-430 |
| SVG line chart builder | reportes/views.py | 210-270 |
| Donut chart builder | reportes/views.py | 273-301 |
| Stock stats helper | productos/views_dynamic.py | 219-277 |
