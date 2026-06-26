---
name: migrate-module
description: >-
  Migrates a legacy Django module to Dynamic Forms following the exact pattern
  used for Ventas and Dashboard. Covers wrappers, hooks, dynamic views, URL
  routing, and compatibility with existing templates. Use when moving a module
  from legacy models to EAV.
license: MIT
compatibility: opencode
metadata:
  audience: developer
  module: migration
  real_files: apps/legacy/ventas/views_dynamic.py, apps/legacy/ventas/hooks.py
---

# migrate-module

Migrates a legacy Django model module to Dynamic Forms EAV, following the
real pattern used in the Ventas and Dashboard migrations.

## When to use

- A legacy Django model still has active views in `config/urls.py`.
- A new business module needs to be created using Dynamic Forms.
- A partially migrated module (like Categories) needs completion.

## When NOT to use

- The module needs database-level constraints (FOREIGN KEY, UNIQUE).
- The module handles high-frequency writes (>1000 writes/min) where EAV
  overhead is prohibitive.
- The data needs complex SQL reporting that cannot be done in Python.

## Real project pattern

The Ventas migration (`apps/legacy/ventas/views_dynamic.py`) and Dashboard
migration (`apps/shared/reportes/views.py:obtener_datos_reportes_dinamico`)
established this pattern:

```
legacy module              dynamic module
┌────────────────┐        ┌────────────────────┐
│ models.py       │  →    │ (no models needed) │
│ views.py        │  →    │ views_dynamic.py   │
│ (no wrappers)   │  →    │ wrappers.py        │
│ (no hooks)      │  →    │ hooks.py (optional)│
│ urls.py (legacy)│  →    │ config/urls.py     │
└────────────────┘        └────────────────────┘
```

## Step-by-step

### 1. Define the form constant

In `services_dynamic.py`, add a form constant:

```python
FORM_MI_MODULO = 'MiModulo'
```

### 2. Create the wrapper

In `apps/legacy/<modulo>/wrappers.py`, create a class that emulates the
legacy model interface. See `DynamicClienteWrapper` (wrappers.py:328-374)
for the simplest example.

**Pattern** (from DynamicClienteWrapper):

```python
class DynamicMiModuloWrapper:
    def __init__(self, registro, valores):
        self._registro = registro
        self._valores = valores or {}
        self.id = registro.id
        self.nombre = self._valores.get('nombre', '')
        self.campo_decimal = _decimal(self._valores.get('campo_decimal', '0'))

    @property
    def nombre_completo(self):
        return f'{self.nombre} {self.apellido}'.strip()
```

### 3. Create the hook (if side effects exist)

If the legacy model's `save()` had side effects (stock decrement, audit
trails), move them to a hook. See `apps/legacy/ventas/hooks.py`.

**Pattern** (from post_crear_venta):
```python
def post_crear_mi_modulo(registro):
    with transaction.atomic():
        # 1. Read values from the registro
        valores = DS.obtener_valores(registro)
        campo_valor = valores.get('campo', '')

        # 2. Lock related records
        producto = Registro.objects.select_for_update().get(id=prod_id)

        # 3. Update via dynamic service
        DS.actualizar(producto, {'stock': str(stock_nuevo)}, usuario=None)

        # 4. Create audit trail
        DS.crear('FORM_AUDITORIA', {...}, usuario=None)
```

Register the hook on the form using `asignar_hook_ventas` as reference.

### 4. Create dynamic views

In `apps/legacy/<modulo>/views_dynamic.py`, implement CRUD views:

**List view pattern** (from listar_productos, historial_ventas):
```python
@login_required(login_url='login')
def listar_mi_modulo(request):
    form = DS.obtener_formulario(FORM_MI_MODULO)
    registros = Registro.objects.filter(formulario=form).order_by('-fecha_creacion')
    valores_map = DS.cargar_valores_mapa(registros)

    # Apply filters in Python
    registros_filtrados = [r for r in registros if ...]

    # Wrap
    items = [DynamicMiModuloWrapper(r, valores_map.get(r.id, {}))
             for r in registros_filtrados]

    # Paginate
    paginator = Paginator(items, per_page_int)
    pagina = paginator.get_page(request.GET.get('page'))

    return render(request, 'modulo/template.html', {...})
```

**Create view pattern** (from agregar_producto, nueva_venta):
```python
if request.method == 'POST':
    valores = {}
    for campo in campos:
        valor = request.POST.get(f'campo_{campo.id}', '').strip()
        if valor:
            valores[campo.nombre] = valor

    try:
        registro = DS.crear(FORM_MI_MODULO, valores, usuario=request.user)
        messages.success(request, 'Creado correctamente.')
        return redirect('mi_modulo_lista')
    except ValidacionError as e:
        errores = e.errores
```

**Edit view pattern** (from editar_producto):
```python
registro = get_object_or_404(Registro, id=id, formulario=form)
valores_actuales = DS.obtener_valores(registro)

if request.method == 'POST':
    valores = {campo.nombre: request.POST.get(f'campo_{campo.id}', '') ...}
    try:
        DS.actualizar(registro, valores, usuario=request.user)
        return redirect('mi_modulo_lista')
    except ValidacionError as e:
        errores = e.errores
```

**Delete view pattern** (from eliminar_producto):
```python
if request.method == 'POST':
    if _tiene_relaciones_asociadas(registro_id):
        messages.error(request, 'Tiene registros asociados.')
    else:
        DS.eliminar(registro)
        messages.success(request, 'Eliminado.')
    return redirect('mi_modulo_lista')
```

### 5. Update URL routing

In `config/urls.py`, replace legacy view imports:

```python
# Replace
from apps.legacy.modulo.views import listar_modulo
# With
from apps.legacy.modulo.views_dynamic import listar_modulo
```

## Checklist

- [ ] Form constant defined in `services_dynamic.py`
- [ ] Wrapper created with `__init__(self, registro, valores)` signature
- [ ] Wrapper provides attribute names matching legacy model field names
- [ ] Type conversion done in wrapper (`_decimal()`, `_entero()`)
- [ ] Safe defaults for missing values (empty string, `Decimal('0')`)
- [ ] Hook created if legacy `save()` had side effects
- [ ] `views_dynamic.py` created with list/create/edit/delete views
- [ ] `DS.cargar_valores_mapa()` used for bulk reads
- [ ] `config/urls.py` pointing to dynamic views
- [ ] Legacy views preserved (no deletion)

## Frequent errors found during migration

- **Missing safe defaults**: Wrappers crash when a new field doesn't exist
  in older registros. Always use `.get('campo', default)`.
- **N+1 in list views**: Iterating registros and calling `DS.obtener_valor()`
  per row. Always use `DS.cargar_valores_mapa()`. See `listar_productos`
  (views_dynamic.py:123).
- **Forgetting to preserve legacy views**: Legacy views stay in the codebase
  as fallback. Never delete them.
- **Not handling `ValidacionError`**: `DS.crear()` and `DS.actualizar()`
  raise `ValidacionError` on validation failure. Always catch it and display
  errors to the user via `messages.error()`.
- **Hardcoded form names**: Always use the constants (`FORM_PRODUCTOS`, etc.)
  instead of string literals.

## Reference files

| File | Lines | Pattern |
|------|-------|---------|
| `apps/legacy/ventas/views_dynamic.py` | 1-1107 | Full ventas migration |
| `apps/legacy/productos/views_dynamic.py` | 1-1362 | Full productos migration |
| `apps/legacy/ventas/hooks.py` | 23-191 | Hook pattern |
| `apps/legacy/productos/wrappers.py` | 45-374 | All wrapper patterns |
| `apps/shared/reportes/views.py` | 433-801 | Dashboard data migration |
