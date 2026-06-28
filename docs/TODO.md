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
| 1a | Eliminar `apps/legacy/productos/urls.py` (no incluido en urlconf raíz) | ✅ Completado (Fase 4) |
| 1b | Eliminar `apps/legacy/ventas/urls.py` (no incluido en urlconf raíz) | ✅ Completado (Fase 3) |
| 1c | Eliminar `apps/legacy/productos/views.py` (0 vistas con ruta activa) | ✅ Completado (Fase 4) |
| 1d | Eliminar `apps/legacy/ventas/views.py` (0 vistas con ruta activa) | ✅ Completado (Fase 3) |
| 1e | Eliminar `apps/legacy/productos/forms.py` (solo usado por orphan views) | ✅ Completado (Fase 4) |
| 1f | Eliminar `templates/productos/agregar_producto.html` (orphan) | ✅ Completado (Fase 4) |
| 1g | Eliminar `templates/productos/editar_producto.html` (orphan) | ✅ Completado (Fase 4) |
| 1h | Eliminar `templates/productos/eliminar_producto.html` (orphan) | ✅ Completado (Fase 4) |
| 1i | Eliminar `templates/formularios/agregar_categoria.html` (orphan) | ✅ Completado (Fase 4) |
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

## Fase 4 — Eliminar Producto/Categoria/MovimientoInventario (RIESGO: MEDIO) — ✅ COMPLETADO

| # | Tarea | Estado |
|---|-------|--------|
| 4a | Eliminar modelos de `productos/models.py` (Categoria, Producto, MovimientoInventario) | ✅ Completado |
| 4b | Eliminar `apps/legacy/productos/admin.py` | ✅ Completado |
| 4c | Eliminar `apps/legacy/productos/tests.py` | ✅ Completado |
| 4d | Eliminar migraciones legacy de productos (8 archivos en `productos/migrations/`) | ❌ No procede (preservadas para cadena de migraciones) |
| 4e | Crear migración que elimine tablas `productos_producto`, `productos_categoria`, `productos_movimientoinventario` | ✅ Completado (migración 0009) |
| 4f | Limpiar `config/settings/base.py` — eliminar `apps.legacy.productos` de INSTALLED_APPS | ❌ No procede (app contiene wrappers, views_dynamic activos) |

Rollback: `git checkout apps/legacy/productos/models.py` + revertir migración 0009.
Validación: `check` (0 issues), `verificar_integridad_dynamic` (TODO OK).

---

## Fase 5 — Limpieza final (RIESGO: BAJO) — ✅ COMPLETADO

| # | Tarea | Estado |
|---|-------|--------|
| 5a | Eliminar `migrar_productos_dynamic.py` (command de migración) | ❌ No procede (preservado como no-op para rollback de referencia) |
| 5b | Squash migraciones de dynamic_forms (opcional) | Pendiente |
| 5c | Actualizar documentación de arquitectura | ✅ Completado |
| 5d | Verificar que ningún template importa modelos legacy | ✅ Completado (auditoría Fase 4: todos seguros) |

**Adicional (auditoría Fase 5):**
- ✅ Fix broken import `backend.permissions` → `config.permissions` en `usuarios/tests.py`
- ✅ Removed orphan `_cargar_productos()` en `productos/views_dynamic.py`
- ✅ Removed orphan `usuarios()` view en `config/views.py` (no enrutada)
- ✅ Removed orphan `rango_dia()` en `reportes/views.py`
- ✅ Removed unused import `json` en `dynamic_forms/views.py`
- ✅ Removed unused import `datetime` en `services_dynamic.py`
- ✅ Removed unused classes `CampoFormSetBase` y `RegistroEditForm` en `forms.py`
- ✅ Consolidated duplicate form name constants (7 archivos → import desde `services_dynamic.py`)
- ✅ N+1 query audit (0 issues encontrados en reportes)

Rollback: `git checkout` de archivos individuales.
Validación: `check` (0 issues), `makemigrations --check` (sin cambios).

Validación: `check`, limpieza de `__pycache__`, `makemigrations --check`.

---

## Fase 6 — Corrección de hallazgos de auditoría (Críticos y Altos) — ✅ COMPLETADO

| # | Hallazgo | Resultado | Estado |
|---|----------|-----------|--------|
| C1 | Template `agregar_categoria.html` eliminado → 500 error | Template recreado | ✅ Corregido |
| C2 | SECRET_KEY hardcodeada | Default eliminado | ✅ Corregido |
| C3 | Seed sin hook → stock no descuenta | Hook auto-asignado | ✅ Corregido |
| A1/A2 | Permisos en vistas de ventas | **Falso positivo** — accesible intencionalmente por vendedores | 📌 Documentado |
| A3 | Paginación carga todo en memoria | **Limitación EAV** — no optimizable sin desnormalización | 📌 Documentado |
| A4 | Falta índice compuesto en ValorCampo | Migración 0006 creada y aplicada | ✅ Corregido |
| A5 | ALLOWED_HOSTS = ['*'] | Cambiado a variable de entorno | ✅ Corregido |
| A6-A8 | Refactor de funciones grandes | No procede (refactor grande, fuera del alcance) | ⏳ Pendiente |
| A9 | JS huérfanos (agregar/editar producto) | Archivos eliminados | ✅ Corregido |
| A10 | Imágenes rotas en index.html | Template index.html está huérfano (A11) — pospuesto | ⏳ Pendiente |
| A11 | Template index.html huérfano | No afecta operación — pospuesto | ⏳ Pendiente |
| M6-M8 | Imports sin usar | Limpiados | ✅ Corregido |

---

## Otras tareas independientes

| # | Tarea | Prioridad | Estado |
|---|-------|-----------|--------|
| R1 | Migrar generación de gráficos SVG (línea, donut, barras) a Dynamic Forms | Media | Pendiente |
| R2 | Integridad referencial: validación que impida eliminar Registro referenciado | Alta | Pendiente |
| R3 | Límites de seguridad en queries (máx. 1000 en top() y buscar()) | Alta | Pendiente |
| R4 | Índices compuestos en ValorCampo(campo_id, valor) | Media | ✅ Completado (Fase 6) |
| R5 | Caché de dashboard (5 min) | Media | Pendiente |
| R6 | Evaluar modelo híbrido para Ventas | Media | Pendiente |
| R7 | Profiling con Django Debug Toolbar | Media | Pendiente |
| R8 | Documentación de límites EAV | Baja | Pendiente |
| R9 | Importación Excel para Dynamic Forms | Alta | ✅ Completado |
| R17 | Enterprise Import/Export v2.0 — Pipeline, auditoría, rollback, historial | Alta | ✅ Completado |
| R10 | Tipo de campo Moneda (enteros, decimales, máx 2 decimales) | Alta | ✅ Completado |
| R11 | Validación booleana extendida (Sí, Si, True, False, 1, 0, yes, no, on, off) | Alta | ✅ Completado |
| R12 | Conversión automática datetime → YYYY-MM-DD en importación Excel | Alta | ✅ Completado |
| R13 | Identificador Principal en Campo (solo uno por formulario) | Alta | ✅ Completado |
| R14 | Configuración de identificación en crear/editar formulario | Alta | ✅ Completado |
| R15 | Tablas sin ID interno, identificador principal primero | Alta | ✅ Completado |
| R16 | Servicios de infraestructura: obtener_identificador_principal, buscar_por_identificador, upsert_por_identificador | Alta | ✅ Completado |
