# Project Overview

## What It Is

**Tonjeo** is a web-based commercial management system for a clothing store. It handles products, inventory, sales, clients, users, and reports through a browser interface.

## Main Objective

Provide a complete point-of-sale and inventory management solution using Django's template-driven architecture (no REST API). The current focus is migrating from traditional Django models to a dynamic Entity-Attribute-Value (EAV) form system that allows schema changes without migrations.

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.11+, Django 5.1.15 |
| Database | PostgreSQL (Neon) with SSL |
| Frontend | Django Templates, JavaScript, CSS |
| Image Storage | Cloudinary (optional) or local filesystem |
| Email | Brevo (Sendinblue) SMTP/API |
| Static Files | WhiteNoise |
| PDF Reports | ReportLab 4.5.0 |
| Excel Reports | OpenPyXL 3.1.5, Pandas 3.0.2 |
| Environment | python-decouple |
| CI | GitHub Actions (CodeQL, SonarCloud) |

## Project Structure

```
├── apps/
│   ├── platform/
│   │   └── dynamic_forms/       # Core EAV engine (platform module)
│   ├── legacy/
│   │   ├── productos/           # Legacy products module
│   │   └── ventas/              # Legacy sales module
│   └── shared/
│       ├── configuracion/       # Store configuration
│       ├── reportes/            # Reports module
│       └── usuarios/            # User management
├── config/
│   ├── settings/
│   │   ├── base.py              # Shared settings
│   │   ├── development.py       # Dev overrides
│   │   └── production.py        # Production overrides
│   ├── urls.py                  # Root URL configuration
│   ├── permissions.py           # Role-based access control
│   └── pagination.py            # Pagination utilities
├── static/                      # CSS, JS organized by module
├── templates/                   # Django templates by module
├── manage.py
├── requirements.txt
└── build.sh
```

## Main Application Modules

### `apps.platform.dynamic_forms`
The core platform module implementing an EAV (Entity-Attribute-Value) pattern. Provides `DynamicService`, a complete CRUD abstraction over four models: `Formulario`, `Campo`, `Registro`, and `ValorCampo`. Includes validators, hooks, formula evaluation, Excel export, and template tags.

### `apps.legacy.productos`
Legacy product management with `Producto`, `Categoria`, and `MovimientoInventario` Django models. Also contains **dynamic views** (`views_dynamic.py`) and **wrappers** (`wrappers.py`) that adapt EAV records to match legacy template interfaces. In transition: most routes use dynamic views.

### `apps.legacy.ventas`
Legacy sales management with `Venta` and `Cliente` Django models. Contains **dynamic views** (`views_dynamic.py`) and the **sales hook** (`hooks.py`) that decrements stock on sale creation. In transition: most routes use dynamic views.

### `apps.shared.configuracion`
Store-wide configuration via a singleton `ConfiguracionTienda` model. Provides a context processor (`configuracion_tienda`) that makes settings available to all templates. Includes dark/light theme toggle and stock alert threshold.

### `apps.shared.usuarios`
User management using Django's `auth.User`. Handles login/logout, password recovery via Brevo email, and seller CRUD with role assignment (Administrador/Vendedor).

### `apps.shared.reportes`
Reports dashboard with KPIs, SVG charts (line, donut, bar), and PDF/Excel export. Partially migrated to Dynamic Forms (Phase 1: data layer; Phase 2: charts pending).

## Current Architecture Summary

The project is in a transitional state between two architectures:

1. **Legacy architecture**: Traditional Django models (`Producto`, `Venta`, `Cliente`, `MovimientoInventario`) with model-level business logic (`save()` overrides for stock operations).

2. **Dynamic Forms architecture**: EAV-based system where form structure is data-driven. Business logic is implemented via **hooks** (Python callables configured on `Formulario`) and **wrappers** (adapter classes that bridge EAV data to legacy template expectations).

The main `urls.py` routes most product and sales URLs to **dynamic views** (`views_dynamic.py`), while legacy views remain as fallback. The migration is incremental: wrappers allow legacy templates to work unmodified with dynamic data.
