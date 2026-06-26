---
name: create-wrapper
description: >-
  Creates a wrapper class that adapts Dynamic Forms EAV data to the interface
  expected by legacy Django templates. Based on DynamicProductWrapper,
  DynamicVentaWrapper, DynamicClienteWrapper, and DynamicMovimientoInventarioWrapper
  in apps/legacy/productos/wrappers.py.
license: MIT
compatibility: opencode
metadata:
  audience: developer
  module: wrappers
  real_files: apps/legacy/productos/wrappers.py
---

# create-wrapper

Creates a wrapper class that bridges Dynamic Forms EAV data to legacy
template interfaces. Each wrapper receives a `Registro` + `valores_dict`
and exposes attributes matching the legacy model field names.

## When to use

- A new dynamic form needs to render in legacy templates.
- An existing wrapper is missing attributes needed by a template.
- A template needs type-converted values (Decimal, int, datetime)
  instead of raw strings from ValorCampo.

## When NOT to use

- The template already uses `dynamic_forms_extras` template tags
  directly (no wrapper needed).
- The data is purely backend (no template rendering).

## Real project pattern

All wrappers live in `apps/legacy/productos/wrappers.py` (374 lines).
Four wrappers exist, each with the same constructor signature.

## Constructor pattern

Every wrapper receives `(registro, valores)` where `valores` comes from
`DS.cargar_valores_mapa()`:

```python
class DynamicMiWrapper:
    def __init__(self, registro, valores):
        self._registro = registro
        self._valores = valores or {}
        self.id = registro.id

        # Direct string values (with safe defaults)
        self.nombre = self._valores.get('nombre', '')

        # Type-converted values
        self.precio = _decimal(self._valores.get('precio', '0'))
        self.stock = _entero(self._valores.get('stock', '0'))
```

### Helper conversion functions (wrappers.py:24-37)

```python
def _decimal(valor, default=Decimal('0')):
    try:
        return Decimal(str(valor).replace(',', '.'))
    except (ValueError, TypeError, InvalidOperation):
        return default

def _entero(valor, default=0):
    try:
        return int(float(str(valor).replace(',', '.')))
    except (ValueError, TypeError):
        return default
```

## `@property` pattern

Use `@property` for computed/derived attributes:

```python
@property
def nombre_completo(self):
    return f'{self.nombre} {self.apellido}'.strip()

@property
def activo(self):
    return self._valores.get('activo', 'Sí') == 'Sí'
```

See `DynamicClienteWrapper.nombre_completo` (wrappers.py:366-367) and
`DynamicClienteWrapper.activo` (wrappers.py:370-371).

## Fallback/resolver pattern

When a wrapper needs related data (product from a venta), use a resolver
with fallback:

```python
self.producto = producto_wrapper or self._resolver_producto_fallback()

def _resolver_producto_fallback(self):
    """Fallback when related wrapper is not pre-resolved."""
    return SimpleNamespace(
        nombre=self._valores.get('producto_nombre', 'Producto desconocido'),
        categoria=SimpleNamespace(nombre=''),
        imagen_final_url='',
    )
```

See `DynamicVentaWrapper._resolver_producto_por_defecto` (wrappers.py:307-317)
and `DynamicMovimientoInventarioWrapper._resolver_producto_fallback`
(wrappers.py:240-254).

## Display method pattern

Emulate Django's `get_FOO_display()` for choice fields:

```python
def get_tipo_display(self):
    return _TIPO_DISPLAY.get(self.tipo, self.tipo.capitalize() if self.tipo else '')
```

See `DynamicMovimientoInventarioWrapper.get_tipo_display` (wrappers.py:224-227).

## Externally-set attributes pattern

Set attributes that are computed outside the wrapper after construction:

```python
# In wrapper constructor:
self.total_vendidos = 0  # Default, set externally
self.cantidad_ventas = 0

# In view code:
producto.total_vendidos = ventas_por_producto.get(registro.id, 0)
cliente.cantidad_ventas = len(ventas_del_cliente)
```

See `DynamicProductWrapper.__init__` line 96 and `detalle_cliente`
(ventas/views_dynamic.py:848-850).

## Checklist

- [ ] Constructor accepts `(registro, valores)` with optional `producto_wrapper`
- [ ] All string values use `.get('campo', default)` — never `['campo']`
- [ ] Numeric values converted with `_decimal()` / `_entero()`
- [ ] `@property` for computed attributes
- [ ] `SimpleNamespace` for related object fallbacks
- [ ] `get_FOO_display()` methods for choice fields with mapping dicts
- [ ] Template-expected attribute names match exactly (e.g., `nombre_completo`)
- [ ] Externally-set attributes initialized with safe defaults

## Frequent errors

- **Using `__getattr__` magic**: Hard to debug. Explicitly declare all
  attributes in `__init__`. See the existing wrappers.
- **Missing `SimpleNamespace` import**: Required for fallback objects.
  Import from `types`.
- **`KeyError` on missing values**: Always use `.get()` not `[]`.
- **Not handling comma as decimal separator**: Argentinian format uses `,`
  for decimals. Always use `.replace(',', '.')` before conversion.
- **Boolean stored as 'Sí'/'No'**: Cannot use `bool()`. Compare string:
  `self._valores.get('activo', 'Sí') == 'Sí'`.

## Reference files

| Wrapper | File | Lines |
|---------|------|-------|
| DynamicProductWrapper | wrappers.py | 45-130 |
| DynamicMovimientoInventarioWrapper | wrappers.py | 167-257 |
| DynamicVentaWrapper | wrappers.py | 260-320 |
| DynamicClienteWrapper | wrappers.py | 328-374 |
