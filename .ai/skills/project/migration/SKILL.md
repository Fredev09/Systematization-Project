---
name: migration
description: >-
  Specialist in Legacy-to-Dynamic-Forms migration. Follows the established
  pattern used to migrate Ventas and Dashboard. Covers wrappers, hooks,
  URL routing, and view conversion for the Tonjeo project.
license: MIT
compatibility: opencode
metadata:
  audience: developer
  module: migration
---

# Migration Skill

## Inspired by

This skill follows the structure defined in the [Anthropic Agent Skills
specification](https://github.com/anthropics/skills) and the
[opencode-skills](https://github.com/malhashemi/opencode-skills) community
repository.

---

## Migration Pattern

The project migrates legacy Django models to Dynamic Forms incrementally.
Legacy models remain in the codebase — never delete them. The pattern
consists of 5 steps:

---

## Step-by-Step Process

### Step 1: Create the Dynamic Form

Ensure the form exists in the database. Forms are seeded via the
`sembrar_formularios_base` management command in
`apps/platform/dynamic_forms/management/commands/`.

Define a form constant in `services_dynamic.py`:

```python
FORM_MI_MODULO = 'MiModulo'
```

Add the corresponding `Campo` definitions matching the legacy model fields.

### Step 2: Create the Wrapper

In `apps/legacy/<modulo>/wrappers.py`, create a wrapper class that adapts
EAV data to the interface expected by existing templates.

```python
class DynamicMiModuloWrapper:
    def __init__(self, registro, valores_dict):
        self.registro = registro
        self.valores = valores_dict

    @property
    def nombre(self):
        return self.valores.get('nombre', '')
```

**Rules:**
- Constructor receives `(registro, valores_dict)`
- Use `@property` for computed fields
- Provide safe defaults for missing values
- Match attribute names to legacy model field names exactly
- Handle type conversion (string → Decimal, string → int, etc.)

### Step 3: Create Dynamic Views

In `apps/legacy/<modulo>/views_dynamic.py`, implement:

- **List view** — Use `DS.filtrar()` + `DS.cargar_valores_mapa()` + wrappers
- **Create view** — Build `valores` dict from `request.POST`, call `DS.crear()`
- **Edit view** — Load values via `DS.obtener_valores()`, call `DS.actualizar()`
- **Delete view** — Call `DS.eliminar()` with `ProtectedError` handling

**Performance rule:** Always use `DS.cargar_valores_mapa(registros)` for
list views to avoid N+1 queries.

### Step 4: Add Business Logic Hook

If the legacy model has side effects in `save()`, move them to a hook in
`apps/legacy/<modulo>/hooks.py`:

```python
def post_crear_mi_modulo(registro):
    # Business logic here
    pass
```

**Hook rules:**
- Signature: `def mi_hook(registro: Registro) -> None`
- Runs inside `transaction.atomic()` with the parent create/update
- Use `select_for_update()` for stock-sensitive operations
- Recursion protection via thread-local is automatic

Register the hook on the form via management command.

### Step 5: Update URL Routing

In `config/urls.py`, replace legacy view imports with dynamic ones:

```python
# Before (legacy)
from apps.legacy.productos.views import listar_productos

# After (dynamic)
from apps.legacy.productos.views_dynamic import listar_productos
```

Keep legacy imports as fallback (commented out or conditional).

---

## Files to Update

After completing a migration, update:

| File | What to update |
|------|----------------|
| `docs/MIGRATION_STATUS.md` | Status tables and estimates |
| `docs/SESSION_LOG.md` | New entry with work done |
| `docs/TODO.md` | Mark task as completed |
| `docs/DECISIONS.md` | If new architectural decision was made |

---

## Reference: Completed Migrations

| Module | Files | Pattern Used |
|--------|-------|-------------|
| Productos CRUD | `views_dynamic.py`, `wrappers.py` | Full CRUD + wrappers |
| Ventas CRUD | `views_dynamic.py`, `hooks.py` | Full CRUD + hook |
| Clientes CRUD | `views_dynamic.py` | Full CRUD |
| Inventory | `views_dynamic.py`, `hooks.py` | Movements via hooks |

---

## When to Use This Skill

- Migrating a new legacy module to Dynamic Forms
- Verifying a migration is complete
- Debugging a partial migration
- Adding wrapper support for an existing dynamic form

---

## Related Files

| File | Purpose |
|------|---------|
| `docs/MIGRATION_STATUS.md` | Current migration state |
| `docs/ROADMAP.md` | Pending migration items |
| `config/urls.py` | URL routing (legacy vs dynamic) |
| `apps/legacy/productos/wrappers.py` | Reference wrapper implementation |
| `apps/legacy/ventas/hooks.py` | Reference hook implementation |
