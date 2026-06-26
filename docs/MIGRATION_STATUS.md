# Migration Status

This document tracks the migration progress from legacy Django models to the Dynamic Forms EAV system.

## Overview

The project is mid-transition. Both legacy Django models and the Dynamic Forms EAV system coexist. The main `config/urls.py` routes most business endpoints to dynamic views (`views_dynamic.py`), but legacy views, models, and templates remain in the codebase.

## Fully Migrated Modules

These modules use Dynamic Forms for their primary data operations:

| Module | Details |
|--------|---------|
| **Productos (CRUD)** | `apps/legacy/productos/views_dynamic.py` handles list, create, edit, delete via `DynamicService`. Product URLs in `config/urls.py` point to dynamic views. Wrappers bridge data to legacy templates. |
| **Catálogo Público** | `catalogo_publico` (catálogo público) migrado a `views_dynamic.py` usando `DynamicService` + `DynamicProductWrapper`. Filtro `mostrar_agotados_catalogo`, orden alfabético, `telefono_whatsapp` replicados. Ruta en `config/urls.py` apunta a `views_dynamic`. |
| **Ventas (CRUD)** | `apps/legacy/ventas/views_dynamic.py` handles new sale, history, export via `DynamicService`. Sale URLs point to dynamic views. Stock decrement via hook (`post_crear_venta`). |
| **Clientes** | Client CRUD uses the `Clientes` dynamic form. Views in `apps/legacy/ventas/views_dynamic.py`. |
| **Inventory (dynamic)** | `apps/legacy/productos/views_dynamic.py` provides inventory view, stock history, Excel export using Dynamic Forms data. |
| **Reports** | `apps/shared/reportes/views.py` — all 5 views (main, Excel, 3 PDFs) use Dynamic Forms via `obtener_datos_reportes_dinamico()` and `_envolver_ventas()`. Legacy code (`obtener_datos_reportes()`, `ventas_filtradas_reportes()`, `construir_grafica_meses()`) removed. |

## Partially Migrated Modules

| Module | Details |
|--------|---------|
| **Products — Categories** | Category management migrado a opciones dinámicas del campo `categoria` (tipo lista) en el formulario Productos. Vistas `agregar_categoria` y `crear_categoria` migradas a `views_dynamic.py`. Modelo `Categoria` legacy ya no tiene vistas activas. |
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

### Categories — Complete
- Categorías migradas a opciones dinámicas del campo `categoria` (tipo lista) en el formulario Productos.
- Vistas `agregar_categoria` y `crear_categoria` migradas a `views_dynamic.py` — gestionan las opciones del campo directamente.
- `CategoriaForm`, `CategoriaAdmin` y código legacy asociado eliminados.
- El modelo `Categoria` legacy persiste en `models.py` para compatibilidad con migraciones y tests, pero no tiene vistas activas.
- El comando `migrar_productos_dynamic` aún lo referencia para sincronizar categorías legacy.

### Reports — Complete
- All 5 views (`reportes/`, Excel, 3 PDFs) use Dynamic Forms via `obtener_datos_reportes_dinamico()` and `_envolver_ventas()`.
- Legacy code removed: `obtener_datos_reportes()`, `ventas_filtradas_reportes()`, `construir_grafica_meses()`, legacy imports (`Venta`, `Producto`, `Cliente`, `Categoria`, `Sum`).
- Migration status: **100%**.

### Legacy Models Cleanup
- The legacy models and their views/templates can be removed only after:
  1. Data migration from legacy to Dynamic Forms is complete.
  2. All templates are verified to work with wrappers.
  3. Category functionality is migrated.

## Dynamic Forms Infrastructure

The Dynamic Forms EAV engine at `apps/platform/dynamic_forms/` has been audited and the database schema is now fully synchronized with the Python models.

| Component | Status |
|-----------|--------|
| All 4 models vs DB tables | ✅ Fully synchronized |
| `manage.py check` | ✅ 0 issues |
| `makemigrations --check` | ✅ No pending changes |
| `migrate --plan` | ✅ No pending operations |
| `sembrar_formularios_base` ready | ✅ Columns exist, nullable constraints correct |
| Form1 (manual/test data) | ⚠️ Safe to delete; no production data |

**Migrations applied:**
- `0001_initial` — Base schema
- `0002_campo_activo_registro_fecha_actualizacion_and_more` — Added `activo`, `fecha_actualizacion`, expanded tipos
- `0003_campo_formula_campo_formulario_destino_and_more` — Added `formula`, `formulario_destino`, expanded tipos
- `0004_campo_unico_formulario_hook_post_actualizar_and_more` — Added `unico`, `hook_post_crear`, `hook_post_actualizar`, `validacion_personalizada`
- `0005_fix_schema_discrepancies` — Fixed 3 pre-existing DB-vs-model mismatches: `creado_por_id` nullable, `valor` NOT NULL, `nombre` varchar(100)

## Completion Estimates

These estimates are based on code inspection, not metrics:

| Area | Estimate | Basis |
|------|----------|-------|
| Product CRUD | **~100% migrated** | Dynamic views handle all CRUD; catálogo público migrado; `migrar_productos_dynamic` command created and tested |
| Sales CRUD | ~90% migrated | Dynamic views + hooks handle sales flow |
| Clients CRUD | ~85% migrated | Dynamic form used; some edge cases remain |
| Inventory | ~90% migrated | Dynamic views handle movements; stock operations via hooks; movimientos iniciales migrados |
| Categories | **~100% migrated** | Categorías como opciones dinámicas; CRUD migrado a `views_dynamic.py`; modelo `Categoria` legacy inactivo |
| Reports | **100% migrated** | All views on Dynamic Forms; legacy code removed |
| Data Migration (products) | **100% migrated** | 6/6 products migrated; idempotent command available |
| Data Migration (other) | ~0% migrated | No migration scripts for Venta/Cliente |
| Legacy model cleanup | ~0% | All legacy models and views still present (but 4 files immediately deletable) |

**Detalle de migración de productos:**
- 6/6 productos legacy migrados exitosamente a Registros dinámicos
- 6/6 imágenes preservadas (URLs de Cloudinary)
- 6/6 movimientos iniciales de inventario creados
- 5/5 categorías legacy sincronizadas a opciones dinámicas
- 3 ejecuciones de idempotencia sin duplicados
- Command `migrar_productos_dynamic` implementado y verificado
