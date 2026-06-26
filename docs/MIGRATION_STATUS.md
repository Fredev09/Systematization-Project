# Migration Status

This document tracks the migration progress from legacy Django models to the Dynamic Forms EAV system.

## Overview

The project is mid-transition. Both legacy Django models and the Dynamic Forms EAV system coexist. The main `config/urls.py` routes most business endpoints to dynamic views (`views_dynamic.py`), but legacy views, models, and templates remain in the codebase.

## Fully Migrated Modules

These modules use Dynamic Forms for their primary data operations:

| Module | Details |
|--------|---------|
| **Productos (CRUD)** | `apps/legacy/productos/views_dynamic.py` handles list, create, edit, delete via `DynamicService`. Product URLs in `config/urls.py` point to dynamic views. Wrappers bridge data to legacy templates. |
| **Ventas (CRUD)** | `apps/legacy/ventas/views_dynamic.py` handles new sale, history, export via `DynamicService`. Sale URLs point to dynamic views. Stock decrement via hook (`post_crear_venta`). |
| **Clientes** | Client CRUD uses the `Clientes` dynamic form. Views in `apps/legacy/ventas/views_dynamic.py`. |
| **Inventory (dynamic)** | `apps/legacy/productos/views_dynamic.py` provides inventory view, stock history, Excel export using Dynamic Forms data. |
| **Reports** | `apps/shared/reportes/views.py` — all 5 views (main, Excel, 3 PDFs) use Dynamic Forms via `obtener_datos_reportes_dinamico()` and `_envolver_ventas()`. Legacy code (`obtener_datos_reportes()`, `ventas_filtradas_reportes()`, `construir_grafica_meses()`) removed. |

## Partially Migrated Modules

| Module | Details |
|--------|---------|
| **Products — Categories** | Category CRUD still uses legacy views (`apps.legacy.productos.views.agregar_categoria`, `apps.legacy.productos.views.crear_categoria`). No dynamic analog exists. Categories are a separate legacy model (`Categoria`), not a dynamic form. |
| **Clients — State toggle** | `cambiar_estado_cliente` uses dynamic views but relies on the `activo` field convention (`'Sí'` / `'No'`) as a string. |

## Legacy Modules

These modules exist as Django models but are **not actively used** by the main URL configuration:

| Module | Files | Purpose |
|--------|-------|---------|
| `apps.legacy.productos.models.Producto` | `apps/legacy/productos/models.py:34-54` | Legacy product model |
| `apps.legacy.productos.models.Categoria` | `apps/legacy/productos/models.py:30-31` | Legacy category model |
| `apps.legacy.productos.models.MovimientoInventario` | `apps/legacy/productos/models.py:57-76` | Legacy inventory movement model |
| `apps.legacy.ventas.models.Venta` | `apps/legacy/ventas/models.py:40-88` | Legacy sales model (with custom `save()`) |
| `apps.legacy.ventas.models.Cliente` | `apps/legacy/ventas/models.py:20-37` | Legacy client model |
| `apps.legacy.productos.views` (legacy views) | `apps/legacy/productos/views.py` | Legacy product views (not in main urls) |
| `apps.legacy.ventas.views` (legacy views) | `apps/legacy/ventas/views.py` | Legacy sales views (not in main urls) |

## Remaining Migration Work

### Data Migration
- No migration script exists to copy data from legacy tables (`Producto`, `Venta`, `Cliente`, `MovimientoInventario`) to Dynamic Forms.
- Legacy database tables remain populated. The dynamic forms are populated independently via the `crear_datos_prueba` management command.

### Categories
- `Categoria` is a legacy model without a Dynamic Forms equivalent. Categories are stored as plain text in the `lista` type field `categoria` on the Productos form.
- Legacy category CRUD views are still wired (`agregar_categoria`, `crear_categoria` in `config/urls.py`).
- The Reports module no longer depends on legacy `Categoria` — uses dynamic form field options instead.

### Reports — Complete
- All 5 views (`reportes/`, Excel, 3 PDFs) use Dynamic Forms via `obtener_datos_reportes_dinamico()` and `_envolver_ventas()`.
- Legacy code removed: `obtener_datos_reportes()`, `ventas_filtradas_reportes()`, `construir_grafica_meses()`, legacy imports (`Venta`, `Producto`, `Cliente`, `Categoria`, `Sum`).
- Migration status: **100%**.

### Legacy Models Cleanup
- The legacy models and their views/templates can be removed only after:
  1. Data migration from legacy to Dynamic Forms is complete.
  2. All templates are verified to work with wrappers.
  3. Category functionality is migrated.

## Completion Estimates

These estimates are based on code inspection, not metrics:

| Area | Estimate | Basis |
|------|----------|-------|
| Product CRUD | ~90% migrated | Dynamic views handle main CRUD; categories remain legacy |
| Sales CRUD | ~90% migrated | Dynamic views + hooks handle sales flow |
| Clients CRUD | ~85% migrated | Dynamic form used; some edge cases remain |
| Inventory | ~80% migrated | Dynamic views handle movements; stock operations via hooks |
| Categories | ~0% migrated | No dynamic equivalent |
| Reports | **100% migrated** | All views on Dynamic Forms; legacy code removed |
| Data Migration | ~0% migrated | No migration script exists |
| Legacy model cleanup | ~0% | All legacy models and views still present |
