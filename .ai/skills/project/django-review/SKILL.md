---
name: django-review
description: >-
  Specialist in Django code review for the Tonjeo project. Checks N+1 queries,
  permissions, imports, URLs, views, templates, forms, and consistency with
  project conventions and architecture.
license: MIT
compatibility: opencode
metadata:
  audience: developer
  workflow: review
---

# Django Review Skill

## Inspired by

This skill follows the structure defined in the [Anthropic Agent Skills
specification](https://github.com/anthropics/skills) and the
[opencode-skills](https://github.com/malhashemi/opencode-skills) community
repository.

---

## Review Checklist

### N+1 Queries

- [ ] Are list views using `DS.cargar_valores_mapa(registros)` for bulk loads?
- [ ] Is there any loop calling `DS.obtener_valor()` per record?
- [ ] Are `select_related()` / `prefetch_related()` used for FK fields when
      accessing related models directly?
- [ ] Are template loops accessing related objects without prefetching?

### Permissions

- [ ] Are all business views decorated with `@login_required`?
- [ ] Are admin-only views decorated with `@admin_required` (from
      `config/permissions.py`)?
- [ ] Is `request.user.is_authenticated` checked where decorators are not used?
- [ ] Are permission checks consistent with the module's sensitivity?

### Imports

- [ ] Is `DynamicService` imported as `DS`?
      (`from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS`)
- [ ] Are imports from the correct app path (dotted from `apps.*`)?
- [ ] Are there any unused imports?
- [ ] Are imports from legacy models clearly marked as legacy?

### URLs

- [ ] Do URLs follow the pattern `/module/action/<id>/`?
- [ ] Are `app_name` and `name` set for `{% url %}` resolution?
- [ ] Are dynamic views imported from `views_dynamic`, not `views`?
- [ ] Are legacy category URLs (`agregar_categoria`, `crear_categoria`)
      still present but marked as pending migration?

### Views

- [ ] Do views return `HttpResponse` / `render` / `redirect` (not JSON)?
- [ ] Are dynamic views using `DS` methods for CRUD?
- [ ] Are wrappers constructed with `DS.cargar_valores_mapa()` output?
- [ ] Are form submissions validated before calling `DS.crear()` /
      `DS.actualizar()`?
- [ ] Are file uploads handled via `request.FILES` and passed to
      `DS.crear(archivos=...)`?
- [ ] Is `transaction.atomic()` present where hooks run?
- [ ] Do delete views catch `ProtectedError` for referential integrity?

### Templates

- [ ] Do templates access wrapper attributes directly (`{{ producto.nombre }}`)?
- [ ] Are Django template filters (`|date`, `|time`, `formato_pesos`) used
      correctly?
- [ ] Is the `config` object (from `configuracion_tienda` context processor)
      available?
- [ ] Are there hardcoded URLs instead of `{% url %}` tags?
- [ ] Are form fields using the correct input types and Bootstrap classes?

### Forms (Django)

- [ ] Are legacy Django ModelForms still referencing legacy models?
- [ ] If processing dynamic forms, is the data extracted as a `valores` dict
      from `request.POST`?

### Project Consistency

- [ ] Does the code follow the naming conventions (Spanish for UI, English
      for code)?
- [ ] Does the code avoid Django REST Framework / JSON endpoints?
- [ ] Does the code preserve legacy models (never delete, only add)?
- [ ] Does the code respect wrapper interfaces (no breaking attribute changes)?
- [ ] Are new form constants added to `services_dynamic.py`?

---

## When to Use This Skill

- Before submitting a pull request
- After completing a feature implementation
- When debugging a production issue
- When onboarding to review other developers' code
- Before merging migration-related changes

---

## Related Files

| File | Purpose |
|------|---------|
| `docs/CODING_GUIDELINES.md` | Full coding conventions |
| `docs/AGENT_CONTEXT.md` | Project rules and architecture |
| `apps/platform/dynamic_forms/services_dynamic.py` | DS reference |
| `apps/legacy/productos/wrappers.py` | Wrapper patterns |
| `config/urls.py` | URL routing reference |
