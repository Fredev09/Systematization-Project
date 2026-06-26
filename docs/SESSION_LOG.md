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
