---
name: dynamic-query
description: >-
  Optimized query patterns for Dynamic Forms EAV data. Covers batch loading
  with DS.cargar_valores_mapa(), Python-side filtering, aggregation,
  relation resolution, and N+1 elimination. Based on real patterns in
  productos/views_dynamic.py and ventas/views_dynamic.py.
license: MIT
compatibility: opencode
metadata:
  audience: developer
  module: queries
  real_files: apps/platform/dynamic_forms/services_dynamic.py
---

# dynamic-query

Query patterns for Dynamic Forms that avoid the performance pitfalls of
EAV. All patterns are extracted from real usage in the project's views.

## When to use

- Reading multiple EAV records for list/dashboard views.
- Filtering records by field values.
- Aggregating (SUM, COUNT) across EAV records.
- Resolving relations between forms (venta → producto, venta → cliente).
- Any code that accesses `ValorCampo` data.

## When NOT to use

- Reading a single record by ID — use `DS.obtener_valores()`.
- Database-level full-text search — use PostgreSQL `SearchVector`.
- Counting without data — use `DS.contar()`.

## Real project pattern

The fundamental principle: **one query for registros, one query for values,
filter and aggregate in Python.**

## Pattern 1: Batch loading (eliminates N+1)

**Bad** (N+1 — never do this):
```python
productos = []
for r in registros:
    valores = DS.obtener_valor(r, 'nombre')  # 1 query per registro
    #                                      ← N extra queries!
```

**Good** (batch load — always do this):
```python
# From listar_productos (views_dynamic.py:123)
todos_valores = DS.cargar_valores_mapa(registros)
# todos_valores = {registro_id: {campo_nombre: valor, ...}}

productos = [
    DynamicProductWrapper(r, todos_valores.get(r.id, {}))
    for r in registros
]
```

## Pattern 2: Python-side filtering

Since EAV stores values as rows, SQL filtering requires JOINs per field.
Filter in Python after batch loading:

```python
# From listar_productos (views_dynamic.py:148-152)
for campo_nombre, valor_buscado in filtros_activos.items():
    registros = [
        r for r in registros
        if todos_valores.get(r.id, {}).get(campo_nombre, '') == valor_buscado
    ]
```

For numeric filters (stock range):
```python
# From listar_productos (views_dynamic.py:155-164)
if stock_filtro == 'bajo':
    registros = [
        r for r in registros
        if 1 <= _entero(todos_valores.get(r.id, {}).get('stock', '0')) <= 5
    ]
```

## Pattern 3: Text search across multiple fields

```python
# From listar_productos (views_dynamic.py:133-143)
query_lower = query.lower()
campos_texto = [c for c in campos_producto
                if c.tipo in ('texto', 'email', 'telefono', 'textarea')]
ids_filtrados = set()
for r in registros:
    vals = todos_valores.get(r.id, {})
    for ct in campos_texto:
        if query_lower in vals.get(ct.nombre, '').lower():
            ids_filtrados.add(r.id)
            break
registros = [r for r in registros if r.id in ids_filtrados]
```

For ventas, a more concise approach searches all fields at once:
```python
# From _aplicar_filtros_ventas_dinamico (ventas/views_dynamic.py:318-331)
query_lower = query.lower()
ids_filtrados = set()
for r in registros:
    vals = valores_map.get(r.id, {})
    texto = ' '.join(v.lower() for v in vals.values() if v)
    if query_lower in texto:
        ids_filtrados.add(r.id)
registros = [r for r in registros if r.id in ids_filtrados]
```

## Pattern 4: Relation resolution without N+1

When a venta references a producto via `campo tipo 'relacion'`, resolve
all related records in batch:

```python
# From _envolver_ventas (ventas/views_dynamic.py:351-418)
# Step 1: Collect all referenced product IDs
producto_ids = set()
for r in registros:
    vals = valores_map.get(r.id, {})
    prod_id = vals.get('producto', '').strip()
    if prod_id and prod_id.isdigit():
        producto_ids.add(int(prod_id))

# Step 2: Batch-load all referenced products
producto_wrappers = {}
if producto_ids:
    form_prod = DS.obtener_formulario(FORM_PRODUCTOS)
    prod_registros = Registro.objects.filter(
        id__in=list(producto_ids), formulario=form_prod
    )
    prod_valores = DS.cargar_valores_mapa(prod_registros)
    for pr in prod_registros:
        producto_wrappers[pr.id] = DynamicProductWrapper(
            pr, prod_valores.get(pr.id, {})
        )
```

## Pattern 5: Aggregation in Python

```python
# From _stats_ventas (ventas/views_dynamic.py:121-152)
total = Decimal('0')
unidades = 0
valores = DS.cargar_valores_mapa(registros)

for r in registros:
    vals = valores.get(r.id, {})
    total += _decimal(vals.get('total', '0'))
    unidades += _entero(vals.get('cantidad', '0'))
```

## Pattern 6: Stats with multiple metrics (single pass)

```python
# From _stock_stats_completo (productos/views_dynamic.py:219-277)
valores_map = DS.cargar_valores_mapa(registros)

stock_bajo = 0
sin_stock = 0
disponibles = 0
valor_total = Decimal('0')

for r in registros:
    vals = valores_map.get(r.id, {})
    stock = _entero(vals.get('stock', '0'))
    precio = _decimal(vals.get('precio', '0'))
    valor_total += precio * stock

    if stock == 0:
        sin_stock += 1
    elif stock <= stock_minimo:
        stock_bajo += 1
    else:
        disponibles += 1
```

## Pattern 7: Filtering at DB level for specific fields

When you need DB-level filtering (for a specific Campo), use `ValorCampo`
directly:

```python
# From _filtrar_movimientos_dinamicos (productos/views_dynamic.py:835-875)
campo_tipo = DS.obtener_campo(form_mov, 'tipo')
mov_registros = mov_registros.filter(
    valores__campo=campo_tipo, valores__valor=tipo_dinamico
)
```

## Checklist

- [ ] `DS.cargar_valores_mapa()` used before iterating registros
- [ ] No `DS.obtener_valor()` calls inside loops
- [ ] Relations resolved in batch (collect IDs → single query → map)
- [ ] Aggregations done in Python on `valores_map` dict
- [ ] Text search uses `in` operator on lowercase strings
- [ ] Numeric fields converted with `_entero()` / `_decimal()` before comparison
- [ ] Wrappers constructed with pre-loaded `valores_map.get(r.id, {})`

## Frequent errors

- **Calling `DS.obtener_valor()` in a loop** — The #1 performance killer.
  Always batch with `DS.cargar_valores_mapa()`.
- **Filtering at DB level for multiple fields** — Each `.filter()` on
  `valores__campo` adds a JOIN. For 3+ fields, load all and filter in Python.
- **Not using `_entero()` for stock comparison** — Stock arrives as string
  `"5"`, comparison `"5" > "10"` is True lexicographically.
- **Forgetting list() on queryset** — After filtering registros in Python,
  the queryset is evaluated as a list. If you later filter the queryset
  again, Django re-evaluates. Convert to list explicitly.

## Reference files

| Pattern | File | Lines |
|---------|------|-------|
| Batch loading | productos/views_dynamic.py | 51-60, 123 |
| Python filtering | productos/views_dynamic.py | 148-164 |
| Text search | productos/views_dynamic.py | 133-143 |
| Relation resolution | ventas/views_dynamic.py | 351-418 |
| Stats single-pass | productos/views_dynamic.py | 219-277 |
| DB-level filtering | productos/views_dynamic.py | 835-875 |
