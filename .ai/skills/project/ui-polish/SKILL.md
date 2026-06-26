---
name: ui-polish
description: >-
  Specialist in visual review for the Tonjeo project. Checks spacing, margins,
  padding, alignment, Bootstrap usage, responsive design, visual consistency,
  accessibility, tables, forms, and buttons.
license: MIT
compatibility: opencode
metadata:
  audience: developer
  workflow: review
---

# UI Polish Skill

## Inspired by

This skill follows the structure defined in the [Anthropic Agent Skills
specification](https://github.com/anthropics/skills) and the
[opencode-skills](https://github.com/malhashemi/opencode-skills) community
repository.

---

## Review Checklist

### Spacing & Layout

- [ ] Are vertical spacings consistent between sections (use Bootstrap
      spacing utilities: `my-*`, `py-*`)?
- [ ] Are horizontal paddings uniform across cards and containers
      (`p-*`, `px-*`)?
- [ ] Is there unnecessary whitespace or missing spacing between elements?
- [ ] Are flex/grid gaps consistent (`gap-*`)?
- [ ] Do modals and cards use consistent internal padding?

### Bootstrap Usage

- [ ] Are Bootstrap 5 utility classes preferred over custom CSS where
      possible?
- [ ] Are `container`, `row`, and `col` used correctly for layout?
- [ ] Are responsive breakpoints applied (`col-md-*`, `col-lg-*`)?
- [ ] Are Bootstrap components (cards, tables, modals, alerts, navs) used
      with correct markup?
- [ ] Is the project's custom CSS in `static/` overriding Bootstrap properly
      (not duplicating it)?

### Responsive Design

- [ ] Do layouts work on mobile viewports (<768px)?
- [ ] Are tables horizontally scrollable on small screens (`table-responsive`)?
- [ ] Are form inputs full-width on mobile?
- [ ] Do modals display correctly on small screens?
- [ ] Are navigation elements collapsible on mobile?

### Visual Consistency

- [ ] Do all pages use the same color scheme (Tonjeo palette)?
- [ ] Are button variants consistent (`btn-primary`, `btn-secondary`,
      `btn-danger`)?
- [ ] Are font sizes consistent across headings and body text?
- [ ] Do alerts and notifications use consistent styling?
- [ ] Are icons consistent (Bootstrap Icons or Font Awesome)?
- [ ] Is the dark mode toggle working and visually coherent?

### Accessibility

- [ ] Do all form inputs have associated `<label>` elements?
- [ ] Are color contrasts sufficient (WCAG AA minimum)?
- [ ] Do images have `alt` text?
- [ ] Are buttons and links focusable and visible on focus?
- [ ] Are error messages clearly associated with their inputs?

### Tables

- [ ] Do tables have `table-striped` or `table-hover` classes?
- [ ] Are long tables wrapped in `table-responsive`?
- [ ] Are action columns consistently placed (usually last column)?
- [ ] Do empty states show a helpful message instead of a blank table?
- [ ] Are sort indicators used where applicable?

### Forms

- [ ] Are labels consistently positioned (above inputs for the project)?
- [ ] Are validation errors displayed inline near the relevant field?
- [ ] Are required fields visually marked?
- [ ] Do disabled/read-only fields have distinct styling?
- [ ] Are submit buttons clearly labeled and consistently positioned?

### Buttons

- [ ] Do actions have clear labels (not just icons alone)?
- [ ] Are destructive actions styled with `btn-danger`?
- [ ] Is button placement consistent (save/submit at bottom right, cancel
      adjacent)?
- [ ] Are loading states indicated during async operations?
- [ ] Do icon buttons have accessible labels or tooltips?

---

## When to Use This Skill

- After implementing new templates or UI components
- Before a release or deployment
- When fixing visual bugs
- When reviewing a pull request with UI changes
- When adding new form pages or modals

---

## Related Files

| File | Purpose |
|------|---------|
| `static/` | Custom CSS organized by module |
| `templates/` | Django templates by module |
| `apps/shared/configuracion/models.py` | Dark/light theme config |
| `docs/AGENT_CONTEXT.md` | Project conventions |
