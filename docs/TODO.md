# TODO

Organizado por prioridad. Basado en el código existente,
`ROADMAP.md`, `MIGRATION_STATUS.md`, `EAV_LIMITACIONES.md` y
`PRODUCTS_MIGRATION.md`.

---

## Alta

| # | Tarea | Fuente | Estado |
|---|-------|--------|--------|
| 1 | **Migrar `catalogo_publico` → Dynamic Forms**: Reemplazar la vista legacy de catálogo público por una versión dinámica que use `DynamicService` + `DynamicProductWrapper`. La plantilla `templates/public/catalogo.html` ya es compatible. | `PRODUCTS_MIGRATION.md` | ✅ Completado |
| 2 | **Migrar categorías legacy (CRUD)**: Reemplazar `agregar_categoria` y `crear_categoria` con gestión de opciones dinámicas del campo `categoria`. | `PRODUCTS_MIGRATION.md` | ✅ Completado |
| 3 | **Migración de datos Ventas legacy → Dynamic Forms**: Crear script que copie datos de `Venta` y `Cliente` legacy a Dynamic Forms. Necesario para eliminar FK `Venta.producto → Producto`. | `PRODUCTS_MIGRATION.md`, `MIGRATION_STATUS.md:44-46` | Pendiente |
| 4 | **Reportes Fase 2 — Gráficos dinámicos**: Migrar generación de gráficos SVG (línea, donut, barras) a usar datos de Dynamic Forms. | `ROADMAP.md:48`, `MIGRATION_STATUS.md:52-53` | Pendiente |
| 5 | **Integridad referencial**: Implementar validación que impida eliminar un `Registro` referenciado por un campo `relacion` en otro formulario. | `ROADMAP.md:42`, `EAV_LIMITACIONES.md:177` | Pendiente |
| 6 | **Límites de seguridad en queries**: Agregar máximo de resultados (ej. 1000) a `top()` y `buscar()`. | `ROADMAP.md:44`, `EAV_LIMITACIONES.md:178` | Pendiente |

---

## Media

| # | Tarea | Fuente | Estado |
|---|-------|--------|--------|
| 7 | **Índices compuestos en ValorCampo**: Agregar índices en `ValorCampo(campo_id, valor)` con `varchar_pattern_ops`. | `ROADMAP.md:34`, `EAV_LIMITACIONES.md:173` | Pendiente |
| 8 | **Caché de dashboard**: Implementar caché de 5 minutos para estadísticas del dashboard y reducir consultas repetitivas. | `ROADMAP.md:36`, `EAV_LIMITACIONES.md:174` | Pendiente |
| 9 | **Evaluar modelo híbrido para Ventas**: Almacenar campos críticos (fecha, total, producto_id) como columnas reales en `Registro`. | `ROADMAP.md:38`, `EAV_LIMITACIONES.md:175` | Pendiente |
| 10 | **Profiling con Django Debug Toolbar**: Identificar cuellos de botella en consultas EAV. | `ROADMAP.md:46`, `EAV_LIMITACIONES.md:179` | Pendiente |
| 11 | **Limpieza inmediata de archivos huérfanos**: Eliminar `apps/legacy/productos/urls.py`, `apps/legacy/ventas/views.py`, `templates/productos/agregar_producto.html`, `editar_producto.html`, `eliminar_producto.html` (ninguno tiene rutas activas). | `PRODUCTS_MIGRATION.md` | Pendiente |
| 12 | **Eliminar código legacy restante**: `templates/formularios/agregar_categoria.html`, `templates/public/catalogo.html`. (`CategoriaForm`, `CategoriaAdmin` ya eliminados; `views.py` parcialmente limpio) | `PRODUCTS_MIGRATION.md` | Pendiente |

---

## Baja

| # | Tarea | Fuente | Estado |
|---|-------|--------|--------|
| 13 | **Eliminar modelos legacy y migraciones**: `apps/legacy/productos/models.py`, `admin.py`, `tests.py`, `migrations/`, y `apps/legacy/ventas/tests.py`. Requiere migrar Venta y eliminar FK primero. | `PRODUCTS_MIGRATION.md` | Pendiente |
| 14 | **Eliminar command de migración**: `migrar_productos_dynamic.py` después de verificar que toda la data legacy fue migrada y no se necesita re-ejecutar. | `PRODUCTS_MIGRATION.md` | Pendiente |
| 15 | **Documentación de límites EAV**: Completar mediciones de rendimiento y actualizar tabla comparativa en `EAV_LIMITACIONES.md`. | `EAV_LIMITACIONES.md:157-167` | Pendiente |
| 16 | **Pruebas de migración**: Verificar que todos los templates funcionan correctamente con wrappers después de la migración. | `MIGRATION_STATUS.md:58` | Pendiente |
