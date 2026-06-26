# Playbooks del Proyecto

Este documento describe cómo funcionan los **Playbooks** en Tonjeo.

---

## ¿Qué es un Playbook?

Un **Playbook** es una secuencia documentada de pasos que combina
múltiples Skills, tareas manuales y verificaciones para ejecutar un
proceso complejo de principio a fin.

A diferencia de una Skill (que se enfoca en una tarea específica),
un Playbook orquesta varias Skills y pasos para lograr un objetivo
mayor: despliegue, migración completa, release, etc.

---

## Estructura de un Playbook

Cada Playbook es un archivo Markdown en `.ai/playbooks/` que contiene:

```yaml
---
title: Nombre del Playbook
objetivo: Descripción del objetivo principal
disparadores: Cuándo o por qué se ejecuta este playbook
skills_necesarias: Lista de Skills que se requieren
duracion_estimada: Tiempo estimado de ejecución
---

## Prerrequisitos
- Estado del proyecto antes de comenzar.
- Variables de entorno o configuraciones necesarias.

## Pasos
1. **Paso 1** — Descripción y referencias a Skills.
2. **Paso 2** — ...
N. **Paso N** — Verificación final.

## Criterios de éxito
- Lista de condiciones que deben cumplirse para dar por terminado
  el playbook.

## Rollback
- Pasos para deshacer el playbook en caso de error.
```

---

## Playbooks Disponibles

### migracion-completa
- **Ruta**: `.ai/playbooks/migracion-completa.md`
- **Objetivo**: Migrar un módulo legacy completo a Dynamic Forms EAV
- **Skills requeridas**: `migration`, `migrate-module`, `dynamic-forms`, `create-wrapper`, `build-dynamic-view`, `documentation-sync`
- **Duración estimada**: 2-4 horas por módulo

### nuevo-modulo-dinamico
- **Ruta**: `.ai/playbooks/nuevo-modulo-dinamico.md`
- **Objetivo**: Crear un módulo completo desde cero usando Dynamic Forms EAV
- **Skills requeridas**: `dynamic-forms`, `create-wrapper`, `build-dynamic-view`, `dynamic-query`, `ui-consistency`, `documentation-sync`
- **Duración estimada**: 3-5 horas por módulo

---

## Reglas

1. **Versionar**: Los playbooks se versionan junto con el código.
2. **Secuencia lineal**: Los pasos se ejecutan en orden, sin saltos.
3. **Skills como bloques**: Cada paso que requiere automatización
   debe delegar en una Skill existente.
4. **Criterios de éxito explícitos**: Cada playbook define condiciones
   verificables para considerar la ejecución exitosa.
5. **Rollback obligatorio**: Todo playbook debe incluir pasos de
   reversión.

---

## Flujo de uso

1. El agente lee el Playbook completo antes de empezar.
2. Verifica los prerrequisitos.
3. Ejecuta los pasos en orden, cargando las Skills indicadas.
4. Al finalizar, verifica los criterios de éxito.
5. Actualiza `docs/SESSION_LOG.md` documentando la ejecución.
