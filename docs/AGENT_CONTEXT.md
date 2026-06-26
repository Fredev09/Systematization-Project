# Agent Context

This file provides persistent context for AI coding agents working on this project.

---

## Project Architecture

- **Django 5.1.15** monolithic application (no REST API, no SPA frontend).
- All rendering uses **Django Templates** with server-side logic.
- Two architectural layers coexist: **legacy Django models** and **Dynamic Forms EAV system**.
- The main URL configuration (`config/urls.py`) routes most endpoints to **dynamic views** (`views_dynamic.py`).
- **Wrappers** (`apps/legacy/productos/wrappers.py`) adapt EAV records to the interface expected by legacy templates.

## Important Conventions

### App Layout
```
apps/
  platform/   → Core infrastructure (dynamic_forms)
  legacy/     → Business modules being migrated (productos, ventas)
  shared/     → Cross-cutting modules (usuarios, configuracion, reportes)
```

### Naming
- `views_dynamic.py` — Dynamic Forms versions of views (prefixed or suffixed with `_dynamic` where applicable).
- `wrappers.py` — Adapter classes that wrap `Registro` + `ValorCampo` data.
- `hooks.py` — Post-create / post-update callbacks for Dynamic Forms.
- App labels in `INSTALLED_APPS` use dotted paths from `apps.*`.

### Code Patterns
- **DynamicService** is always imported as `DS`:
  ```python
  from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
  ```
- All services are static methods on `DynamicService` — no instantiation.
- Wrappers are constructed by passing `(registro, valores_dict)` where `valores_dict` comes from `DS.cargar_valores_mapa()`.
- Business logic that would live in model `save()` (e.g., stock decrement) goes in **hooks**.
- All form-level constants are in `services_dynamic.py` (e.g., `FORM_PRODUCTOS = 'Productos'`).

## Dynamic Forms Philosophy

- **Schema without migrations**: New fields are created as `Campo` rows, not database columns.
- **All values are text**: `ValorCampo.valor` is a `TextField`. Type conversion happens in Python.
- **Calculated fields in two passes**: Formulas evaluate after all normal fields are saved, enabling chaining.
- **Hooks for side effects**: Post-create/post-update logic lives in configurable Python callables, not model methods.
- **Wrappers for compatibility**: EAV data is adapted to legacy model interfaces so templates need no changes.

## Migration Philosophy

- **Incremental migration**: Legacy models remain in the codebase. Dynamic views coexist with legacy views.
- **Wrapper bridge**: Business modules can use Dynamic Forms data while legacy templates render it unchanged.
- **Hook-based replacement**: Model-level `save()` logic is replaced by `hook_post_crear` / `hook_post_actualizar`.
- **No data migration yet**: Legacy database tables still exist. There is no migration script to move data from legacy to Dynamic Forms.

## Compatibility Requirements

- All templates expect to receive objects with attribute-based access (e.g., `producto.nombre`, `producto.precio`). Wrappers must provide this.
- Templates use Django template filters like `|date`, `|time`, `formato_pesos` from `apps.legacy.ventas.templatetags.formatos`.
- All views return Django `HttpResponse` / `render` / `redirect` — not JSON (no DRF).
- URLs follow the pattern: `/module/action/<id>/` (e.g., `/productos/editar/42/`).

## General Development Workflow

1. Create/edit `Campo` definitions in the admin or via `sembrar_formularios_base` management command.
2. Implement business logic as hooks in `hooks.py` of the relevant app.
3. Create/update wrappers if templates need new attributes.
4. Use `DynamicService` methods (`filtrar`, `crear`, `actualizar`, `obtener_valores`, etc.) in views.
5. Bulk-load values with `DS.cargar_valores_mapa(registros)` for performance.

## Working Protocol

Regla permanente del proyecto. Cualquier agente que modifique el
proyecto debe seguir este protocolo de documentación.

### Obligaciones del agente

Al realizar cambios en el código, el agente DEBE:

1. **Actualizar `SESSION_LOG.md`** — Agregar una entrada cronológica
   con fecha, trabajo realizado, archivos modificados, decisiones
   importantes y próximo paso.
2. **Actualizar `TODO.md`** — Si el cambio completa, cancela o cambia
   el estado de alguna tarea listada, reflejarlo inmediatamente.
3. **Actualizar `MIGRATION_STATUS.md`** — Cuando se complete una
   migración de un módulo legacy a Dynamic Forms, actualizar las
   tablas de estado y las estimaciones correspondientes.
4. **Actualizar `DECISIONS.md`** — Cuando se tome una decisión
   arquitectónica importante (nuevo patrón, biblioteca, cambio de
   enfoque), agregar una entrada con la decisión, razón y estado.
5. **No modificar documentación que no corresponda al cambio**
   — Si el cambio no afecta el estado de una migración, no se debe
   modificar `MIGRATION_STATUS.md`.

### Secuencia recomendada

1. Leer `AGENT_CONTEXT.md`, `MIGRATION_STATUS.md`, `TODO.md`.
2. Realizar los cambios en el código.
3. Actualizar `SESSION_LOG.md`.
4. Actualizar `TODO.md` si corresponde.
5. Actualizar `MIGRATION_STATUS.md` si corresponde.
6. Actualizar `DECISIONS.md` si corresponde.

---

## Rules Every AI Agent Should Follow Before Modifying Code

1. **Read first**: Always read `services_dynamic.py`, `wrappers.py`, and the relevant `views_dynamic.py` before making changes to understand the existing patterns.
2. **No REST API**: Do not add Django REST Framework or JSON endpoints. This is a template-driven application.
3. **Preserve wrapper interface**: Do not change attribute names on wrappers without checking all templates that use them.
4. **Thread safety**: Hooks use thread-local storage for recursion protection. Do not break this mechanism.
5. **Transactions**: All `DS.crear()` and `DS.actualizar()` calls run inside `transaction.atomic()`. Hooks execute within that transaction. Do not remove atomicity.
6. **Pessimistic locking**: Stock-sensitive operations must use `select_for_update()` to prevent race conditions.
7. **Legacy code preservation**: Do not delete legacy models, views, or templates. The migration is incremental.
8. **No invented features**: Only implement what is explicitly requested or documented. Do not add speculative functionality.
9. **Follow existing naming**: Use Spanish for user-facing strings, English for code identifiers (as existing code does).
10. **Check base settings**: Read `config/settings/base.py` before adding new dependencies or configurations.
