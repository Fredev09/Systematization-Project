---
name: dynamic-dashboard
description: >-
  Builds the main dashboard view using Dynamic Forms data. Based on the
  real integration between dashboard.html template and the data helpers
  in productos/views_dynamic.py and ventas/views_dynamic.py.
license: MIT
compatibility: opencode
metadata:
  audience: developer
  module: dashboard
  real_files: templates/dashboard/dashboard.html
---

# dynamic-dashboard

Builds the main dashboard view that integrates data from multiple Dynamic
Forms (Productos, Ventas, Clientes, MovimientosInventario) into a single
cohesive view. Based on the real integration in the project.

## When to use

- Creating the main dashboard/home page.
- Adding new KPIs or panels to the dashboard.
- Integrating data from multiple dynamic forms into one view.
- Building stat cards, top-N lists, and recent activity panels.

## When NOT to use

- Detailed reports (use `report-generator` skill).
- Single-form list views (use `build-dynamic-view` skill).
- Admin-only configuration pages.

## Real project pattern

The dashboard (`templates/dashboard/dashboard.html`) integrates data from
the dynamic views layer. The controller view typically lives in a
central module and calls helpers from productos and ventas.

## Pattern: Multi-form data aggregation

```python
# Pseudo-code based on the real dashboard integration
def dashboard(request):
    es_admin = es_administrador(request.user)

    # 1. Product stats from DynamicService
    total_productos = DS.contar(FORM_PRODUCTOS)
    _, stock_bajo, sin_stock = _stock_stats()

    # 2. Sales stats for the current user
    from apps.legacy.ventas.views_dynamic import _stats_ventas, _ventas_recientes
    total_ventas, total_hoy, total_mes, unidades = _stats_ventas(
        request.user, es_admin
    )

    # 3. Recent sales
    ventas_recientes = _ventas_recientes(limite=5)

    # 4. Top products (from sales data)
    top_productos = _calcular_top_productos(limite=5)

    # 5. Render
    return render(request, 'dashboard/dashboard.html', {
        'total_ventas': total_ventas,
        'total_productos': total_productos,
        'stock_bajo': stock_bajo,
        'ventas_recientes': ventas_recientes,
        'productos': top_productos,
        'es_admin': es_admin,
        'rol_usuario': rol_usuario(request.user),
    })
```

## Pattern: Template structure (from dashboard.html)

The dashboard template (`templates/dashboard/dashboard.html:1-181`) has
this structure:

```html
{% extends 'base/base.html' %}
{% load formatos %}

{% block contenido %}
<!-- Header with action buttons -->
<section class="page-header">
    <h1>Panel principal</h1>
    <nav class="header-actions">
        <a href="{% url 'exportar_ventas' %}" class="btn btn-outline-primary">
            Exportar ventas
        </a>
        <a href="{% url 'nueva_venta' %}" class="btn btn-primary">
            Nueva venta
        </a>
    </nav>
</section>

<!-- Stats grid (4 cards) -->
<section class="stats-grid">
    <article class="stat-card">
        <span>Ventas</span>
        <h3>{{ total_ventas|formato_pesos }}</h3>
    </article>
    <article class="stat-card">
        <span>Productos</span>
        <h3>{{ total_productos }}</h3>
    </article>
    <article class="stat-card">
        <span>Stock bajo</span>
        <h3>{{ stock_bajo }}</h3>
    </article>
</section>

<!-- Content grid (2 panels) -->
<section class="content-grid">
    <article class="panel-card">
        <h2>Top productos vendidos</h2>
        <table class="table">
            <thead><tr><th>#</th><th>Producto</th><th>Precio</th>...</tr></thead>
            <tbody>
                {% for producto in productos %}
                <tr>
                    <td>{{ forloop.counter }}</td>
                    <td>{{ producto.nombre }}</td>
                    <td>{{ producto.precio|formato_pesos }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </article>

    <article class="panel-card">
        <h2>Ventas recientes</h2>
        {% for venta in ventas_recientes %}
        <article class="sale-item">
            <strong>Venta #{{ venta.id }}</strong>
            <span>{{ venta.fecha|date:"d/m/Y h:i A" }}</span>
            <p>{{ venta.total|formato_pesos }}</p>
        </article>
        {% endfor %}
    </article>
</section>
{% endblock %}
```

## Pattern: Empty states

Every data block in the dashboard has an empty state:

```html
{% if productos %}
    <table>...</table>
{% else %}
    <p class="empty-text">No hay productos vendidos registrados.</p>
{% endif %}
```

## Checklist

- [ ] Stats computed from each form independently
- [ ] Recent data limited with slicing (`[:5]`, `[:10]`)
- [ ] Empty states for every panel
- [ ] Role-aware content (admin sees more cards)
- [ ] `formato_pesos` filter for monetary values
- [ ] Stock status badges (green/yellow/red)
- [ ] Action buttons link to the correct CRUD views
- [ ] `stock_minimo_alerta` passed to template for conditional styling

## Frequent errors

- **One view trying to do everything**: The dashboard controller should
  delegate to helpers (`_stats_ventas`, `_stock_stats`, `_ventas_recientes`)
  instead of inlining all queries.
- **Not limiting recent queries**: `_ventas_recientes(limite=5)` limits
  at DB level. Loading all records then slicing in Python wastes queries.
- **Missing empty state**: If there are no sales, the template shows a
  blank section. Always include `{% else %}` for every data block.
- **Hardcoding admin checks in template**: Use `es_admin` variable from
  the view context, not inline `request.user.is_superuser` in templates.

## Reference files

| Component | File | Lines |
|-----------|------|-------|
| Dashboard template | templates/dashboard/dashboard.html | 1-181 |
| _stock_stats | productos/views_dynamic.py | 63-91 |
| _stats_ventas | ventas/views_dynamic.py | 121-152 |
| _ventas_recientes | ventas/views_dynamic.py | 155-168 |
| _stock_stats_completo | productos/views_dynamic.py | 219-277 |
