# AI Workflow

Flujo recomendado para trabajar con agentes de IA en este proyecto.

---

## Pasos

### 1. Leer AGENT_CONTEXT.md
Entender la arquitectura, convenciones, reglas y el protocolo de
documentación antes de cualquier modificación.

### 2. Leer MIGRATION_STATUS.md
Identificar qué módulos están migrados, cuáles están en transición
y cuáles son todavía legacy.

### 3. Leer TODO.md
Revisar las tareas pendientes organizadas por prioridad para saber
qué corresponde hacer y en qué orden.

### 4. Realizar auditoría si es necesaria
Si el cambio lo requiere, inspeccionar el código relevante
(views, wrappers, hooks, templates, servicios) para entender el
estado actual antes de modificar.

### 5. Implementar cambios
Escribir o modificar código siguiendo las convenciones del proyecto
(ver `CODING_GUIDELINES.md` y `AGENT_CONTEXT.md`).

### 6. Ejecutar validaciones
- Verificar que el código sigue las reglas del proyecto.
- Ejecutar pruebas si existen.
- Verificar que no se rompe la compatibilidad con wrappers/templates.

### 7. Actualizar la documentación correspondiente
Siguiendo el **Working Protocol** de `AGENT_CONTEXT.md`:
- `SESSION_LOG.md` — siempre.
- `TODO.md` — si cambia estado de tareas.
- `MIGRATION_STATUS.md` — si se completa una migración.
- `DECISIONS.md` — si se toma una decisión arquitectónica.

---

## Diagrama

```
[1. AGENT_CONTEXT.md] → [2. MIGRATION_STATUS.md] → [3. TODO.md]
                             │
                    ┌────────┴────────┐
                    │                 │
             [4. Auditoría]    [Saltar a 5]
                    │                 │
                    └────────┬────────┘
                             │
                    [5. Implementar cambios]
                             │
                    [6. Ejecutar validaciones]
                             │
                    [7. Actualizar documentación]
```
