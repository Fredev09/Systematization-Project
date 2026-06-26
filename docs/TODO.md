# TODO

Organizado por prioridad. Basado únicamente en el código existente,
`ROADMAP.md`, `MIGRATION_STATUS.md` y `EAV_LIMITACIONES.md`.

---

## Alta

| # | Tarea | Fuente | Estado |
|---|-------|--------|--------|
| 1 | **Migración de datos legacy → Dynamic Forms**: Crear script que copie datos de tablas legacy (`Producto`, `Venta`, `Cliente`, `MovimientoInventario`) a Dynamic Forms. | `ROADMAP.md:40`, `EAV_LIMITACIONES.md:176`, `MIGRATION_STATUS.md:44-46` | Pendiente |
| 2 | **Migración de Categorías**: Crear equivalente dinámico para `Categoria`. Actualmente es modelo legacy sin reemplazo EAV. | `ROADMAP.md:50`, `MIGRATION_STATUS.md:48-50` | Pendiente |
| 3 | **Reportes Fase 2 — Gráficos dinámicos**: Migrar generación de gráficos SVG (línea, donut, barras) a usar datos de Dynamic Forms. | `ROADMAP.md:48`, `MIGRATION_STATUS.md:52-53` | Pendiente |
| 4 | **Integridad referencial**: Implementar validación que impida eliminar un `Registro` referenciado por un campo `relacion` en otro formulario. | `ROADMAP.md:42`, `EAV_LIMITACIONES.md:177` | Pendiente |
| 5 | **Límites de seguridad en queries**: Agregar máximo de resultados (ej. 1000) a `top()` y `buscar()`. | `ROADMAP.md:44`, `EAV_LIMITACIONES.md:178` | Pendiente |

---

## Media

| # | Tarea | Fuente | Estado |
|---|-------|--------|--------|
| 6 | **Índices compuestos en ValorCampo**: Agregar índices en `ValorCampo(campo_id, valor)` con `varchar_pattern_ops`. | `ROADMAP.md:34`, `EAV_LIMITACIONES.md:173` | Pendiente |
| 7 | **Caché de dashboard**: Implementar caché de 5 minutos para estadísticas del dashboard y reducir consultas repetitivas. | `ROADMAP.md:36`, `EAV_LIMITACIONES.md:174` | Pendiente |
| 8 | **Evaluar modelo híbrido para Ventas**: Almacenar campos críticos (fecha, total, producto_id) como columnas reales en `Registro`. | `ROADMAP.md:38`, `EAV_LIMITACIONES.md:175` | Pendiente |
| 9 | **Profiling con Django Debug Toolbar**: Identificar cuellos de botella en consultas EAV. | `ROADMAP.md:46`, `EAV_LIMITACIONES.md:179` | Pendiente |
| 10 | **Limpieza de vistas legacy**: Deprecar o eliminar `apps/legacy/productos/views.py` y `apps/legacy/ventas/views.py`. | `ROADMAP.md:52` | Pendiente |

---

## Baja

| # | Tarea | Fuente | Estado |
|---|-------|--------|--------|
| 11 | **Limpieza de modelos legacy**: Eliminar modelos Django legacy (`Producto`, `Venta`, `Cliente`, `MovimientoInventario`) tras completar migración de datos. | `ROADMAP.md:54`, `MIGRATION_STATUS.md:55-59` | Pendiente |
| 12 | **Documentación de límites EAV**: Completar mediciones de rendimiento y actualizar tabla comparativa en `EAV_LIMITACIONES.md`. | `EAV_LIMITACIONES.md:157-167` | Pendiente |
| 13 | **Pruebas de migración**: Verificar que todos los templates funcionan correctamente con wrappers después de la migración. | `MIGRATION_STATUS.md:58` | Pendiente |
