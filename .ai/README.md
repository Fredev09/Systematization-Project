# AI Infrastructure — Tonjeo

Este directorio contiene la infraestructura de **Skills** y **Playbooks**
para que los agentes de IA trabajen de forma estructurada y reproducible
en el proyecto. Es agnóstico al agente (OpenCode, Claude Code, Cline,
etc.).

---

## ¿Qué es una Skill?

Una **Skill** es un conjunto de instrucciones y recursos que le indican
a un agente de IA cómo abordar una tarea específica. Incluye:

- Instrucciones detalladas paso a paso.
- Archivos de referencia (plantillas, ejemplos, configuraciones).
- Reglas y restricciones propias de la tarea.

Cuando un agente carga una Skill, obtiene contexto especializado que le
permite ejecutar la tarea correctamente sin necesidad de que se le
explique todo desde cero cada vez.

---

## Organización

```
.ai/
├── README.md            ← Este archivo
├── skills/
│   ├── community/       ← Skills de la comunidad (no modificar)
│   ├── project/         ← Skills propias del proyecto
│   └── README.md        ← Índice de todas las Skills disponibles
└── playbooks/
    └── README.md        ← Documentación de playbooks
```

---

## Diferencia entre community y project

| Carpeta | Propósito |
|---------|-----------|
| `skills/community/` | Skills obtenidas de la comunidad. No deben modificarse. Si se necesita una variante, copiar a `project/` y adaptar. |
| `skills/project/` | Skills propias del proyecto. Creadas específicamente para las necesidades de Tonjeo. Pueden ser nuevas o variantes de community adaptadas al proyecto. |

### Reglas

- **No modificar** Skills en `community/`. Si requieres cambios,
  cópialas a `project/` y modifica la copia.
- **Documentar** cada Skill en `skills/README.md` con una breve
  descripción y su ruta.
- **Nombrar** los archivos de Skill con el formato
  `nombre-descriptivo.md` (kebab-case).

---

## Cómo debe usar las Skills un agente

Antes de modificar código, el agente DEBE:

1. **Revisar `skills/README.md`** para conocer las Skills disponibles.
2. **Identificar si existe una Skill** que cubra la tarea a realizar.
3. **Cargar la Skill** mediante la herramienta correspondiente antes
   de empezar a implementar.
4. **Seguir las instrucciones** de la Skill como guía principal.
5. **Actualizar `docs/SESSION_LOG.md`** al finalizar, registrando qué
   Skills se utilizaron.

Si no existe una Skill para la tarea, se debe considerar crearla en
`skills/project/` y registrarla en `skills/README.md`.

---

## Playbooks

Los **Playbooks** (en `playbooks/`) son documentos que describen
flujos de trabajo completos y repetibles para procesos complejos del
proyecto (por ejemplo: "Despliegue completo", "Migración de datos
legacy", "Nueva release"). Cada playbook combina múltiples Skills
y pasos manuales en una secuencia documentada.

Ver `playbooks/README.md` para más detalle.
