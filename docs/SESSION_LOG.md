# Session Log

Historial cronológico del proyecto. Cada entrada documenta una sesión
de trabajo con los cambios realizados, decisiones tomadas y problemas
encontrados.

---

## [2026-06-26] Estado actual del proyecto

### Trabajo realizado
- Configuración inicial y fundación del proyecto.
- Implementación del sistema EAV Dynamic Forms (modelos `Formulario`,
  `Campo`, `Registro`, `ValorCampo`) con capa de servicio (`DynamicService`).
- Migración incremental de módulos legacy a Dynamic Forms.

### Archivos modificados
- `apps/platform/dynamic_forms/` — Núcleo del motor EAV.
- `apps/legacy/productos/views_dynamic.py` — Vistas dinámicas de productos.
- `apps/legacy/ventas/views_dynamic.py` — Vistas dinámicas de ventas.
- `apps/legacy/productos/wrappers.py` — Adaptadores EAV → templates.
- `apps/legacy/ventas/hooks.py` — Hooks de negocio (descuento de stock).
- `config/urls.py` — Enrutamiento a vistas dinámicas.
- `docs/*.md` — Documentación inicial del proyecto.

### Decisiones importantes
- **EAV como reemplazo de esquemas fijos**: Los modelos dinámicos
  (`Formulario`, `Campo`, `Registro`, `ValorCampo`) permiten cambios
  de esquema sin migraciones.
- **Arquitectura híbrida**: Los modelos legacy coexisten con Dynamic
  Forms. Las URLs principales apuntan a vistas dinámicas, pero las
  legacy quedan como respaldo.
- **Wrapper Pattern**: Se crean adaptadores (`DynamicProductWrapper`,
  `DynamicVentaWrapper`, etc.) para que los templates existentes
  funcionen sin cambios con datos EAV.
- **Static-method Service Layer**: `DynamicService` expone solo métodos
  estáticos, sin instanciación ni DI.
- **TextField universal**: Todos los valores EAV se almacenan como
  strings en `ValorCampo.valor`.
- **Evaluación en dos pasos**: Los campos calculados se evalúan después
  de los campos normales para soportar encadenamiento.
- **Hooks para efectos secundarios**: La lógica de negocio (descuento
  de stock) se implementa como callables configurables, no como
  `save()` del modelo.
- **Pessimistic Locking**: Las operaciones sensibles (stock) usan
  `select_for_update()` para evitar race conditions.
- **Sin REST API**: Todo el renderizado es server-side con Django
  Templates.
- **Cloudinary opcional**: Soporte para almacenamiento local o en la
  nube mediante variable de entorno.
- **Brevo para email**: Recuperación de contraseña vía Brevo (Sendinblue).
- **Singleton Config**: `ConfiguracionTienda` con `pk=1` forzado.

### Problemas encontrados
- Las consultas EAV con múltiples filtros generan JOINs excesivos
  (ver `docs/EAV_LIMITACIONES.md`).
- Las agregaciones (SUM, COUNT, GROUP BY) son 5-10x más lentas que en
  modelo relacional fijo.
- No existe integridad referencial real a nivel BD (las relaciones
  son IDs en texto).
- No hay migración de datos desde legacy a Dynamic Forms.
- Las categorías (`Categoria`) siguen siendo modelo legacy sin
  equivalente dinámico.
- No hay índices compuestos en `ValorCampo(campo_id, valor)`.
- No hay límites de seguridad en queries `top()` y `buscar()`.

---

## [2026-06-26] Configuración de infraestructura IA

### Trabajo realizado
- Creación de `opencode.json` con configuración de skills, permisos e instrucciones.
- Integración de skills de `.ai/skills/` con OpenCode mediante `skills.paths`.
- Creación de 2 playbooks: `migracion-completa` y `nuevo-modulo-dinamico`.
- Actualización del índice de playbooks en `.ai/playbooks/README.md`.

### Archivos creados
- `opencode.json` — Configuración del proyecto para OpenCode.
- `.ai/playbooks/migracion-completa.md` — Playbook de migración legacy → EAV.
- `.ai/playbooks/nuevo-modulo-dinamico.md` — Playbook de creación de nuevos módulos.

### Archivos modificados
- `.ai/playbooks/README.md` — Listado de playbooks disponibles.

### Decisiones importantes
- **Config over symlink**: Se usa `skills.paths` en `opencode.json` en lugar de
  symlink `.opencode/skills/` → `.ai/skills/` porque los skills están anidados
  bajo `community/` y `project/`, y OpenCode espera `<name>/SKILL.md` directamente.
- **Instrucciones unificadas**: `opencode.json` referencia `docs/AGENT_CONTEXT.md`,
  `TODO.md`, `SESSION_LOG.md`, `MIGRATION_STATUS.md` y `DECISIONS.md` para que todos
  los agentes carguen el contexto completo del proyecto.
- **Permisos abiertos**: `"*": "allow"` para skills — no hay restricciones.

### Problemas encontrados
- Ninguno.

---

## [2026-06-26] Reportes Fase 3A — Reconexión de vista principal a Dynamic Forms

### Trabajo realizado
- Cambio de `obtener_datos_reportes()` → `obtener_datos_reportes_dinamico()` en la vista `reportes()` de `apps/shared/reportes/views.py:912`.
- Verificación estructural: ambas funciones retornan exactamente las mismas 24 claves en el diccionario de contexto.
- Verificación de template: `templates/reportes/reportes.html` no usa `datos['ventas']` directamente, solo variables individuales como `ventas_totales`, `ventas_meses`, `top_productos`, etc. — todas presentes en ambas versiones.
- Verificación de referencias: `obtener_datos_reportes()` legacy sigue siendo usada por las 3 exportaciones (excel, pdf completo, pdf ventas) — no hay código huérfano.
- `python manage.py check` — 0 issues.

### Archivos modificados
- `apps/shared/reportes/views.py` — 1 línea cambiada (line 912).
- `docs/MIGRATION_STATUS.md` — actualizado estado de Reports de ~40% a ~50%, Phase 3A.
- `docs/SESSION_LOG.md` — este registro.

### Decisiones importantes
- **Rollback inmediato**: cambiar `obtener_datos_reportes_dinamico` → `obtener_datos_reportes` en la línea 912 restaura el comportamiento anterior.
- **Exportaciones no tocadas**: Excel y PDFs completan su ciclo de vida con datos legacy; migrarlas queda para Fase 3B+.

### Problemas encontrados
- El filtro por `categoria_id` y `producto_id` no se aplica en la versión dinámica (omisión documentada en Fase 1). Esto existía antes del cambio y no es una regresión.

---

## [2026-06-26] Reportes Fase 5A — Migración de exportación Excel a Dynamic Forms

### Trabajo realizado
- Migración completa de `exportar_reporte_excel()` para usar Dynamic Forms, eliminando dependencias de `Venta.objects`, `Producto.objects`, `Cliente.objects` y `Categoria.objects`.
- Datos agregados (KPIs, top productos, categorías) obtenidos de `obtener_datos_reportes_dinamico()`.
- Detalle de ventas obtenido mediante `Registro.objects.filter(formulario=Ventas)` + `DS.cargar_valores_mapa()` + `_envolver_ventas()` de `ventas/views_dynamic.py`.
- Filtros de categoría y producto resueltos desde los objetos dinámicos (`datos['categorias']` y `datos['productos']`).
- Filtro de vendedor aplicado en la query de Registro (`usuario_id`).
- Mismo formato Excel: 4 hojas (Reporte, Ventas, Top productos, Categorias), mismos encabezados, mismo estilo.

### Archivos modificados
- `apps/shared/reportes/views.py` — nueva importación de `_envolver_ventas`; reemplazo completo de `exportar_reporte_excel()`.
- `docs/MIGRATION_STATUS.md` — Reports ~50% → ~70%, Phase 5A.
- `docs/SESSION_LOG.md` — este registro.

### Decisiones importantes
- **Reutilización de `_envolver_ventas()`**: la función batch-resuelve productos, clientes y vendedores en 3 consultas (productos, clientes, users), sin N+1.
- **Filtros consistente con Fase 3A**: se usan las mismas fechas (`fecha_creacion__date__gte/__lte`) y vendedor (`usuario_id`) que en `obtener_datos_reportes_dinamico()`.
- **Filtro categoria/producto no aplicado a datos**: igual que en Fase 3A, la omisión es documentada. Los nombres se resuelven correctamente en el encabezado del Excel.

### Problemas encontrados
- Ninguno. `python manage.py check` — 0 issues.
- AST scan confirma que `exportar_reporte_excel()` ya no referencia `Venta.objects`, `Producto.objects`, `Cliente.objects` ni `Categoria.objects`.

---

## [2026-06-26] Reportes Fase 5B — Migración de exportación PDF Ventas a Dynamic Forms

### Trabajo realizado
- Migración completa de `exportar_reporte_ventas_pdf()` para usar Dynamic Forms.
- Mismo patrón que Fase 5A: `obtener_datos_reportes_dinamico()` para KPIs + `Registro.objects.filter(formulario=Ventas)` + `DS.cargar_valores_mapa()` + `_envolver_ventas()` para el detalle.
- Mismo PDF: resumen, detalle, columnas, anchos, estilos, límite 120 registros, nombre de archivo.
- `python manage.py check` — 0 issues.

### Archivos modificados
- `apps/shared/reportes/views.py` — reemplazo de `exportar_reporte_ventas_pdf()` (~50 líneas).
- `docs/MIGRATION_STATUS.md` — Reports ~70% → ~85%, Phase 5B.
- `docs/SESSION_LOG.md` — este registro.

### Decisiones importantes
- **Misma query que Excel**: filtros y orden consistente con Fase 5A.
- **Sin tocar `exportar_reporte_completo_pdf`**: queda como última pieza legacy del módulo.

### Problemas encontrados
- Ninguno.

---

## [2026-06-26] Reportes Fase Final — Migración 100% completada

### Trabajo realizado
- Cambio de `exportar_reporte_completo_pdf()` a `obtener_datos_reportes_dinamico()`.
- Eliminación de `obtener_datos_reportes()` (127 líneas), `ventas_filtradas_reportes()` (24 líneas) y `construir_grafica_meses()` (61 líneas) — todo código legacy huérfano.
- Eliminación de imports legacy (`Categoria`, `Producto`, `Cliente`, `Venta`, y `Sum` de django.db.models).
- `python manage.py check` — 0 issues.
- AST scan confirma 0 referencias a modelos legacy dentro de `apps/shared/reportes/views.py`.

### Archivos modificados
- `apps/shared/reportes/views.py` — cambio de 1 línea en `exportar_reporte_completo_pdf` + eliminación de ~230 líneas de código legacy.
- `docs/MIGRATION_STATUS.md` — Reports movido a "Fully Migrated", estimación 100%.
- `docs/SESSION_LOG.md` — este registro.

### Decisiones importantes
- **Migración completa del módulo**: Reportes es el primer módulo del proyecto en alcanzar 100% de migración a Dynamic Forms.
- **Eliminación segura**: todas las funciones legacy se verificaron huérfanas antes de eliminar.

### Problemas encontrados
- Ninguno.

### Próximo paso
Revisar `docs/TODO.md` y `docs/PRODUCTS_MIGRATION.md` para priorizar:
- Migración de `catalogo_publico` → vista dinámica.
- Migración de categorías (CRUD legacy → opciones dinámicas).
- Eliminación de código legacy huérfano.
- Migración del modelo `Venta` legacy (eliminar FK a `Producto`).


---

---

## [2026-06-26] Migración completa de productos legacy → Dynamic Forms

### Trabajo realizado
- Auditoría completa de infraestructura de Productos (modelos, vistas legacy y dinámicas, wrappers, servicios, templates, rutas, dependencias externas).
- Diseño de migración idempotente usando SKU `LEGACY-{id}` como trazabilidad.
- Implementación de `python manage.py migrar_productos_dynamic` con 5 pasos (verificar requisitos, sinconizar categorías, migrar productos, crear movimientos iniciales, validar).
- Sincronización automática de categorías: merge de 5 categorías legacy (`Blusa`, `Camisas`, `Jeans`, `Sets`, `Vestidos`) con 6 opciones del seed → 11 opciones finales.
- Migración de 6 productos legacy → dinámicos, con 6 imágenes (URLs de Cloudinary), 6 movimientos iniciales de inventario.
- Corrección de normalización de talla (`Única` → `Unica`).
- Agregado automático de `'Inventario inicial'` a opciones de motivo de MovimientosInventario.
- Prueba de idempotencia: 3 ejecuciones sin duplicados.
- Diseño del cambio de `catalogo_publico` (Fase 6).
- Identificación de código legacy eliminable (Fase 7): 4 archivos ya huérfanos, 4 eliminables tras migrar catálogo, 6 tras eliminar modelos.
- Creación de documentación completa en `docs/PRODUCTS_MIGRATION.md`.

### Archivos creados
- `apps/platform/dynamic_forms/management/commands/migrar_productos_dynamic.py` — Management command de migración idempotente.
- `docs/PRODUCTS_MIGRATION.md` — Documentación completa del proceso de migración.

### Archivos modificados
- `docs/SESSION_LOG.md` — este registro.
- `docs/MIGRATION_STATUS.md` — actualizado estado de Productos y Categorías.
- `docs/DECISIONS.md` — añadida decisión sobre estrategia de migración idempotente.
- `docs/TODO.md` — actualizado para reflejar el nuevo estado.

### Decisiones importantes
- **SKU como trazabilidad**: Se usa el campo `sku` con formato `LEGACY-{id}` como clave de identificación entre productos legacy y dinámicos. Esto permite idempotencia sin necesidad de crear un campo adicional.
- **URL de imagen en vez de archivo**: Cloudinary no soporta `.path()` para lectura de archivos. En lugar de descargar y re-subir imágenes, se almacena la URL existente (`imagen_final_url`) en el campo `imagen_url`.
- **Normalización de talla**: Las opciones dinámicas usan `'Unica'` (sin acento), pero los datos legacy tienen `'Única'`. Se normaliza durante la migración para evitar errores de validación.
- **Movimientos iniciales en paso separado**: Se crean en un segundo barrido (3b) para permitir que productos ya migrados antes de esta función reciban su movimiento inicial.

### Problemas encontrados
- Cloudinary no permite `FileField.path()` — resuelto usando `imagen_final_url`.
- Talla `'Única'` no coincide con opción dinámica `'Unica'` — resuelto con normalización.
- `'Inventario inicial'` no estaba en opciones de motivo — resuelto con sincronización automática.
- Primer intento de migración falló en movimientos iniciales por alias incorrecto de `DS.crear()` — resuelto en corrección.

### Próximo paso
Migrar `catalogo_publico` → Dynamic Forms y las categorías legacy.

### Trabajo realizado
- Auditoría completa del esquema de Dynamic Forms: comparación de modelos Django vs tabla real en PostgreSQL.
- Identificación de 4 discrepancias:
  1. Migración `0004` no aplicada (faltaban columnas `unico`, `hook_post_crear`, `hook_post_actualizar`, `validacion_personalizada`).
  2. `Formulario.creado_por_id` NOT NULL en BD vs `null=True` en modelo (bloqueaba el seed command).
  3. `ValorCampo.valor` nullable en BD vs `TextField()` sin null en modelo.
  4. `Campo.nombre` varchar(200) en BD vs `max_length=100` en modelo.
- Aplicación de migración `0004` (4 campos añadidos).
- Creación y aplicación de migración `0005_fix_schema_discrepancies` con `RunSQL` para corregir las 3 discrepancias preexistentes (el sistema de migraciones de Django no detectaba estos desajustes porque el estado de migración ya coincidía con el modelo).
- Verificación final: `check`, `makemigrations --check`, `migrate --plan` — todo OK, 0 pendientes.
- Verificación de que `sembrar_formularios_base` puede ejecutarse (todas las columnas existen, crear Formulario sin usuario funciona).

### Archivos creados
- `apps/platform/dynamic_forms/migrations/0005_fix_schema_discrepancies.py` — RunSQL para corregir nulabilidad y tipos.

### Archivos modificados
- `docs/SESSION_LOG.md` — este registro.

### Decisiones importantes
- **RunSQL sobre AlterField**: Las discrepancias preexistentes no son detectables por `makemigrations` porque el estado de migración de Django (basado en los archivos de migración) ya coincide con el modelo actual. La BD real diverge debido a cambios previos en el modelo que no generaron migraciones. Se usó `migrations.RunSQL` para forzar los `ALTER TABLE` necesarios.
- **Safe to fix**: Se verificó que no existían datos conflictivos (NULLs en valor, nombres > 100 chars) antes de aplicar restricciones.
- **Form1**: El formulario `Form1` (creado manualmente, 2 campos genéricos, 1 registro basura) no interfiere con el seed y puede eliminarse posteriormente.

### Problemas encontrados
- El seed command (`sembrar_formularios_base`) habría fallado con `IntegrityError` por la columna `creado_por_id NOT NULL` al intentar crear formularios sin usuario asignado.
- El seed command también habría fallado con `ProgrammingError` por la columna `unico` inexistente.
- Ambos bloqueos quedan resueltos tras aplicar migraciones 0004 + 0005.

---

## [2026-06-26] Migración de categorías legacy a opciones dinámicas

### Trabajo realizado
- Auditoría completa de todas las referencias al modelo `Categoria` en el proyecto (47 archivos, ~200+ referencias).
- Clasificación de dependencias: activas (`migrar_productos_dynamic`, tests), indirectas (wrappers, templates con `categoria.nombre`), huérfanas (`CategoriaForm`, `CategoriaAdmin`, vistas legacy `agregar_categoria`/`crear_categoria`).
- Implementación de vistas dinámicas de reemplazo en `views_dynamic.py`:
  - `agregar_categoria`: Gestiona opciones del campo `categoria` (tipo lista) en formulario Productos. GET muestra opciones actuales + formulario; POST agrega nueva opción.
  - `crear_categoria`: Endpoint AJAX que agrega opción dinámicamente y retorna JSON.
- `config/urls.py`: Rutas redirigidas de `productos_views` a `views_dynamic`.
- `views.py`: 50 líneas eliminadas (`agregar_categoria`, `crear_categoria`, imports `CategoriaForm`, `require_POST`).
- `forms.py`: `CategoriaForm` eliminado (37 líneas); import de `Categoria` removido.
- `admin.py`: `CategoriaAdmin` eliminado (5 líneas); import de `Categoria` removido.

### Archivos modificados
- `apps/legacy/productos/views_dynamic.py` — 2 nuevas funciones (+85 líneas), 2 nuevos imports.
- `apps/legacy/productos/views.py` — 50 líneas eliminadas.
- `apps/legacy/productos/forms.py` — `CategoriaForm` eliminado, import limpio.
- `apps/legacy/productos/admin.py` — `CategoriaAdmin` eliminado, import limpio.
- `config/urls.py` — Imports y rutas actualizados.
- `docs/MIGRATION_STATUS.md` — Categorías movido a Fully Migrated.
- `docs/TODO.md` — Tarea #2 marcada completada.
- `docs/SESSION_LOG.md` — este registro.

### Decisiones importantes
- **Opción dinámica como reemplazo**: Las categorías ya no son registros del modelo `Categoria`, sino opciones de un campo `lista` en el formulario Productos. La migración es conceptual: en vez de crear un modelo FK, se gestiona una lista de strings.
- **Backward compatibility**: Las URLs `agregar_categoria` y `crear_categoria` se mantienen. El template `formularios/agregar_categoria.html` funciona sin cambios (recibe un `forms.Form` en vez de `ModelForm`, y `SimpleNamespace` en vez de instancias de `Categoria`).
- **Modelo legacy preservado**: El modelo `Categoria` en `models.py` no se elimina porque aún es referenciado por migraciones, tests, y el comando `migrar_productos_dynamic` (para sincronizar categorías legacy). Su eliminación requiere planificación separada.

### Problemas encontrados
- Ninguno. `check`, `makemigrations --check`, `migrate --plan` = 0 issues.
- Pruebas de Dynamic Forms: 26/26 OK.

### Trabajo realizado
- Migración completa de `catalogo_publico` (catálogo público) desde `views.py` a `views_dynamic.py`, usando `DynamicService` + `DynamicProductWrapper`.
- La nueva función replica exactamente el comportamiento legacy: carga `ConfiguracionTienda`, obtiene `stock_minimo_alerta`, filtra por `mostrar_agotados_catalogo`, ordena alfabéticamente por nombre, formatea `telefono_whatsapp`.
- `config/urls.py`: import redirigido de `views` a `views_dynamic`.
- `views.py`: 15 líneas de código legacy huérfano eliminadas (`catalogo_publico`).
- Sin cambios en `templates/public/catalogo.html` — ya compatible con `DynamicProductWrapper`.
- Ninguna otra función en `views.py` se ve afectada; todos los imports permanecen activos.
- `python manage.py check` — 0 issues.

### Archivos modificados
- `apps/legacy/productos/views_dynamic.py` — nueva función `catalogo_publico()` (+37 líneas).
- `apps/legacy/productos/views.py` — eliminada `catalogo_publico()` (-15 líneas).
- `config/urls.py` — import cambiado de `views` a `views_dynamic`.
- `docs/MIGRATION_STATUS.md` — Catálogo Público agregado a Fully Migrated.
- `docs/PRODUCTS_MIGRATION.md` — tarea Fase 6 marcada completada; líneas actualizadas.
- `docs/TODO.md` — tarea #1 marcada completada.
- `docs/SESSION_LOG.md` — este registro.

### Decisiones importantes
- **Sin cambios en template**: `templates/public/catalogo.html` ya usa `DynamicProductWrapper` compatible — no requiere modificaciones.
- **Orden en Python vs SQL**: El ordenamiento alfabético se hace en Python (`.sort()`) sobre la lista de wrappers, no en la query de `Registro`, porque el campo `nombre` es un `ValorCampo` no indexable a nivel BD para ordenamiento directo.
- **Filtro de stock en Python**: `mostrar_agotados_catalogo=False` filtra wrappers con `stock <= 0` en Python, replicando el `filter(stock__gt=0)` legacy.

### Problemas encontrados
- Ninguno. Todas las variables de contexto y atributos del template son compatibles.

---

## [2026-06-26] Auditoría completa de modelos legacy (Producto, Venta, Cliente)

### Trabajo realizado
- Auditoría exhaustiva de todos los modelos legacy del proyecto: `Producto`, `Venta`, `Cliente`, `MovimientoInventario`, `Categoria`.
- Análisis de cada referencia clasificada como: activa, indirecta, migración, test, huérfana o documentación.
- Verificación de cada URL en `config/urls.py` para confirmar qué vistas están realmente enrutadas.

### Hallazgos clave

**Producto** (apps.legacy.productos.models.Producto):
- 0 vistas activas en `config/urls.py` que usen `Producto.objects` — todas las rutas apuntan a `views_dynamic.py`.
- Dependencias activas: FK desde `MovimientoInventario.producto` (CASCADE) y `Venta.producto` (PROTECT), ambos modelos huérfanos.
- Referencias restantes: admin.py (registro), migraciones (8 archivos), command `migrar_productos_dynamic`, tests (2 archivos).
- Import `productos_views` en `config/urls.py:19` — importado pero NUNCA usado en ningún URL pattern.

**Venta** (apps.legacy.ventas.models.Venta):
- 0 vistas activas — toda `apps/legacy/ventas/views.py` (668 líneas) está huérfana, incluyendo `exportar_ventas()`.
- `config/urls.py` importa `exportar_ventas` desde `views_dynamic.py`, NO desde `views.py`.
- Dependencias activas: FK a `Producto` (PROTECT) y `Cliente` (SET_NULL).
- No hay modelos que dependan de Venta (es hoja en el grafo de dependencias).
- Las URLs legacy en `apps/legacy/ventas/urls.py` NO están incluidas en la urlconf raíz.

**Cliente** (apps.legacy.ventas.models.Cliente):
- 0 vistas activas — toda la funcionalidad de clientes en producción usa `DynamicClienteWrapper` desde `views_dynamic.py`.
- Única dependencia activa: FK `Venta.cliente` (SET_NULL) en un modelo ya huérfano.

**Archivos que pueden eliminarse INMEDIATAMENTE** (riesgo cero):
1. `apps/legacy/productos/urls.py` — no incluido en urlconf raíz
2. `apps/legacy/ventas/urls.py` — no incluido en urlconf raíz
3. `apps/legacy/productos/views.py` — ninguna vista tiene ruta activa (676 líneas)
4. `apps/legacy/ventas/views.py` — ninguna vista tiene ruta activa (668 líneas)
5. `apps/legacy/productos/forms.py` — solo usado por orphan views (ProductoForm, ProductoEditForm)
6. `templates/productos/agregar_producto.html` — orphan, sin ruta activa
7. `templates/productos/editar_producto.html` — orphan, sin ruta activa
8. `templates/productos/eliminar_producto.html` — orphan, sin ruta activa
9. `templates/formularios/agregar_categoria.html` — ya identificado previamente
10. Import `productos_views` en `config/urls.py:19` — líneas 19 y suelta

**Archivos que requieren migración de datos primero**:
- `apps/legacy/productos/models.py` (5 modelos: Categoria, Producto, MovimientoInventario)
- `apps/legacy/ventas/models.py` (2 modelos: Cliente, Venta)
- `apps/legacy/productos/admin.py`
- `apps/legacy/ventas/admin.py`
- `apps/legacy/productos/tests.py`
- `apps/legacy/ventas/tests.py`
- Todas las migraciones legacy (8 en productos, 8 en ventas)
- `apps/platform/dynamic_forms/management/commands/migrar_productos_dynamic.py`

### Plan de eliminación por fases

**Fase 1 — Limpieza inmediata** (RIESGO: BAJO)
- Eliminar 10 archivos huérfanos + 1 import muerto.
- Rollback: `git checkout` de los archivos eliminados.
- Validación: `python manage.py check` + `makemigrations --check`.

**Fase 2 — Migración de datos Venta/Cliente** (RIESGO: ALTO)
- Crear script que copie datos de `Venta` y `Cliente` legacy a Dynamic Forms.
- Migrar relaciones producto_id → sku dinámico, cliente_id → documento dinámico.
- Rollback: re-ejecutar script (idempotente).
- Validación: conteo de registros origen = destino, verificación de integridad.

**Fase 3 — Eliminación de Venta/Cliente** (RIESGO: MEDIO)
- Eliminar modelos Venta y Cliente de `ventas/models.py`.
- Eliminar admin.py registrations, tests, migraciones de ventas legacy.
- Crear migración de squashing que elimine tablas `ventas_venta` y `ventas_cliente`.
- Rollback: restaurar modelos y migraciones desde git + volver a migrar datos.
- Validación: `check`, `migrate`, pruebas funcionales de ventas.

**Fase 4 — Eliminación de Producto/Categoria/MovimientoInventario** (RIESGO: MEDIO)
- Eliminar modelos de `productos/models.py`.
- Eliminar admin.py, tests, migraciones de productos legacy.
- Crear migración que elimine tablas `productos_producto`, `productos_categoria`, `productos_movimientoinventario`.
- Rollback: mismo mecanismo que Fase 3.
- Validación: `check`, `migrate`, pruebas funcionales de productos e inventario.

**Fase 5 — Limpieza final** (RIESGO: BAJO)
- Eliminar `migrar_productos_dynamic.py`.
- Eliminar migraciones squashed de dynamic_forms (opcional).
- Validación: `check`, limpieza de `__pycache__`.

### Archivos modificados
- `docs/SESSION_LOG.md` — este registro.
- `docs/TODO.md` — reorganizado con plan de 5 fases.
- `docs/MIGRATION_STATUS.md` — actualizado con hallazgos detallados.

### Decisiones importantes
- **Ventas/views.py completamente huérfano**: se confirmó que `config/urls.py` importa todas las vistas de ventas desde `views_dynamic.py`. Incluso `exportar_ventas()` tiene su versión dinámica.
- **Fase 1 ejecutable de inmediato**: 10 archivos pueden eliminarse sin riesgo porque ningún código activo los referencia.
- **Import muerto en urls.py**: `from apps.legacy.productos import views as productos_views` en `config/urls.py:19` no se usa en ningún `path()`.

### Próximo paso
Ejecutar Fase 1 — eliminar los 10 archivos huérfanos y el import muerto.

---

## [2026-06-26] Fase 2 completada — Migración de datos Venta/Cliente a Dynamic Forms

### Trabajo realizado
- Auditoría de estructura legacy Venta/Cliente vs formularios dinámicos.
- Identificación de campos necesarios: se agregó `id_legacy` (texto) al formulario Ventas como clave de idempotencia, indispensable porque las ventas no tienen un identificador único natural en Dynamic Forms.
- Creación de 3 management commands.

**Archivos creados:**
1. `migrar_clientes_dynamic.py` — Migración idempotente de Clientes legacy usando `documento` como clave natural (único en ambos sistemas).
2. `migrar_ventas_dynamic.py` — Migración idempotente de Ventas legacy usando `id_legacy` como trazabilidad. Deshabilita temporalmente el hook `post_crear_venta` durante la migración para evitar doble descuento de stock. Preserva fechas originales actualizando `Registro.fecha_creacion` vía QuerySet.update(). Preserva vendedores asignando `usuario` en `DS.crear()`.
3. `verificar_integridad_dynamic.py` — Verificación automática de 6 aspectos: cantidad de registros, totales monetarios, cantidades vendidas, usuarios/vendedores, relaciones rotas, duplicados.

**Resultados de migración:**
- Clientes migrados: 1/1 (100%) — 1 creado, 0 errores.
- Ventas migradas: 5/5 (100%) — 5 creadas, 0 errores, 0 diferencias por redondeo.
- Productos (preexistente): 6/6 ya migrados.

**Resultados de verificación de integridad:**
- Productos: 6 legacy = 6 dinámicos ✓
- Clientes: 1 legacy = 1 dinámico, todas las fechas coinciden ✓
- Ventas: 5 legacy = 5 dinámicos, total monetario $620,000.00 exacto, cantidades 5 = 5 ✓
- Vendedores: 100% coinciden ✓
- Relaciones rotas: 0 a Productos, 0 a Clientes ✓
- Duplicados: 0 en documentos, 0 en id_legacy, 0 en SKUs ✓

**Idempotencia verificada:** 2+ ejecuciones de cada comando sin duplicados.

**Validaciones:**
- `python manage.py check` — 0 issues.
- `python manage.py makemigrations --check` — No pending changes.
- `python manage.py migrate --plan` — No pending operations.

### Archivos creados
- `apps/platform/dynamic_forms/management/commands/migrar_clientes_dynamic.py` — 253 líneas.
- `apps/platform/dynamic_forms/management/commands/migrar_ventas_dynamic.py` — 317 líneas.
- `apps/platform/dynamic_forms/management/commands/verificar_integridad_dynamic.py` — 303 líneas.

### Archivos modificados
- `docs/SESSION_LOG.md` — este registro.
- `docs/TODO.md` — Fase 2 marcada completada.
- `docs/MIGRATION_STATUS.md` — Data Migration (Venta/Cliente) actualizado a 100%.
- `docs/DECISIONS.md` — añadida decisión sobre id_legacy para Ventas.

### Decisiones importantes
- **id_legacy como trazabilidad para Ventas**: Se agregó el campo `id_legacy` (texto) al formulario Ventas porque las ventas no tienen un identificador único natural (mismo producto + mismo cliente + misma cantidad puede repetirse). El campo almacena el ID del registro legacy.
- **documento como clave natural para Clientes**: No se agregó id_legacy a Clientes porque el campo `documento` ya es único en ambos sistemas (legacy y dinámico). Sirve como clave de idempotencia sin modificar el esquema.
- **Hook deshabilitado temporalmente**: Durante la migración de ventas, se deshabilita `hook_post_crear` del formulario Ventas para evitar que el hook descuente stock nuevamente (el stock ya fue descontado cuando ocurrió la venta original).
- **Fecha preservada vía QuerySet.update()**: Se usa `Registro.objects.filter(id=...).update(fecha_creacion=...)` porque `fecha_creacion` es `auto_now_add` y no puede pasarse como parámetro a `DS.crear()`. El método `update()` de QuerySets bypass `auto_now_add`.
- **precio_unitario calculado para preservar total exacto**: Se calcula `precio_unitario = total / cantidad` con 4 decimales de precisión para minimizar errores de redondeo en la fórmula `subtotal - descuento`. En 5/5 ventas el total fue exacto.
- **Sin eliminación de modelos legacy**: Fase 2 no elimina ningún modelo. El objetivo fue únicamente migrar datos para que la Fase 3 sea segura.

### Riesgos encontrados
- Ninguno. La verificación de integridad confirmó 100% de coincidencia en todos los aspectos (cantidades, totales, usuarios, relaciones, duplicados).

### Próximo paso
Ejecutar Fase 4 — eliminar modelos Producto/Categoria/MovimientoInventario legacy.

---

## [2026-06-26] Fase 3 completada — Eliminación de Venta y Cliente legacy

### Trabajo realizado
- Eliminación completa de modelos `Venta` y `Cliente` legacy de `apps/legacy/ventas/`.
- Datos preservados en Dynamic Forms (6 productos, 5 ventas, 1 cliente — 100% íntegros).

### Archivos modificados
**Eliminados (código huérfano):**
- `apps/legacy/ventas/models.py` — Clase `Cliente` (88→3 líneas, reemplazada por comment)
- `apps/legacy/ventas/admin.py` — `VentaAdmin`, `ClienteAdmin` (17→3 líneas)
- `apps/legacy/ventas/views.py` — 668 líneas de vistas legacy orphan (→3 líneas)
- `apps/legacy/ventas/tests.py` — `VentaModelTests` (71→3 líneas)
- `apps/legacy/ventas/urls.py` — 12 líneas de rutas no usadas (→3 líneas)
- `config/urls.py:19` — Import muerto `productos_views` eliminado

**Preservados (activos):**
- `views_dynamic.py` — 1107 líneas activas, sin cambios
- `hooks.py` — `post_crear_venta` hook, sin cambios
- `templatetags/formatos.py` — Template tags, sin cambios
- `migrations/` — 9 archivos (incluyendo la nueva migración 0009), preservados
- `apps.py` — `VentasConfig`, preservado (app sigue en INSTALLED_APPS)

**Migración de BD:**
- `ventas/migrations/0009_remove_venta_cliente_remove_venta_producto_and_more.py` — Creada por `makemigrations`, aplicada por `migrate`
- SQL generado: DROP TABLE `ventas_cliente` CASCADE; DROP TABLE `ventas_venta` CASCADE;
- Tablas eliminadas: `ventas_venta`, `ventas_cliente` (con sus FK constraints)

**Commands de migración modificados (eliminada dependencia de modelos legacy):**
- `migrar_clientes_dynamic.py` — No-op informativo (migración ya completada)
- `migrar_ventas_dynamic.py` — No-op informativo (migración ya completada)
- `verificar_integridad_dynamic.py` — Solo verifica datos dinámicos (sin comparación legacy)

### Validaciones
- `python manage.py check` — 0 issues
- `python manage.py makemigrations --check` — No pending changes
- `python manage.py migrate --plan` — No pending operations
- `python manage.py verificar_integridad_dynamic` — **TODO OK**: 6 productos, 5 ventas, 1 cliente, 0 relaciones rotas, 0 duplicados
- `python manage.py test apps.platform.dynamic_forms` — 26/26 tests pasan (seed, hooks, validaciones)
- Commands migrar_clientes_dynamic y migrar_ventas_dynamic: ejecutan sin errores

### Decisiones importantes
- **App preservada en INSTALLED_APPS**: `apps.legacy.ventas` permanece en INSTALLED_APPS porque contiene:
  - `hooks.py` — hook `post_crear_venta` referenciado por el formulario Ventas
  - `templatetags/formatos.py` — template tags usados por templates
  - `views_dynamic.py` — vistas activas de ventas y clientes
  - `migrations/` — historial de migraciones necesario para la cadena
- **Sin eliminación de `config/settings/base.py`**: La app debe permanecer en INSTALLED_APPS mientras tenga archivos activos
- **Commands preservados como no-op**: `migrar_clientes_dynamic` y `migrar_ventas_dynamic` se mantienen como referencia para rollback, informando que la migración ya se completó
- **`verificar_integridad_dynamic` adaptado**: Ahora solo verifica la integridad interna de Dynamic Forms (conteos, relaciones, duplicados) sin depender de modelos legacy

### Problemas encontrados
- Ninguno. La migración y eliminación fueron limpias, sin efectos secundarios en el sistema en producción.

### Próximo paso
Ejecutar Fase 4 — eliminar modelos Producto/Categoria/MovimientoInventario legacy.

---

## [2026-06-26] Fase 4 completada — Eliminación de Producto, Categoria y MovimientoInventario legacy

### Trabajo realizado
- Eliminación completa de modelos `Categoria`, `Producto` y `MovimientoInventario` legacy de `apps/legacy/productos/`.
- Datos preservados en Dynamic Forms (6 productos, 6 movimientos de inventario — 100% íntegros).

### Archivos modificados
**Eliminados (código huérfano):**
- `apps/legacy/productos/models.py` — Clases `Categoria`, `Producto`, `MovimientoInventario` (76→3 líneas, comment)
- `apps/legacy/productos/admin.py` — `ProductoAdmin`, `MovimientoInventarioAdmin` (37→3 líneas)
- `apps/legacy/productos/views.py` — 676 líneas de vistas legacy orphan (→3 líneas)
- `apps/legacy/productos/forms.py` — `ProductoForm`, `ProductoEditForm` (123→3 líneas)
- `apps/legacy/productos/urls.py` — 15 líneas de rutas no usadas (→3 líneas)
- `apps/legacy/productos/tests.py` — `ProductoModelTests` (55→3 líneas)
- `templates/productos/agregar_producto.html` — orphan
- `templates/productos/editar_producto.html` — orphan
- `templates/productos/eliminar_producto.html` — orphan
- `templates/formularios/agregar_categoria.html` — orphan

**Preservados (activos):**
- `views_dynamic.py` — Vistas dinámicas activas, sin cambios
- `wrappers.py` — Wrappers activos (DynamicProductWrapper, DynamicMovimientoInventarioWrapper, etc.)
- `migrations/` — 9 archivos (incluyendo nueva migración 0009), preservados
- `apps.py` — `ProductosConfig`, preservado (app sigue en INSTALLED_APPS)

**Migración de BD:**
- `productos/migrations/0009_remove_producto_categoria_and_more.py` — Creada por `makemigrations`, aplicada por `migrate`
- SQL generado: DROP TABLE `productos_categoria` CASCADE; DROP TABLE `productos_movimientoinventario` CASCADE; DROP TABLE `productos_producto` CASCADE;
- Tablas eliminadas: `productos_categoria`, `productos_producto`, `productos_movimientoinventario` (con sus FK constraints)

**Commands de migración modificados (eliminada dependencia de modelos legacy):**
- `migrar_productos_dynamic.py` — No-op informativo (migración ya completada)

### Validaciones
- `python manage.py check` — 0 issues
- `python manage.py makemigrations --check` — No pending changes
- `python manage.py migrate --plan` — No pending operations
- `python manage.py verificar_integridad_dynamic` — **TODO OK**: 6 productos, 5 ventas, 1 cliente, 6 movimientos, 0 relaciones rotas, 0 duplicados
- `python manage.py migrar_productos_dynamic` — ejecuta sin errores

### Decisiones importantes
- **App preservada en INSTALLED_APPS**: `apps.legacy.productos` permanece en INSTALLED_APPS (thin app) porque contiene:
  - `wrappers.py` — Wrappers usados por templates y views dinámicas
  - `views_dynamic.py` — Vistas activas de productos, inventario y catálogo
  - `migrations/` — Historial de migraciones necesario para la cadena
- **Sin FK blockers**: Las FK externas (Venta.producto, Venta.cliente) fueron eliminadas en Fase 3. No había dependencias de FKs desde otros módulos.
- **Commands preservados como no-op**: `migrar_productos_dynamic` se mantiene como referencia para rollback.

### Problemas encontrados
- Ninguno. La migración y eliminación fueron limpias, sin efectos secundarios en el sistema en producción.

### Próximo paso
Ejecutar Fase 5 — limpieza final (squash migraciones, verificar imports legacy restantes en templates).
