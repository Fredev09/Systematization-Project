# Roadmap

This document summarizes the technical work that can be inferred from the current repository state. It does not invent features — only describes work clearly suggested by the existing code, comments, and documentation.

## Completed

- Dynamic Forms EAV engine (models, service layer, validators, template tags).
- Product CRUD migration to Dynamic Forms (`views_dynamic.py`).
- Sales CRUD migration to Dynamic Forms (`views_dynamic.py`).
- Client CRUD migration to Dynamic Forms (`views_dynamic.py`).
- Inventory management migration to Dynamic Forms (stock movements, history).
- Hook system (post-create, post-update) with recursion protection.
- Wrapper adapters for template compatibility (`DynamicProductWrapper`, `DynamicVentaWrapper`, `DynamicMovimientoInventarioWrapper`, `DynamicClienteWrapper`).
- Formula evaluation for calculated fields (with chaining support).
- Excel export for any dynamic form (`exportar_registros_excel`).
- Reports dashboard with legacy data (KPIs, SVG charts, PDF/Excel export).
- Seed management command for base forms (`sembrar_formularios_base`).
- Test data creation command (`crear_datos_prueba`).
- Hook assignment command (`asignar_hook_ventas`).
- User authentication and role management (Administrador/Vendedor).
- Store configuration singleton with context processor.
- Password recovery via Brevo email.
- Cloudinary integration for media storage.
- CI via GitHub Actions (CodeQL, SonarCloud).

## In Progress

- **Reports Phase 1 (Dynamic data layer)**: `obtener_datos_reportes_dinamico()` exists but charts still use legacy model data. The function is defined and returns dynamic KPIs but is not fully integrated into the report templates.

## Pending

The following items are based on explicit TODO items in `docs/EAV_LIMITACIONES.md` and code patterns that indicate incomplete transitions:

1. **Database indexes for ValorCampo** — Add composite indexes on `ValorCampo(campo_id, valor)` with `varchar_pattern_ops` to improve query performance. (Source: `docs/EAV_LIMITACIONES.md`)

2. **Dashboard cache** — Implement 5-minute cache for dashboard statistics to reduce repeated aggregation queries. (Source: `docs/EAV_LIMITACIONES.md`)

3. **Hybrid model evaluation for Ventas** — Consider storing critical sales fields (fecha, total, producto_id) as real columns in `Registro` while keeping variable attributes in EAV. (Source: `docs/EAV_LIMITACIONES.md`)

4. **Data migration from legacy to dynamic_forms** — Create a migration script to copy data from legacy `Producto`, `Venta`, `Cliente`, `MovimientoInventario` tables to Dynamic Forms. (Source: `docs/EAV_LIMITACIONES.md`)

5. **Application-level referential integrity** — Implement validation that prevents deleting a `Registro` that is referenced by a `relacion`-type field in another form. (Source: `docs/EAV_LIMITACIONES.md`)

6. **Query safety limits** — Add maximum result limits (e.g., 1000) to `top()` and `buscar()` to prevent unbounded queries. (Source: `docs/EAV_LIMITACIONES.md`)

7. **Profiling with Django Debug Toolbar** — Identify performance bottlenecks in EAV queries. (Source: `docs/EAV_LIMITACIONES.md`)

8. **Reports Phase 2 — Dynamic charts** — Migrate chart generation (SVG line chart, conic-gradient donut, top products bar chart) to use Dynamic Forms data. (Source: `apps/shared/reportes/views.py` — comment `# Fase 1: solo datos dinámicos`)

9. **Category migration** — The `Categoria` legacy model is still used for category CRUD. No dynamic analog exists. Categories are currently stored as plain text on the Productos form. (Source: `config/urls.py` — comment `# Productos — categorías legacy (pendientes de migrar a Dynamic Forms)`)

10. **Legacy views cleanup** — Remove or deprecate `apps/legacy/productos/views.py` and `apps/legacy/ventas/views.py` once all routes use dynamic versions. (Inferred from the existence of parallel view files.)

11. **Legacy models cleanup** — Remove legacy Django models (`Producto`, `Venta`, `Cliente`, `MovimientoInventario`) after data migration is complete. (Inferred from the dual-architecture pattern.)

## Summary

| Area | Status |
|------|--------|
| EAV Engine | Completed |
| Product CRUD | Completed |
| Sales CRUD + hook | Completed |
| Client CRUD | Completed |
| Inventory | Completed |
| Reports (data layer) | In Progress |
| Reports (charts) | Pending |
| Categories | Pending (legacy) |
| Data migration | Pending |
| Performance optimization | Pending |
| Legacy code cleanup | Pending |
