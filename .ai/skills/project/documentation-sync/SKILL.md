---
name: documentation-sync
description: >-
  Specialist in keeping project documentation synchronized. Automatically
  updates SESSION_LOG.md, TODO.md, MIGRATION_STATUS.md, and DECISIONS.md
  after code changes to ensure docs always reflect the current project state.
license: MIT
compatibility: opencode
metadata:
  audience: developer
  workflow: documentation
---

# Documentation Sync Skill

## Inspired by

This skill follows the structure defined in the [Anthropic Agent Skills
specification](https://github.com/anthropics/skills) and the
[opencode-skills](https://github.com/malhashemi/opencode-skills) community
repository.

---

## Overview

This skill ensures that after every code modification, the four core
documentation files are updated to reflect the new state. Run this as the
final step of any task that modifies code.

---

## Files to Maintain

### 1. `docs/SESSION_LOG.md`

Always update. Append a new entry with:

**Entry format:**
```markdown
## [YYYY-MM-DD] Brief title

### Trabajo realizado
- Bullet list of what was done

### Archivos modificados
- Paths to modified files (relative to project root)

### Decisiones importantes
- Only if new decisions were taken

### Problemas encontrados
- Obstacles, bugs discovered, unresolved issues

### Próximo paso
- What should be done next
```

**Rules:**
- Date in `YYYY-MM-DD` format
- One entry per session
- Never modify previous entries
- Be specific about file paths

### 2. `docs/TODO.md`

Update when a task's state changes:

- **Task completed** → Change state to `Completada`
- **Task cancelled** → Change state to `Cancelada` and note why
- **New task discovered** → Add it with the appropriate priority
- **Priority changes** → Move the task up/down

**Rules:**
- Never remove tasks (use `Cancelada` state)
- Keep the priority sections (Alta, Media, Baja)
- Reference the source file that justifies the task

### 3. `docs/MIGRATION_STATUS.md`

Update only when a migration is completed or its status changes:

- Move module from "Partially Migrated" to "Fully Migrated"
- Update percentage estimates
- Update "Remaining Migration Work" section
- Update "Completion Estimates" table

**Rules:**
- Only touch this file when migration status actually changes
- Never speculate — only update based on completed work

### 4. `docs/DECISIONS.md`

Update when a new architectural decision is made:

**Entry format:**
```markdown
## Decision: Title

**Decision**: Concise description of what was decided.

**Reason**: Why this decision was made.

**Current status**: Implemented / In progress / Planned.
```

**Rules:**
- One entry per decision
- Include the rationale
- Be specific about scope and impact

---

## Sync Flow

```
Code changes completed
        │
        ▼
SESSION_LOG.md ← Always (new entry)
        │
        ├── Did a TODO task complete?  → Update TODO.md
        ├── Did a migration progress?  → Update MIGRATION_STATUS.md
        └── Was an architectural
            decision made?             → Update DECISIONS.md
```

---

## When to Use This Skill

- After completing any code modification
- Before committing changes
- When closing a pull request
- After running migrations
- After adding new dependencies or configuration
- After creating or modifying documentation

---

## Related Files

| File | Purpose |
|------|---------|
| `docs/SESSION_LOG.md` | Session history |
| `docs/TODO.md` | Task list |
| `docs/MIGRATION_STATUS.md` | Migration progress |
| `docs/DECISIONS.md` | Architectural decisions |
| `docs/AGENT_CONTEXT.md` | Working Protocol (rules for updating) |
