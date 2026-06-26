---
name: ui-consistency
description: >-
  Maintains visual consistency following the Bootstrap patterns actually used
  in the project's templates. Covers stat cards, tables, forms, buttons,
  pagination, empty states, responsive tables, and the Tonjeo color palette.
  Based on real patterns in base.html, dashboard.html, productos.html,
  historial_ventas.html, and all templates/ files.
license: MIT
compatibility: opencode
metadata:
  audience: developer
  module: ui
  real_files: templates/base/base.html, templates/dashboard/dashboard.html
---

# ui-consistency

Maintains visual consistency across all templates following the real
Bootstrap 5 patterns used throughout the project.

## When to use

- Creating a new template for a dynamic view.
- Adding new UI components (cards, tables, forms).
- Fixing visual inconsistencies between pages.
- Reviewing a pull request with UI changes.

## When NOT to use

- Creating a completely new visual design (use `frontend-design` community skill).
- Backend-only changes (no template modifications).

## Real project patterns

The project uses **Bootstrap 5.3.3** loaded via CDN in `base.html`:
```html
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
```

Custom CSS lives in `static/css/` organized by module (19 CSS files).

## Pattern: Page structure

Every page extends `base/base.html` and follows this structure:

```html
{% extends 'base/base.html' %}
{% load static %}

{% block titulo %}Page Title | Tonjeo{% endblock %}

{% block estilos %}
<link rel="stylesheet" href="{% static 'css/modulo/modulo.css' %}">
{% endblock %}

{% block contenido %}
<!-- 1. Page header with title + actions -->
<section class="page-header">
    <header>
        <h1>Título</h1>
        <p>Subtítulo o descripción</p>
    </header>
    <nav class="header-actions">
        <a href="..." class="btn btn-primary"><i class="fas fa-plus"></i> Acción</a>
    </nav>
</section>

<!-- 2. Stats cards (optional) -->
<section class="stats-grid">
    <article class="stat-card">...</article>
</section>

<!-- 3. Content (table, form, etc.) -->
<section class="table-responsive">
    <table class="table">...</table>
</section>

<!-- 4. Pagination (if list) -->
{% endblock %}
```

## Pattern: Stats cards

```html
<section class="stats-grid">
    <article class="stat-card">
        <section class="stat-icon primary">
            <i class="fas fa-coins"></i>
        </section>
        <section>
            <span>Label</span>
            <h3>{{ value|formato_pesos }}</h3>
            <p>Subtexto</p>
        </section>
    </article>
</section>
```

Color variants: `primary` (blue), `accent` (orange/pink), `info` (teal),
`warning` (yellow/amber).

## Pattern: Tables

Tables use the `table` class with optional `table-stagger` for dashboard:

```html
<section class="table-responsive">
    <table class="table table-stagger">
        <thead>
            <tr>
                <th>Columna</th>
                <th>Acciones</th>
            </tr>
        </thead>
        <tbody>
            {% for item in items %}
            <tr>
                <td>{{ item.nombre }}</td>
                <td>
                    <a href="{% url 'editar' item.id %}" class="btn-edit">
                        <i class="fas fa-edit"></i>
                    </a>
                    <a href="{% url 'eliminar' item.id %}" class="btn-delete">
                        <i class="fas fa-trash"></i>
                    </a>
                </td>
            </tr>
            {% empty %}
            <tr>
                <td colspan="100%" class="empty-row">
                    <p class="empty-text">No hay registros.</p>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</section>
```

## Pattern: Action buttons

```html
<nav class="header-actions">
    <a href="{% url 'crear' %}" class="btn btn-primary">
        <i class="fas fa-plus"></i> Crear
    </a>
    <a href="{% url 'exportar' %}" class="btn btn-outline-primary">
        <i class="fas fa-download"></i> Exportar
    </a>
    <a href="{% url 'nueva_venta' %}" class="btn btn-accent">
        <i class="fas fa-cart-plus"></i> Nueva venta
    </a>
</nav>
```

Button variants: `btn-primary` (main action), `btn-outline-primary`
(secondary), `btn-accent` (special), `btn-danger` (destructive).

## Pattern: Pagination

```html
{% include 'base/per_page_control.html' %}
<nav class="pagination-nav">
    <span>Página {{ items.number }} de {{ items.paginator.num_pages }}</span>
    <section>
        {% if items.has_previous %}
        <a href="?page=1{{ query_params }}" class="btn btn-sm btn-outline-primary">
            <i class="fas fa-chevron-left"></i> Anterior
        </a>
        {% endif %}
        {% if items.has_next %}
        <a href="?page={{ items.next_page_number }}{{ query_params }}"
           class="btn btn-sm btn-outline-primary">
            Siguiente <i class="fas fa-chevron-right"></i>
        </a>
        {% endif %}
    </section>
</nav>
```

## Pattern: Stock status badges

```html
{% if producto.stock <= stock_minimo_alerta %}
    <span class="stock-badge stock-low">{{ producto.stock }}</span>
{% else %}
    <span class="stock-badge stock-ok">{{ producto.stock }}</span>
{% endif %}
```

## Pattern: Empty states

Every list template handles the empty case:

```html
{% if items %}
    <table>...</table>
{% else %}
    <p class="empty-text">No hay registros.</p>
{% endif %}
```

Or for dashboard panels:
```html
{% if productos %}
    ...
{% else %}
    <p class="empty-text">No hay productos vendidos registrados.</p>
{% endif %}
```

## Pattern: Icon usage

All icons use **Font Awesome 6** (loaded in base.html):
```html
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
```

Common icon patterns: `fa-plus` (create), `fa-edit` (edit),
`fa-trash` (delete), `fa-download` (export), `fa-search` (search),
`fa-filter` (filter), `fa-chevron-left/right` (pagination),
`fa-coins`, `fa-box`, `fa-cart-plus`, `fa-receipt`.

## Checklist

- [ ] Template extends `base/base.html` (or `base/form_base.html` for auth)
- [ ] `{% load static %}` present at top
- [ ] Page header with title and action buttons
- [ ] Stats cards using `stat-card` + `stat-icon` pattern
- [ ] Tables wrapped in `table-responsive`
- [ ] Pagination with prev/next and per-page control
- [ ] Empty states for all data blocks (`{% else %}` / `{% empty %}`)
- [ ] Font Awesome icons for all actions
- [ ] Stock badges with conditional coloring
- [ ] `formato_pesos` filter for monetary values
- [ ] `{% url %}` tags instead of hardcoded paths
- [ ] `query_params` appended to pagination links
- [ ] Tonjeo color palette (pink `D41473`, dark `111827`)

## Frequent errors

- **Missing `table-responsive`**: Long tables overflow on mobile. Always
  wrap `<table>` in `<section class="table-responsive">`.
- **Hardcoded URLs**: Use `{% url 'view_name' %}` instead of `/path/`.
- **Missing `per_page` parameter**: Pagination breaks without the per-page
  selector. Include `per_page_control.html` and pass `per_page_options`.
- **Stat cards without icons**: All stat cards should have an icon in a
  `stat-icon` section.
- **Not handling empty querysets**: An empty DB table shows "No hay..."
  message, never a blank page.
- **Missing CSRF token on forms**: All POST forms need
  `{% csrf_token %}`.

## Reference files

| Template | File | Lines |
|----------|------|-------|
| Base layout | templates/base/base.html | 1-218 |
| Dashboard | templates/dashboard/dashboard.html | 1-181 |
| Product list | templates/productos/productos.html | 1-280 |
| Sales history | templates/ventas/historial_ventas.html | 1-267 |
| New sale | templates/ventas/nueva_venta.html | 1-403 |
| Main CSS | static/css/tonjeo.css | full file |
