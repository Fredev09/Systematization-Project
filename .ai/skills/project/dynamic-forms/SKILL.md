---
name: dynamic-forms
description: >-
  Specialist in the Dynamic Forms EAV architecture. Knows DynamicService,
  Registro, ValorCampo, wrappers, hooks, formulas, validators, and project
  conventions for the Tonjeo commercial management system.
license: MIT
compatibility: opencode
metadata:
  audience: developer
  module: platform
---

# Dynamic Forms Skill

## Inspired by

This skill follows the structure defined in the [Anthropic Agent Skills
specification](https://github.com/anthropics/skills) and the
[opencode-skills](https://github.com/malhashemi/opencode-skills) community
repository.

---

## Overview

Tonjeo uses an **Entity-Attribute-Value (EAV)** pattern for its Dynamic Forms
system. Instead of fixed database tables like `Producto(id, nombre, precio)`,
the schema is defined at runtime via four models: `Formulario`, `Campo`,
`Registro`, and `ValorCampo`.

The core service layer is `DynamicService` (always imported as `DS`), located
at `apps/platform/dynamic_forms/services_dynamic.py`. All methods are static.

---

## Key Concepts

### DynamicService (`DS`)

Central CRUD abstraction. Never instantiate — call static methods directly:

```python
from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
```

**Important methods:**

| Method | Purpose |
|--------|---------|
| `crear(nombre_form, valores, usuario)` | Create record with validation + hooks |
| `actualizar(registro, valores, usuario)` | Update record with validation + hooks |
| `eliminar(registro)` | Delete record and its values |
| `filtrar(nombre_form, **filtros)` | Filter records by field values |
| `buscar(nombre_form, texto, campos)` | Text search across fields |
| `cargar_valores_mapa(registros)` | Bulk-load values for multiple records |
| `sumar(nombre_form, campo, **filtros)` | Sum numeric field values |
| `contar(nombre_form, **filtros)` | Count matching records |
| `top(nombre_form, valor, agrupador, limite)` | Top N aggregation |
| `validar_completo(form, dict)` | Run all validations |

### Registro

Represents a concrete record/row. Fields:
- `formulario` (FK → Formulario)
- `fecha_creacion`, `fecha_actualizacion` (DateTime)
- `usuario` (FK → User)

### ValorCampo

Stores the actual value for a field. All values are `TextField` — type
conversion happens in Python. Unique constraint: `(registro, campo)`.

### Wrappers

Adapter classes in `apps/legacy/productos/wrappers.py` that convert EAV data
to legacy template interfaces. Receive `(registro, valores_dict)`.

**Existing wrappers:**
- `DynamicProductWrapper` — emulates legacy `Producto`
- `DynamicVentaWrapper` — emulates legacy `Venta`
- `DynamicMovimientoInventarioWrapper` — emulates legacy `MovimientoInventario`
- `DynamicClienteWrapper` — emulates legacy `Cliente`

### Hooks

Python callables configured on `Formulario.hook_post_crear` and
`Formulario.hook_post_actualizar`. Execute within `transaction.atomic()`.

**Implemented:** `apps.legacy.ventas.hooks.post_crear_venta` (stock decrement).
Recursion protection via `threading.local()`.

### Formulas

Calculated fields (`tipo='calculado'`) evaluated in a second pass after
normal fields. Support chaining: `subtotal = precio_unitario * cantidad`
→ `total = subtotal - descuento`.

### Validators

Located in `apps/platform/dynamic_forms/validators.py`. Types:
`numero`, `fecha`, `booleano`, `lista`, `email`, `url`, `telefono`,
`relacion`, `calculado`.

---

## Project Conventions

1. Form name constants in `services_dynamic.py`:
   `FORM_PRODUCTOS`, `FORM_CLIENTES`, `FORM_VENTAS`, `FORM_MOVIMIENTOS_INVENTARIO`
2. `DS.cargar_valores_mapa()` for bulk reads (never N+1)
3. `select_for_update()` for stock operations
4. Wrappers handle type conversion, not views or templates
5. Two-pass save: normal fields first, calculated fields second
6. Booleans stored as `'Sí'` / `'No'`
7. Relations store target `Registro.id` as string

---

## When to Use This Skill

- Creating or modifying a `Campo` definition
- Implementing business logic in a hook
- Creating or updating a wrapper
- Debugging EAV query performance
- Adding a new dynamic form
- Understanding the value flow (view → DS → Registro/ValorCampo → wrapper → template)

---

## Related Files

| File | Purpose |
|------|---------|
| `apps/platform/dynamic_forms/services_dynamic.py` | Core service layer |
| `apps/platform/dynamic_forms/models.py` | Formulario, Campo, Registro, ValorCampo |
| `apps/platform/dynamic_forms/validators.py` | Type validators |
| `apps/legacy/productos/wrappers.py` | Adapter wrappers |
| `apps/legacy/ventas/hooks.py` | Business hooks |
| `docs/DYNAMIC_FORMS.md` | Full documentation |
| `docs/EAV_LIMITACIONES.md` | Known limitations |
