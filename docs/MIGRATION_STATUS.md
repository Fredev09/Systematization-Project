# Migration Status

This document tracks the migration progress from legacy Django models to the Dynamic Forms EAV system.

## Overview

The project is mid-transition. Both legacy Django models and the Dynamic Forms EAV system coexist. The main `config/urls.py` routes all business endpoints to dynamic views (`views_dynamic.py`), but legacy model definitions, admin registrations, migration files, and tests remain in the codebase.

## Fully Migrated Modules

These modules use Dynamic Forms for their primary data operations:

| Module | Details |
|--------|---------|
| **Productos (CRUD)** | `apps/legacy/productos/views_dynamic.py` handles list, create, edit, delete via `DynamicService`. Product URLs in `config/urls.py` point to dynamic views. Wrappers bridge data to legacy templates. |
| **Catálogo Público** | `catalogo_publico` migrado a `views_dynamic.py` usando `DynamicService` + `DynamicProductWrapper`. Filtro `mostrar_agotados_catalogo`, orden alfabético, `telefono_whatsapp` replicados. |
| **Ventas (CRUD)** | `apps/legacy/ventas/views_dynamic.py` handles new sale, history, export via `DynamicService`. Sale URLs point to dynamic views. Stock decrement via hook (`post_crear_venta`). |
| **Clientes** | Client CRUD uses the `Clientes` dynamic form. Views in `apps/legacy/ventas/views_dynamic.py`. |
| **Inventory (dynamic)** | `apps/legacy/productos/views_dynamic.py` provides inventory view, stock history, Excel export using Dynamic Forms data. |
| **Reports** | All 5 views (main, Excel, 3 PDFs) use Dynamic Forms via `obtener_datos_reportes_dinamico()` and `_envolver_ventas()`. Legacy code removed. |

## Partially Migrated Modules

| Module | Details |
|--------|---------|
| **Products — Categories** | Category management migrado a opciones dinámicas del campo `categoria` (tipo lista) en el formulario Productos. Vistas `agregar_categoria` y `crear_categoria` migradas a `views_dynamic.py`. Modelo `Categoria` legacy ya no tiene vistas activas. |
| **Clients — State toggle** | `cambiar_estado_cliente` uses dynamic views but relies on the `activo` field convention (`'Sí'` / `'No'`) as a string. |

## Removed Modules (eliminated in Fase 3)

| Module | Files | Purpose |
|--------|-------|---------|
| `apps.legacy.ventas.models.Venta` | Eliminado | Legacy sales model — table `ventas_venta` dropped (migration 0009) |
| `apps.legacy.ventas.models.Cliente` | Eliminado | Legacy client model — table `ventas_cliente` dropped (migration 0009) |
| `apps.legacy.ventas.admin` | Eliminado | VentaAdmin + ClienteAdmin |
| `apps.legacy.ventas.views` | Eliminado | Legacy sales views (668 lines, ALL orphan) |
| `apps.legacy.ventas.urls` | Eliminado | Not included in root urlconf |
| `apps.legacy.ventas.tests` | Eliminado | VentaModelTests |

**Files preserved**: `views_dynamic.py` (1107 lines, active), `hooks.py` (active), `templatetags/formatos.py` (active), `migrations/` (9 files, migration chain).

## Removed Modules (eliminated in Fase 4)

| Module | Files | Purpose |
|--------|-------|---------|
| `apps.legacy.productos.models.Producto` | Eliminado | Legacy product model — table `productos_producto` dropped (migration 0009) |
| `apps.legacy.productos.models.Categoria` | Eliminado | Legacy category model — table `productos_categoria` dropped (migration 0009) |
| `apps.legacy.productos.models.MovimientoInventario` | Eliminado | Legacy inventory model — table `productos_movimientoinventario` dropped (migration 0009) |
| `apps.legacy.productos.admin` | Eliminado | ProductoAdmin + MovimientoInventarioAdmin |
| `apps.legacy.productos.views` | Eliminado | Legacy product views (676 lines, ALL orphan) |
| `apps.legacy.productos.forms` | Eliminado | ProductoForm + ProductoEditForm |
| `apps.legacy.productos.urls` | Eliminado | Not included in root urlconf |
| `apps.legacy.productos.tests` | Eliminado | ProductoModelTests |

**Files preserved**: `views_dynamic.py` (active), `wrappers.py` (active), `migrations/` (9 files, migration chain).

## Zero Legacy Models Remaining

All legacy models from both `ventas` and `productos` apps have been removed:

- ✅ `Venta` (Fase 3 — table `ventas_venta` dropped)
- ✅ `Cliente` (Fase 3 — table `ventas_cliente` dropped)
- ✅ `Producto` (Fase 4 — table `productos_producto` dropped)
- ✅ `Categoria` (Fase 4 — table `productos_categoria` dropped)
- ✅ `MovimientoInventario` (Fase 4 — table `productos_movimientoinventario` dropped)

## Dynamic Forms Infrastructure

The Dynamic Forms EAV engine at `apps/platform/dynamic_forms/` is fully synchronized:

| Component | Status |
|-----------|--------|
| All 4 models vs DB tables | Fully synchronized |
| `manage.py check` | 0 issues |
| `makemigrations --check` | No pending changes |
| `migrate --plan` | No pending operations |
| `sembrar_formularios_base` ready | Columns exist, nullable constraints correct |

**Migrations applied:**
- `0001_initial` to `0005_fix_schema_discrepancies` — all applied, DB matches Python models.
- `0006_add_valorcampo_campo_valor_index` — composite index on `(campo_id, valor)` for EAV queries.
- `0007_campo_identificador_principal_alter_campo_tipo` — adds `identificador_principal` field and `moneda` type.

## Completion Estimates

| Area | Estimate | Basis |
|------|----------|-------|
| Product CRUD | **100% migrated** | Dynamic views handle all CRUD |
| Sales CRUD | **100% migrated** | Dynamic views + hooks handle sales |
| Clients CRUD | **100% migrated** | Dynamic form used everywhere |
| Inventory | **100% migrated** | Dynamic views handle movements |
| Categories | **100% migrated** | Dynamic options; modelo legacy inactivo |
| Reports | **100% migrated** | All views on Dynamic Forms; legacy code removed |
| Data Migration (products) | **100% migrated** | 6/6 products migrated; idempotent command |
| Data Migration (Venta/Cliente) | **100% migrated** | 5/5 ventas, 1/1 cliente migrados; commands adaptados a no-op |
| Legacy model cleanup | **100%** | All 5 legacy models eliminated (Fase 3 + Fase 4) |
| Legacy views/urls removal | **100%** | All orphan view/url files eliminated (Fase 3 + Fase 4) |
| Code cleanup (Phase 5) | **100%** | Orphan code, unused imports, duplicate constants, N+1 audit — all clean |
