---
title: Migración Completa Legacy → Dynamic Forms
objetivo: Migrar un módulo legacy completo (modelo, vistas, URLs) a Dynamic Forms EAV
disparadores: Se decide migrar un módulo legacy existente a Dynamic Forms
skills_necesarias:
  - migration
  - migrate-module
  - dynamic-forms
  - create-wrapper
  - build-dynamic-view
  - documentation-sync
duracion_estimada: 2-4 horas por módulo
---

## Prerrequisitos

- Dynamic Forms instalado y funcionando (`sembrar_formularios_base` ejecutado)
- Conocimiento del modelo legacy: campos, tipos, relaciones, side effects en `save()`
- `docs/MIGRATION_STATUS.md` revisado para conocer el estado actual
- Entorno local con datos de prueba del módulo legacy

## Pasos

### 1. Analizar el modelo legacy

Identificar en `models.py`:
- Todos los campos y sus tipos (CharField, DecimalField, ForeignKey, etc.)
- Métodos `save()` con side effects (stock, auditoría, notificaciones)
- Propiedades computadas (`@property`) que deben replicarse en el wrapper
- Relaciones con otros modelos (FK, M2M)

**Skill**: `dynamic-forms` — secciones Key Concepts y Project Conventions.

### 2. Definir el formulario dinámico

En `apps/platform/dynamic_forms/services_dynamic.py`:
- Agregar constante `FORM_MI_MODULO = 'MiModulo'`
- Agregar `Campo` definitions en `sembrar_formularios_base` para cada campo legacy
- Ejecutar `python manage.py sembrar_formularios_base` para materializar en BD

**Skill**: `migrate-module` — paso 1 (Define the form constant).

### 3. Crear el wrapper

En `apps/legacy/<modulo>/wrappers.py`:
- Crear clase `DynamicMiModuloWrapper` con constructor `(registro, valores_dict)`
- Mapear cada campo legacy como `@property` con safe defaults
- Implementar conversiones de tipo (`_decimal()`, `_entero()`, etc.)
- Replicar propiedades computadas del modelo legacy

**Skill**: `create-wrapper` — patrones de wrappers existentes.

### 4. Crear hook (si aplica)

Si el modelo legacy tiene side effects en `save()`:
- Crear `apps/legacy/<modulo>/hooks.py`
- Implementar `post_crear_mi_modulo(registro)` con la lógica de negocio
- Usar `select_for_update()` para operaciones sensibles (stock, saldos)
- Registrar el hook en el formulario mediante management command

**Skill**: `migrate-module` — paso 3 (Create the hook if side effects exist).

### 5. Implementar vistas dinámicas

En `apps/legacy/<modulo>/views_dynamic.py`:

- **Lista**: `DS.filtrar()` + `DS.cargar_valores_mapa()` + wrappers + paginación
- **Crear**: construir `valores` desde `request.POST`, llamar `DS.crear()` con manejo de `ValidacionError`
- **Editar**: `DS.obtener_valores()`, presentar formulario, `DS.actualizar()` en POST
- **Eliminar**: verificar relaciones, `DS.eliminar()`, manejar `ProtectedError`

**Skills**: `build-dynamic-view` — patrones CRUD; `dynamic-query` — optimización N+1.

### 6. Actualizar routing

En `config/urls.py`:
- Reemplazar imports de `views.py` legacy por `views_dynamic.py`
- Mantener imports legacy comentados como respaldo
- Verificar que los nombres de ruta (`name='...'`) coincidan con los templates

### 7. Verificar templates

- Navegar cada vista (lista, crear, editar, detalle, eliminar)
- Verificar que los nombres de campo en templates coincidan con las propiedades del wrapper
- Confirmar que botones y enlaces apuntan a las URLs correctas
- Probar responsive y mensajes de error/éxito

**Skills**: `ui-consistency` — patrones Bootstrap 5; `ui-polish` — revisión visual.

### 8. Documentar

Actualizar archivos de documentación:
- `docs/MIGRATION_STATUS.md` — marcar módulo como migrado
- `docs/SESSION_LOG.md` — nueva entrada con resumen del trabajo
- `docs/TODO.md` — marcar tarea correspondiente como completada
- `docs/DECISIONS.md` — si se tomó alguna decisión arquitectónica

**Skill**: `documentation-sync` — actualización de todos los archivos de documentación.

## Criterios de éxito

- [ ] Todas las vistas del módulo funcionan con datos de Dynamic Forms
- [ ] Wrapper emula correctamente la interfaz del modelo legacy
- [ ] Hooks ejecutan side effects correctamente (si aplica)
- [ ] No hay regresiones en funcionalidad existente
- [ ] `DS.cargar_valores_mapa()` usado en listas (sin N+1)
- [ ] Manejo de errores visible al usuario (`messages.error`)
- [ ] Templates se renderizan sin errores
- [ ] Documentación actualizada

## Rollback

1. Revertir `config/urls.py` a los imports de vistas legacy
2. Comentar o eliminar hooks del formulario en management command
3. Ejecutar migración inversa si se agregaron campos a la BD
4. Verificar que las vistas legacy funcionan correctamente
5. Revertir cambios en documentación
