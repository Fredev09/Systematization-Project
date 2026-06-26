---
title: Creación de Nuevo Módulo Dinámico
objetivo: Crear un módulo completo desde cero usando Dynamic Forms EAV
disparadores: Se requiere una nueva funcionalidad que no existe como modelo legacy
skills_necesarias:
  - dynamic-forms
  - create-wrapper
  - build-dynamic-view
  - dynamic-query
  - ui-consistency
  - documentation-sync
duracion_estimada: 3-5 horas por módulo
---

## Prerrequisitos

- Dynamic Forms operativo con `sembrar_formularios_base` ejecutado
- Especificación clara de los campos del nuevo módulo
- Familiaridad con los patrones de vista en `views_dynamic.py` existentes
- Bootstrap 5 disponible en los templates

## Pasos

### 1. Definir el formulario

En `apps/platform/dynamic_forms/services_dynamic.py`:
- Agregar constante `FORM_NUEVO_MODULO = 'NuevoModulo'`
- Agregar definiciones de `Campo` con tipos apropiados (`texto`, `numero`, `fecha`, `lista`, `relacion`, `calculado`)
- Ejecutar `python manage.py sembrar_formularios_base`

**Skill**: `dynamic-forms` — sección DynamicService y Project Conventions.

### 2. Crear wrapper

En `apps/legacy/<modulo>/wrappers.py`:
- Crear clase wrapper con constructor `(registro, valores_dict)`
- Proveer propiedades para cada campo con safe defaults
- Implementar conversiones de tipo necesarias
- Agregar propiedades computadas si el módulo las requiere

**Skill**: `create-wrapper` — patrones de DynamicProductWrapper, DynamicClienteWrapper.

### 3. Crear hook (opcional)

Si el módulo requiere lógica de negocio post-create/post-update:
- Crear `apps/legacy/<modulo>/hooks.py`
- Implementar hooks con `transaction.atomic()` y `select_for_update()` si es necesario
- Registrar en el formulario mediante management command

**Skill**: `migrate-module` — paso 3 (Hook pattern); referencia: `apps/legacy/ventas/hooks.py`.

### 4. Implementar vistas

En `apps/legacy/<modulo>/views_dynamic.py`:

**Vistas mínimas requeridas:**
- `listar_<modulo>` — listado paginado con filtros
- `agregar_<modulo>` — formulario de creación
- `editar_<modulo>` — formulario de edición
- `eliminar_<modulo>` — confirmación y eliminación

**Optimizaciones:**
- `DS.cargar_valores_mapa()` para carga masiva en listas
- Filtros en Python post-carga para lógica compleja
- `top()` y `sumar()` para agregaciones si aplica

**Skills**: `build-dynamic-view` — patrones CRUD; `dynamic-query` — filtros y agregaciones.

### 5. Crear templates

En `templates/<modulo>/`:
- `<modulo>_lista.html` — tabla Bootstrap 5 responsive
- `<modulo>_formulario.html` — formulario con validación
- `<modulo>_confirmar_eliminar.html` — confirmación

**Skill**: `ui-consistency` — patrones Bootstrap 5, tablas, formularios, botones.

### 6. Registrar URLs

En `config/urls.py`:
- Agregar rutas para lista, crear, editar, eliminar
- Usar nombres de ruta consistentes con el proyecto

### 7. Probar

- Crear, editar, listar y eliminar registros
- Verificar validaciones y mensajes de error
- Confirmar que no hay N+1 queries
- Probar responsive en mobile

**Skill**: `ui-polish` — revisión visual completa.

### 8. Documentar

- `docs/SESSION_LOG.md` — nueva entrada
- `docs/MIGRATION_STATUS.md` — agregar nuevo módulo como completado
- `docs/TODO.md` — actualizar si aplica

**Skill**: `documentation-sync`.

## Criterios de éxito

- [ ] Formulario creado y sembrado en BD
- [ ] Wrapper funcional con safe defaults
- [ ] CRUD completo operativo (crear, leer, editar, eliminar)
- [ ] Templates responsivos con Bootstrap 5
- [ ] Sin N+1 queries en vista de lista
- [ ] Manejo de errores (`ValidacionError`) visible al usuario
- [ ] Hooks ejecutan lógica de negocio correctamente (si aplica)

## Rollback

1. Eliminar rutas de `config/urls.py`
2. Eliminar o comentar definiciones de `Campo` en `sembrar_formularios_base`
3. Eliminar archivos creados (`views_dynamic.py`, `wrappers.py`, `hooks.py`, templates)
4. Ejecutar `sembrar_formularios_base` para limpiar formulario de la BD
5. Revertir documentación
