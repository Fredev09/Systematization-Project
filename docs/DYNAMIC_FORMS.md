# Dynamic Forms

## Overview

Dynamic Forms implements an **Entity-Attribute-Value (EAV)** pattern that allows form schemas to be defined at runtime through database records rather than Django model migrations.

## Data Models

### Formulario

Represents a form type (equivalent to a database table).

| Field | Type | Purpose |
|-------|------|---------|
| `nombre` | CharField | Name of the form (e.g., `"Productos"`, `"Ventas"`) |
| `descripcion` | TextField | Human-readable description |
| `fecha_creacion` | DateTimeField | Auto-set on creation |
| `activo` | BooleanField | Soft-disable the form |
| `creado_por` | FK → User | Who created it |
| `hook_post_crear` | TextField | Python dotted path to post-create function |
| `hook_post_actualizar` | TextField | Python dotted path to post-update function |
| `validacion_personalizada` | TextField | Python dotted path to custom validation function |

### Campo

Represents a field/attribute within a form (equivalent to a table column).

| Field | Type | Purpose |
|-------|------|---------|
| `formulario` | FK → Formulario | Parent form |
| `nombre` | CharField | Field name (e.g., `"precio"`, `"stock"`) |
| `tipo` | ChoiceField | One of 13 types (see below) |
| `obligatorio` | BooleanField | Required field |
| `orden` | IntegerField | Display order |
| `opciones` | JSONField | Options for `lista` type fields |
| `activo` | BooleanField | Soft-delete without losing data |
| `unico` | BooleanField | Unique constraint (enforced in Python) |
| `formulario_destino` | FK → Formulario | Target form for `relacion` type |
| `formula` | TextField | Mathematical expression for `calculado` type |

**Field types**: `texto`, `numero`, `fecha`, `booleano`, `lista`, `email`, `url`, `telefono`, `textarea`, `imagen`, `archivo`, `relacion`, `calculado`.

**Special groupings**:
- `TIPOS_ARCHIVO = {'imagen', 'archivo'}` — File upload fields
- `TIPOS_SOLO_LECTURA = {'calculado'}` — Read-only fields
- `TIPOS_RELACION = {'relacion'}` — Cross-form references

### Registro

Represents a concrete record/row within a form.

| Field | Type | Purpose |
|-------|------|---------|
| `formulario` | FK → Formulario | Parent form |
| `fecha_creacion` | DateTimeField | Auto-set |
| `fecha_actualizacion` | DateTimeField | Updated on save |
| `usuario` | FK → User | Who created the record |

### ValorCampo

Stores the actual value for a field in a record (the "Value" in EAV).

| Field | Type | Purpose |
|-------|------|---------|
| `registro` | FK → Registro | Parent record |
| `campo` | FK → Campo | Field definition |
| `valor` | TextField | The value (always stored as text) |

**Unique constraint**: `(registro, campo)` — one value per field per record.

## DynamicService

Located in `apps/platform/dynamic_forms/services_dynamic.py`. All methods are static. Typical import:

```python
from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
```

### Responsibilities

1. **CRUD abstraction**: Create, read, update, delete EAV records without exposing the underlying `Registro`/`ValorCampo` model details.
2. **Validation pipeline**: Runs required-field, type, uniqueness, and custom validators before persisting.
3. **Formula evaluation**: Evaluates `calculado` fields in a second pass after normal field save (supports chaining).
4. **Hook execution**: Calls `hook_post_crear` / `hook_post_actualizar` after save, within the same transaction.
5. **File handling**: Saves uploaded images/files to `MEDIA_ROOT/dynamic_uploads/` for `imagen`/`archivo` fields.
6. **Aggregations**: Provides `sumar()`, `contar()`, `top()` for dashboard/reporting queries (aggregates in Python).

### Key Methods

| Method | Description |
|--------|-------------|
| `crear(nombre_form, valores, usuario, usar_select_for_update, archivos)` | Create record with validation + hooks |
| `actualizar(registro, valores, usuario, usar_select_for_update, archivos)` | Update record with validation + hooks |
| `eliminar(registro)` | Delete record and its values |
| `filtrar(nombre_form, **filtros)` | Filter records by field values |
| `buscar(nombre_form, texto, campos)` | Text search across fields |
| `obtener_valor(registro, nombre_campo)` | Get single value |
| `obtener_valores(registro)` | Get all values as dict |
| `cargar_valores_mapa(registros)` | Bulk-load values for multiple records |
| `sumar(nombre_form, campo, **filtros)` | Sum numeric field values |
| `contar(nombre_form, **filtros)` | Count matching records |
| `top(nombre_form, valor, agrupador, limite)` | Top N aggregation |
| `validar_completo(form, dict)` | Run all validations |

## Wrapper Responsibilities

Wrappers live in `apps/legacy/productos/wrappers.py`. They are **not** part of the Dynamic Forms platform — they are an adapter layer in the legacy apps.

Each wrapper:
1. Receives a `Registro` instance and a `dict` of `{campo_nombre: valor}` (from `DS.cargar_valores_mapa()`).
2. Exposes attributes with the same names as the legacy Django model (e.g., `.nombre`, `.precio`, `.stock`).
3. Handles type conversion (string → Decimal, string → int) with safe defaults on failure.
4. Provides fallback values for missing fields.
5. Emulates Django model methods like `get_tipo_display()`, `get_motivo_display()`.

**Available wrappers**:
- `DynamicProductWrapper` — used in product listing, inventory, dashboard
- `DynamicVentaWrapper` — used in sales history, export
- `DynamicMovimientoInventarioWrapper` — used in inventory history
- `DynamicClienteWrapper` — used in client listing, detail

## Validation Flow

```
DS.crear() / DS.actualizar()
    │
    ├── 1. validar_campos_obligatorios()
    │       Checks every Campo with obligatorio=True has a non-empty value
    │
    ├── 2. validar_tipos()
    │       Delegates to validators._validar_valor_campo() per type
    │
    ├── 3. validar_unicidad()
    │       For fields with unico=True, checks no duplicate exists
    │
    ├── 4. ejecutar_validacion_personalizada()
    │       Calls the function at Formulario.validacion_personalizada path
    │
    └── If any validation fails → raises ValidacionError with all errors
```

## Formula Fields

- Defined on `Campo` with `tipo='calculado'` and a `formula` string.
- Formulas support: numbers, field names (by name), operators `+`, `-`, `*`, `/`, and parentheses.
- Example: `"precio_unitario * cantidad"` → evaluated as `Decimal(precio_unitario) * Decimal(cantidad)`.
- **Two-pass evaluation**: First pass saves all normal fields; second pass evaluates formulas sequentially, updating the `valores_guardados` dict after each calculation. This enables chaining:
  1. `subtotal = precio_unitario * cantidad`
  2. `total = subtotal - descuento`
- Formula token values are resolved from the `valores_guardados` dict by field name.
- Evaluated via `_evaluar_formula()` in `apps/platform/dynamic_forms/services.py`.

## Hooks

Hooks are Python callables configured on `Formulario` as dotted paths:

```python
Formulario.hook_post_crear = "apps.legacy.ventas.hooks.post_crear_venta"
Formulario.hook_post_actualizar = "apps.legacy.ventas.hooks.post_actualizar_venta"
```

### Execution

- Called after `DS.crear()` / `DS.actualizar()` within the same `transaction.atomic()` block.
- If a hook raises, the entire transaction rolls back (including the record creation).
- Signature: `def mi_hook(registro: Registro) -> None`
- **Recursion protection**: Uses `threading.local()` to detect if a hook is already executing in the current thread. If a hook calls `DS.crear()` which tries to execute the same hook, `HookRecursivoError` is raised.

### Implemented Hook

**`post_crear_venta`** (`apps/legacy/ventas/hooks.py`):
1. Reads `producto`, `cantidad`, `precio_unitario` from the sale record.
2. Locks the product `Registro` with `select_for_update()`.
3. Validates sufficient stock.
4. Decrements product stock via `ValorCampo.update_or_create()`.
5. Creates a `MovimientosInventario` record via `DS.crear()`.
6. If `precio_unitario` was empty, fetches it from the product and saves it retroactively.

## Dynamic Menus

Dynamic menus are **not implemented** in the current codebase. Navigation is static, defined in templates.

## How Business Modules Interact with Dynamic Forms

```
Business Module (e.g., productos/ventas)
    │
    ├── Views (views_dynamic.py)
    │   ├── Receive HTTP request
    │   ├── Call DS methods for CRUD
    │   ├── Create wrappers for template data
    │   └── Render template
    │
    ├── Wrappers (wrappers.py)
    │   ├── Receive (registro, valores_dict)
    │   └── Expose attributes matching legacy model interface
    │
    ├── Hooks (hooks.py)
    │   ├── Configured on Formulario via management command
    │   └── Execute business logic (stock, audit, etc.)
    │
    └── Templates (templates/*/)
        ├── Access wrapper attributes as if they were Django models
        └── Use same template tags/filters as legacy templates
```

### Predefined Forms

| Form Name | Constant | Fields | Used By |
|-----------|----------|--------|---------|
| `Productos` | `FORM_PRODUCTOS` | nombre, precio, stock, categoria, descripcion, sku, talla, color, imagen, imagen_url, stock_minimo, activo | product CRUD, inventory |
| `Clientes` | `FORM_CLIENTES` | documento, nombre, apellido, correo, telefono, direccion, activo | client CRUD |
| `Ventas` | `FORM_VENTAS` | producto, cantidad, cliente, subtotal, precio_unitario, descuento, total, observacion | sales, dashboard |
| `MovimientosInventario` | `FORM_MOVIMIENTOS_INVENTARIO` | producto, tipo, cantidad, motivo, stock_anterior, stock_nuevo, observacion | stock history |
