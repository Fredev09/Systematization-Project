# TODO

Organizado por prioridad. Basado en la auditoría completa de modelos
legacy (`docs/SESSION_LOG.md`, `PRODUCTS_MIGRATION.md`, `ROADMAP.md`,
`MIGRATION_STATUS.md`).

---

## Fase 1 — Limpieza inmediata (RIESGO: BAJO)

Archivos huérfanos que pueden eliminarse sin riesgo porque ningún
código activo los referencia. Rollback: `git checkout`.

| # | Tarea | Estado |
|---|-------|--------|
| 1a | Eliminar `apps/legacy/productos/urls.py` (no incluido en urlconf raíz) | Pendiente |
| 1b | Eliminar `apps/legacy/ventas/urls.py` (no incluido en urlconf raíz) | Pendiente |
| 1c | Eliminar `apps/legacy/productos/views.py` (0 vistas con ruta activa) | Pendiente |
| 1d | Eliminar `apps/legacy/ventas/views.py` (0 vistas con ruta activa) | Pendiente |
| 1e | Eliminar `apps/legacy/productos/forms.py` (solo usado por orphan views) | Pendiente |
| 1f | Eliminar `templates/productos/agregar_producto.html` (orphan) | Pendiente |
| 1g | Eliminar `templates/productos/editar_producto.html` (orphan) | Pendiente |
| 1h | Eliminar `templates/productos/eliminar_producto.html` (orphan) | Pendiente |
| 1i | Eliminar `templates/formularios/agregar_categoria.html` (orphan) | Pendiente |
| 1j | Eliminar import muerto `productos_views` en `config/urls.py:19` | ✅ Completado (Fase 3) |

Validación: `python manage.py check` + `makemigrations --check`.

---

## Fase 2 — Migración de datos Venta/Cliente (RIESGO: ALTO)

Crear script que copie datos de tablas legacy `ventas_venta` y
`ventas_cliente` a Dynamic Forms, mapeando FK producto_id → sku
dinámico y cliente_id → documento dinámico.

| # | Tarea | Estado |
|---|-------|--------|
| 2a | Crear `migrar_clientes_dynamic.py` — migración idempotente de Clientes | ✅ Completado |
| 2b | Crear `migrar_ventas_dynamic.py` — migración idempotente de Ventas | ✅ Completado |
| 2c | Migrar relaciones: producto_id → Registro.sku, cliente_id → Registro.documento | ✅ Completado |
| 2d | Probar idempotencia (2+ ejecuciones sin duplicados) | ✅ Completado |
| 2e | Crear `verificar_integridad_dynamic.py` — comando de validación | ✅ Completado |
| 2f | Verificar integridad: 100% coincidencias (cantidad, totales, usuarios, relaciones) | ✅ Completado |

Rollback: re-ejecutar script. Validación: `check` + conteo + pruebas
funcionales de ventas (nueva venta, historial, exportar).

---

## Fase 3 — Eliminar Venta y Cliente (RIESGO: MEDIO) — ✅ COMPLETADO

| # | Tarea | Estado |
|---|-------|--------|
| 3a | Eliminar modelos Venta y Cliente de `ventas/models.py` | ✅ Completado |
| 3b | Eliminar `apps/legacy/ventas/admin.py` (VentaAdmin, ClienteAdmin) | ✅ Completado |
| 3c | Eliminar `apps/legacy/ventas/tests.py` | ✅ Completado |
| 3d | Eliminar migraciones legacy de ventas (8 archivos en `ventas/migrations/`) | ❌ No procede (preservadas para cadena de migraciones) |
| 3e | Crear migración que elimine tablas `ventas_venta` y `ventas_cliente` | ✅ Completado (migración 0009) |
| 3f | Limpiar `config/settings/base.py` — eliminar `apps.legacy.ventas` de INSTALLED_APPS | ❌ No procede (app contiene hooks, views_dynamic, templatetags activos) |

Rollback: `git checkout apps/legacy/ventas/models.py` + revertir migración 0009.
Validación: `check` (0 issues), `verificar_integridad_dynamic` (TODO OK),
`test apps.platform.dynamic_forms` (26/26).

---

## Fase 4 — Eliminar Producto/Categoria/MovimientoInventario (RIESGO: MEDIO)

Después de eliminar Venta/Cliente (que tienen FK a Producto).

| # | Tarea | Estado |
|---|-------|--------|
| 4a | Eliminar modelos de `productos/models.py` (Categoria, Producto, MovimientoInventario) | Pendiente |
| 4b | Eliminar `apps/legacy/productos/admin.py` | Pendiente |
| 4c | Eliminar `apps/legacy/productos/tests.py` | Pendiente |
| 4d | Eliminar migraciones legacy de productos (8 archivos en `productos/migrations/`) | Pendiente |
| 4e | Crear migración que elimine tablas `productos_producto`, `productos_categoria`, `productos_movimientoinventario` | Pendiente |
| 4f | Limpiar `config/settings/base.py` — eliminar `apps.legacy.productos` de INSTALLED_APPS | Pendiente |

Rollback: mismo mecanismo que Fase 3. Validación: `check`, `migrate`,
pruebas funcionales de productos e inventario.

---

## Fase 5 — Limpieza final (RIESGO: BAJO)

| # | Tarea | Estado |
|---|-------|--------|
| 5a | Eliminar `migrar_productos_dynamic.py` (command de migración) | Pendiente |
| 5b | Squash migraciones de dynamic_forms (opcional) | Pendiente |
| 5c | Actualizar documentación de arquitectura | Pendiente |
| 5d | Verificar que ningún template importa modelos legacy | Pendiente |

Validación: `check`, limpieza de `__pycache__`, `makemigrations --check`.

---

## Otras tareas independientes

| # | Tarea | Prioridad | Estado |
|---|-------|-----------|--------|
| R1 | Migrar generación de gráficos SVG (línea, donut, barras) a Dynamic Forms | Media | Pendiente |
| R2 | Integridad referencial: validación que impida eliminar Registro referenciado | Alta | Pendiente |
| R3 | Límites de seguridad en queries (máx. 1000 en top() y buscar()) | Alta | Pendiente |
| R4 | Índices compuestos en ValorCampo(campo_id, valor) | Media | Pendiente |
| R5 | Caché de dashboard (5 min) | Media | Pendiente |
| R6 | Evaluar modelo híbrido para Ventas | Media | Pendiente |
| R7 | Profiling con Django Debug Toolbar | Media | Pendiente |
| R8 | Documentación de límites EAV | Baja | Pendiente |
