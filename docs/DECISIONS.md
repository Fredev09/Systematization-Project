# Architectural Decisions

## Decision: EAV-Based Dynamic Forms

**Decision**: Replace fixed Django model schemas with an Entity-Attribute-Value (EAV) system (`Formulario` / `Campo` / `Registro` / `ValorCampo`) to eliminate migrations for field changes.

**Reason**: The project needed the ability to add, remove, or modify product/sales fields without running Django migrations. An EAV pattern was chosen because it provides schema flexibility at the cost of query complexity.

**Current status**: Implemented. Four models (`Formulario`, `Campo`, `Registro`, `ValorCampo`) with a full CRUD service layer (`DynamicService`), validators, hooks, and template tags. The EAV_LIMITACIONES.md document identifies the known trade-offs (performance, referential integrity, weak types).

---

## Decision: Static-Method Service Layer

**Decision**: `DynamicService` exposes only static methods. No instantiation, no dependency injection.

**Reason**: Simplifies usage from views — no constructor or state management needed. The service is a stateless facade over the EAV models.

**Current status**: Implemented in `apps/platform/dynamic_forms/services_dynamic.py`. All ~20 public methods are `@staticmethod`.

---

## Decision: Value Storage as TextField

**Decision**: Store all values (numbers, dates, booleans, relationships) as plain text in `ValorCampo.valor`.

**Reason**: EAV systems with per-type value columns (e.g., `valor_texto`, `valor_numero`, `valor_fecha`) introduce complexity without significant benefit at the current scale. A single `TextField` keeps the schema simple.

**Current status**: Implemented. Type conversion happens in `validators.py`, `wrappers.py`, and `services.py` (formula evaluation). Known limitation: no database-level type safety.

---

## Decision: Two-Pass Formula Evaluation

**Decision**: Calculated fields are evaluated in a second pass after all normal fields are saved, with sequential updates to support chaining.

**Reason**: Formulas like `subtotal = precio_unitario * cantidad` and `total = subtotal - descuento` require that normal fields exist before formulas can be evaluated. Sequential updates enable chaining.

**Current status**: Implemented in `DS.crear()` and `DS.actualizar()`. Fields with `tipo='calculado'` are skipped in the first pass and evaluated in a second loop.

---

## Decision: Hook-Based Side Effects

**Decision**: Business logic side effects (stock decrement, audit trails) are implemented as configurable Python callables (hooks) on `Formulario`, not as model `save()` overrides.

**Reason**: Since records are stored in the generic `Registro` model, business logic cannot be placed in a model-specific `save()` method. Hooks decouple form structure from business logic and allow reuse across forms.

**Current status**: Implemented. `Formulario` has `hook_post_crear` and `hook_post_actualizar` fields. A thread-local recursion protection mechanism prevents infinite loops. One hook exists: `apps.legacy.ventas.hooks.post_crear_venta`.

---

## Decision: Wrapper Pattern for Template Compatibility

**Decision**: Create adapter classes (wrappers) that convert EAV `Registro` + `ValorCampo` data into objects with the same attribute interface as legacy Django models.

**Reason**: Legacy templates use attribute access (`producto.nombre`, `venta.total`) and Django template filters. Wrappers allow the templates to work unmodified with dynamic data, enabling gradual migration.

**Current status**: Implemented in `apps/legacy/productos/wrappers.py`. Four wrappers exist: `DynamicProductWrapper`, `DynamicVentaWrapper`, `DynamicMovimientoInventarioWrapper`, `DynamicClienteWrapper`.

---

## Decision: Pessimistic Locking for Stock Operations

**Decision**: Use `SELECT ... FOR UPDATE` (`select_for_update()`) when reading product stock before decrementing.

**Reason**: Stock operations are susceptible to race conditions. Pessimistic locking prevents concurrent sale processing from creating negative stock.

**Current status**: Implemented in `apps/legacy/ventas/hooks.py:post_crear_venta()` and in `DS.crear()` when `usar_select_for_update=True`.

---

## Decision: Parallel Dynamic and Legacy Views

**Decision**: Keep both legacy views (`views.py`) and dynamic views (`views_dynamic.py`) in the same app, with the main URL config pointing to dynamic versions.

**Reason**: Enables incremental migration. If a dynamic view has issues, the URL can be switched back to the legacy version. Legacy models and templates serve as a reference implementation.

**Current status**: Implemented for both `apps.legacy.productos` and `apps.legacy.ventas`. `config/urls.py` imports from `views_dynamic` for most routes.

---

## Decision: No REST API

**Decision**: Use pure Django template views with server-side rendering. No Django REST Framework or JSON API.

**Reason**: The project is a single-team internal tool with no mobile app or third-party integrations that would require an API. Template rendering is simpler and faster to develop.

**Current status**: Implemented. All views return `HttpResponse` / `render` / `redirect`. No serializers or API endpoints exist.

---

## Decision: Singleton for Store Configuration

**Decision**: `ConfiguracionTienda` uses a singleton pattern (forced `pk=1`, `get_or_create(pk=1)`).

**Reason**: The application has exactly one store configuration. A singleton model prevents accidental multi-config state and simplifies access from templates via a context processor.

**Current status**: Implemented in `apps/shared/configuracion/models.py`.

---

## Decision: Cloudinary for Optional Cloud Media Storage

**Decision**: Support both local filesystem and Cloudinary for image/media storage, controlled by environment variables.

**Reason**: Development environments use local storage for simplicity; production can use Cloudinary for scalability and CDN delivery.

**Current status**: Implemented in `config/settings/base.py` via conditional `USAR_CLOUDINARY` flag and storage backend switching.

---

## Decision: Brevo for Email

**Decision**: Use Brevo (Sendinblue) for transactional emails (password recovery).

**Reason**: Brevo offers a free tier suitable for the project's email volume and provides both SMTP and API options.

**Current status**: Implemented in `apps/shared/usuarios/services.py` (`enviar_correo_brevo()`). Brevo API key and SMTP settings are configurable via environment variables.

---

## Decision: Thread-Local Hook Recursion Protection

**Decision**: Use `threading.local()` to detect and prevent recursive hook execution.

**Reason**: A hook (e.g., `post_crear_venta`) calls `DS.crear()` for `MovimientosInventario`, which could theoretically trigger another `post_crear` hook. Thread-local storage prevents infinite recursion without requiring database-level state.

**Current status**: Implemented in `services_dynamic.py` with `_hook_local`, `_marcar_inicio_hook()`, `_marcar_fin_hook()`, and `HookRecursivoError`.
