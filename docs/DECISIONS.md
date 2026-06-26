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

## Decision: SKU-Based Identity Tracing for Idempotent Migration

**Decision**: Use the `sku` campo with format `LEGACY-{id}` as the identity trace key for mapping legacy `Producto` records to dynamic `Registro` records, enabling fully idempotent re-runs.

**Reason**: Legacy product IDs are stable identifiers that don't change. Storing them in the existing `sku` field (already defined in the seed as `unico=True`) avoids creating a dedicated mapping table or an extra campo. Migration re-runs look up `ValorCampo(campo=sku, valor='LEGACY-{id}')` → if found, update; if not, create. This is simpler and more robust than name+talla matching.

**Trade-off**: The `sku` campo with `unico=True` prevents creating two dynamic products with the same SKU, which is desirable. Products that already have a custom SKU are unaffected (they simply don't match `LEGACY-*`).

**Current status**: Implemented in `migrar_productos_dynamic`. Verified idempotent across 3 executions.

---

## Decision: URL-Based Image Migration for Cloudinary

**Decision**: Store the legacy product's `imagen_final_url` (Cloudinary URL) in the dynamic `imagen_url` campo instead of downloading and re-uploading image files.

**Reason**: The storage backend is `MediaCloudinaryStorage`, which does not support `FileField.path()`. The existing Cloudinary URLs are already working in production. Storing the URL avoids:
- Duplicate image storage (same image in two places)
- Cloudinary API download/upload round-trips
- UUID-based filename changes that would break existing bookmarks

**Template compatibility**: `DynamicProductWrapper.imagen_final_url` prefers `imagen_url` over `imagen` uploads, so templates work without changes.

**Current status**: Implemented in `migrar_productos_dynamic`. All 6 images migrated as URLs.

---

## Decision: Two-Pass Migration (Products → Then Movements)

**Decision**: Product creation and initial inventory movement creation are separate passes (step 3 and step 3b), not a single atomic operation per product.

**Reason**: The initial inventory movement (motivo='Inventario inicial') requires the dynamic product to exist first. Separating the passes allows the second pass to also handle edge cases: products created by an earlier version of the script that didn't create movements, or products with stock=0 that don't need a movement.

**Current status**: Implemented in `migrar_productos_dynamic`. Step 3b detects missing movements and creates them without duplicating existing ones.

---

## Decision: RunSQL for Pre-Existing Schema Discrepancies

**Decision**: Use `migrations.RunSQL` instead of `migrations.AlterField` to fix pre-existing database schema discrepancies that Django's migration system cannot detect.

**Reason**: Django's `makemigrations` compares the current model state against the recorded migration state (from migration files), not against the actual database schema. When a column was created with different constraints than the model specifies (due to prior model changes that didn't generate migrations), `AlterField` generates `(no-op)` because Django believes the schema is already correct. `RunSQL` bypasses this and executes raw `ALTER TABLE` statements directly.

**Current status**: Applied in migration `0005_fix_schema_discrepancies`. Fixed: `Formulario.creado_por_id` nullable, `ValorCampo.valor` NOT NULL, `Campo.nombre` varchar(100).

---

## Decision: Thread-Local Hook Recursion Protection

**Decision**: Use `threading.local()` to detect and prevent recursive hook execution.

**Reason**: A hook (e.g., `post_crear_venta`) calls `DS.crear()` for `MovimientosInventario`, which could theoretically trigger another `post_crear` hook. Thread-local storage prevents infinite recursion without requiring database-level state.

**Current status**: Implemented in `services_dynamic.py` with `_hook_local`, `_marcar_inicio_hook()`, `_marcar_fin_hook()`, and `HookRecursivoError`.
