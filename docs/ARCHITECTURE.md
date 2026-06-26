# Architecture

## High-Level Architecture

The project is a monolithic Django application with template-based rendering. It follows a layered architecture:

```
┌─────────────────────────────────────────────────────────┐
│                    Templates (UI layer)                  │
│   base / dashboard / productos / ventas / clientes / ...│
└────────────────────┬────────────────────────────────────┘
                     │ context (views → templates)
┌────────────────────▼────────────────────────────────────┐
│                    Views (Controllers)                   │
│   views.py / views_dynamic.py                           │
└────────────────────┬────────────────────────────────────┘
                     │ calls
┌────────────────────▼────────────────────────────────────┐
│                    Services / Hooks                      │
│   DynamicService / services.py / hooks.py                │
└────────────────────┬────────────────────────────────────┘
                     │ queries
┌────────────────────▼────────────────────────────────────┐
│                    Models (Data Layer)                   │
│   Legacy: Producto, Venta, Cliente, ...                 │
│   Dynamic: Formulario, Campo, Registro, ValorCampo      │
└─────────────────────────────────────────────────────────┘
```

## Django Apps

| App | Type | Purpose |
|-----|------|---------|
| `apps.platform.dynamic_forms` | Platform | EAV engine — form definition, field management, record storage, validation, hooks |
| `apps.legacy.productos` | Legacy | Product & inventory CRUD (both legacy and dynamic views) |
| `apps.legacy.ventas` | Legacy | Sales & client management (both legacy and dynamic views) |
| `apps.shared.configuracion` | Shared | Singleton store configuration |
| `apps.shared.usuarios` | Shared | User authentication, authorization, password recovery |
| `apps.shared.reportes` | Shared | Dashboard KPIs, charts, PDF/Excel export |

## Dynamic Forms Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    DynamicService                        │
│  Static methods: crear, actualizar, eliminar, filtrar,   │
│  buscar, sumar, contar, top, validar_*, obtener_*       │
└────┬─────────┬──────────┬──────────┬────────────────────┘
     │         │          │          │
┌────▼──┐ ┌───▼────┐ ┌──▼─────┐ ┌──▼───────────────────┐
│Models │ │Views   │ │Validat.│ │Services (formula eval)│
│       │ │(CRUD)  │ │        │ │                      │
│Formul.│ │Listar  │ │Tipo    │ │_evaluar_formula()    │
│Campo  │ │Crear   │ │Unique  │ │Excel export          │
│Regist.│ │Editar  │ │Obligat.│ │                      │
│ValorC.│ │Export  │ │Custom  │ │                      │
└───────┘ └────────┘ └────────┘ └──────────────────────┘
```

### DynamicService

Located in `apps/platform/dynamic_forms/services_dynamic.py`. A static-method service class that provides:

- **Form lookup**: `obtener_formulario()`, `obtener_campo()`, `obtener_campos_activos()`
- **Value access**: `obtener_valor()`, `obtener_valores()`, `cargar_valores_mapa()`
- **Query**: `filtrar()`, `buscar()`, `sumar()`, `contar()`, `top()`
- **Validation**: `validar_completo()`, `validar_unicidad()`, `validar_campos_obligatorios()`, `validar_tipos()`, `ejecutar_validacion_personalizada()`
- **CRUD**: `crear()`, `actualizar()`, `eliminar()`
- **Hooks**: `_ejecutar_hook()` (internal, called from `crear`/`actualizar`)
- **Constants**: `FORM_PRODUCTOS`, `FORM_CLIENTES`, `FORM_VENTAS`, `FORM_MOVIMIENTOS_INVENTARIO`

### Wrappers

Located in `apps/legacy/productos/wrappers.py`. Adapter classes that convert EAV `Registro` + `ValorCampo` data into objects matching legacy template expectations.

| Wrapper | Emulates | Key Attributes |
|---------|----------|---------------|
| `DynamicProductWrapper` | Legacy `Producto` | `nombre`, `precio`, `stock`, `talla`, `color`, `categoria.nombre`, `imagen_final_url` |
| `DynamicVentaWrapper` | Legacy `Venta` | `cantidad`, `total`, `producto.nombre`, `vendedor.username`, `cliente.nombre_completo` |
| `DynamicMovimientoInventarioWrapper` | Legacy `MovimientoInventario` | `tipo`, `cantidad`, `motivo`, `stock_anterior`, `stock_nuevo`, `producto`, `fecha` |
| `DynamicClienteWrapper` | Legacy `Cliente` | `documento`, `nombre`, `apellido`, `nombre_completo`, `correo`, `telefono` |

### Hooks

Defined as Python dotted-path callables stored on `Formulario.hook_post_crear` and `Formulario.hook_post_actualizar`. Example:

- **Path**: `apps.legacy.ventas.hooks.post_crear_venta`
- **Behavior**: Decrements product stock, creates `MovimientosInventario` record after each sale.
- **Recursion protection**: Thread-local storage prevents a hook from triggering itself.

### Validators

Located in `apps/platform/dynamic_forms/validators.py`. Centralized per-type validation:

- `numero` — float conversion check
- `fecha` — YYYY-MM-DD format
- `booleano` — `'on'` maps to `'Sí'`, else `'No'`
- `lista` — value must be in `campo.opciones`
- `email` — regex pattern
- `url` — must start with `http://` or `https://`
- `telefono` — minimum 7 digits, allows formatting chars
- `relacion` — validates referenced `Registro` exists
- `calculado` — read-only, no user validation

## Relationships Between Modules

```
dynamic_forms (platform)
    ├── provides DynamicService, models, validators, template tags
    │
    ├── used by productos/views_dynamic.py → product CRUD via EAV
    ├── used by ventas/views_dynamic.py → sales CRUD via EAV
    ├── used by ventas/hooks.py → stock operations
    ├── used by reportes/views.py → dynamic KPI queries
    │
    ├── wrappers bridge to:
    │   ├── productos/wrappers.py → legacy product templates
    │   └── legado (implicitly) via attribute compatibility
    │
    └── management commands seed base forms and hooks

configuracion (shared)
    └── context processor provides settings to ALL templates

usuarios (shared)
    └── provides auth for all views via @login_required, @admin_required

reportes (shared)
    ├── reads from legacy models (Producto, Venta, Cliente) — legacy path
    └── reads from DynamicService — dynamic path (Phase 1)
```

## Legacy SQLite Patterns Not Used

The `requirements.txt` includes `mysqlclient` but the database is PostgreSQL. The legacy models `Producto`, `Venta`, `Cliente`, and `MovimientoInventario` use standard Django ORM fields and are fully migrated.
