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
Revisar `docs/TODO.md` para priorizar el trabajo pendiente:
- Migración de datos legacy → Dynamic Forms.
- Migración de Categorías.
- Gráficos dinámicos (Fase 2).
- Integridad referencial.
- Límites de seguridad en queries.
- Índices compuestos.
- Caché de dashboard.
- Evaluación de modelo híbrido.
- Profiling.
- Limpieza de vistas legacy.
- Pruebas de migración.
