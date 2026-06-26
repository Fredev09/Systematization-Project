---
name: build-dynamic-view
description: >-
  Builds a Django view that uses DynamicService for CRUD operations on EAV
  data. Based on the real pattern in listar_productos, historial_ventas,
  agregar_producto, editar_producto, and eliminar_producto. Covers list,
  create, edit, and delete views.
license: MIT
compatibility: opencode
metadata:
  audience: developer
  module: views
  real_files: apps/legacy/productos/views_dynamic.py, apps/legacy/ventas/views_dynamic.py
---

# build-dynamic-view

Builds Django views that operate on Dynamic Forms data following the exact
pattern used across all `views_dynamic.py` files in the project.

## When to use

- Creating a new list view for a dynamic form.
- Creating create/edit/delete views.
- Adding filters and pagination to an existing dynamic view.
- Replacing a legacy Django model view with a dynamic equivalent.

## When NOT to use

- The page has no data persistence (static/about pages).
- The data comes from a non-Dynamic-Forms source (Django admin, third-party API).

## Real project pattern

Two files contain the full pattern: `apps/legacy/productos/views_dynamic.py`
(1362 lines) and `apps/legacy/ventas/views_dynamic.py` (1107 lines). All
views follow the same structure.

## List view pattern

The canonical example is `listar_productos` (productos/views_dynamic.py:101-211).

```python
@login_required(login_url='login')
@admin_required
def listar_mi_modulo(request):
    # 1. Load fields for dynamic filters
    campos_activos = DS.obtener_campos_activos(FORM_NAME)

    # 2. Query registros
    registros = Registro.objects.filter(
        formulario=DS.obtener_formulario(FORM_NAME)
    ).order_by('-fecha_creacion')

    # 3. Bulk-load ALL values (never N+1)
    todos_valores = DS.cargar_valores_mapa(registros)

    # 4. Filter in Python using dicts
    registros = list(registros)
    if query:
        query_lower = query.lower()
        campos_texto = [c for c in campos_activos
                        if c.tipo in ('texto', 'email', 'telefono', 'textarea')]
        registros = [
            r for r in registros
            if any(query_lower in todos_valores.get(r.id, {}).get(c.nombre, '').lower()
                   for c in campos_texto)
        ]

    # 5. Wrap in wrapper objects
    items = [MiWrapper(r, todos_valores.get(r.id, {})) for r in registros]

    # 6. Paginate
    paginator = Paginator(items, per_page_int)
    pagina = paginator.get_page(request.GET.get('page'))

    # 7. Render
    return render(request, 'modulo/lista.html', {
        'items': pagina,
        'query_params': parametros_sin_pagina(request, ['page']),
        'per_page': per_page,
        'es_admin': es_administrador(request.user),
    })
```

## Create view pattern

The canonical example is `agregar_producto` (productos/views_dynamic.py:1101-1159).

```python
@login_required(login_url='login')
@admin_required
def agregar(request):
    formulario = DS.obtener_formulario(FORM_NAME)
    campos = formulario.campos.filter(activo=True).order_by('orden')
    errores = None
    valores_previos = {}

    if request.method == 'POST':
        valores = {}
        archivos = {}
        for campo in campos:
            if campo.tipo in Campo.TIPOS_ARCHIVO:
                archivo = request.FILES.get(f'campo_{campo.id}')
                if archivo:
                    archivos[campo.nombre] = archivo
            elif campo.tipo not in ('calculado',):
                valor = request.POST.get(f'campo_{campo.id}', '').strip()
                if valor:
                    valores[campo.nombre] = valor
                valores_previos[campo.id] = valor

        try:
            registro = DS.crear(FORM_NAME, valores, archivos, usuario=request.user)
            messages.success(request, 'Creado correctamente.')
            return redirect('lista_view_name')
        except ValidacionError as e:
            errores = e.errores
            messages.error(request, 'Corrige los errores.')

    return render(request, 'modulo/crear.html', {
        'formulario': formulario,
        'campos': campos,
        'errores': errores,
        'valores_previos': valores_previos,
    })
```

## Edit view pattern

The canonical example is `editar_producto` (productos/views_dynamic.py:1169-1248).

```python
@login_required(login_url='login')
@admin_required
def editar(request, registro_id):
    formulario = DS.obtener_formulario(FORM_NAME)
    campos = formulario.campos.filter(activo=True).order_by('orden')

    registro = get_object_or_404(
        Registro.objects.select_related('formulario'),
        id=registro_id, formulario=formulario
    )
    valores_actuales = DS.obtener_valores(registro)

    valores_previos = {}
    for campo in campos:
        valores_previos[campo.id] = valores_actuales.get(campo.nombre, '')

    if request.method == 'POST':
        valores = {}
        archivos = {}
        for campo in campos:
            if campo.tipo in Campo.TIPOS_ARCHIVO:
                archivo = request.FILES.get(f'campo_{campo.id}')
                if archivo:
                    archivos[campo.nombre] = archivo
            elif campo.tipo not in ('calculado',):
                valor = request.POST.get(f'campo_{campo.id}', '').strip()
                if valor:
                    valores[campo.nombre] = valor
                valores_previos[campo.id] = valor

        try:
            DS.actualizar(registro, valores, archivos, usuario=request.user)
            messages.success(request, 'Actualizado correctamente.')
            return redirect('lista_view_name')
        except ValidacionError as e:
            errores = e.errores

    return render(request, 'modulo/editar.html', {
        'registro': registro,
        'campos': campos,
        'errores': errores,
        'valores_previos': valores_previos,
    })
```

## Delete view pattern

The canonical example is `eliminar_producto` (productos/views_dynamic.py:1258-1322).

```python
@login_required(login_url='login')
@admin_required
def eliminar(request, registro_id):
    formulario = DS.obtener_formulario(FORM_NAME)
    registro = get_object_or_404(Registro, id=registro_id, formulario=formulario)
    valores = DS.obtener_valores(registro)
    wrapper = MiWrapper(registro, valores)

    if request.method == 'POST':
        if request.POST.get('confirmar') == 'si':
            if _tiene_referencias(registro_id):
                messages.error(request, 'No se puede eliminar: tiene referencias.')
            else:
                DS.eliminar(registro)
                messages.success(request, 'Eliminado.')
            return redirect('lista_view_name')

    return render(request, 'modulo/eliminar.html', {
        'item': wrapper,
    })
```

## Checklist

- [ ] View uses `DS.obtener_formulario()` to get the form
- [ ] List views use `DS.cargar_valores_mapa()` before the loop
- [ ] Filters applied in Python on the valores_map dict, not on DB
- [ ] Wrappers created inside list comprehensions
- [ ] `ValidacionError` caught in create/edit views
- [ ] `messages.error()` used for user feedback
- [ ] Pagination via `Paginator` + `obtener_por_pagina()`
- [ ] `@login_required` on all business views
- [ ] `@admin_required` on admin-only views

## Frequent errors

- **N+1 in list views**: Calling `DS.obtener_valor()` per record instead
  of `DS.cargar_valores_mapa()` upfront.
- **Not catching `ValidacionError`**: Causes 500 errors instead of showing
  validation messages to the user.
- **Forgetting `usuario=request.user`**: `DS.crear()` and `DS.actualizar()`
  require the user parameter for audit trail.
- **Hardcoded field IDs in POST**: Use `campo_{campo.id}` naming convention
  for form fields, matching the templates.
- **Missing `transaction.atomic()`**: When mixing `DS.crear()` and
  `DS.actualizar()` in the same view, wrap in `transaction.atomic()`.

## Reference files

| View | File | Lines |
|------|------|-------|
| listar_productos | productos/views_dynamic.py | 101-211 |
| agregar_producto | productos/views_dynamic.py | 1101-1159 |
| editar_producto | productos/views_dynamic.py | 1169-1248 |
| eliminar_producto | productos/views_dynamic.py | 1258-1322 |
| nueva_venta | ventas/views_dynamic.py | 177-300 |
| historial_ventas | ventas/views_dynamic.py | 426-492 |
| clientes | ventas/views_dynamic.py | 881-959 |
