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

## Decision: Import Execution as Reusable Service

**Decision**: Extract all import logic from `_handle_import_data()` into a standalone service `import_execution.py` with `execute_import()`, so that both the manual POST handler and the auto-import after form creation execute exactly the same code.

**Reason**: The bug was that `_handle_create_form()` created the form and set session data but never called the import — the user had to click a second "Importar datos" button. By extracting the import logic into a service, `_handle_create_form()` calls `execute_import()` immediately after form creation when `has_data=True`, then auto-redirects to `ver_registros`. This eliminates the two-step flow for the normal case.

**Trade-off**: The "Importar datos" button is now only shown when `import_failed=True` (for retry). This means users cannot manually trigger import on a successfully created form — they would need to re-upload. This is acceptable because the normal flow is now fully automatic.

**Current status**: Implemented. `apps/platform/document_intelligence/services/import_execution.py` exposes `execute_import()`, `apply_import_messages()`, and `_cleanup_session()`. `_handle_import_data()` is a ~20-line delegate. `_handle_create_form()` calls `execute_import()` inline when `has_data=True`. Templates show import button only for retry.

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

---

## Decision: id_legacy Field for Ventas Idempotent Migration

**Decision**: Add an `id_legacy` (text) field to the `Ventas` dynamic form to serve as the idempotency key during legacy-to-dynamic data migration.

**Reason**: Unlike Clientes (which have a natural unique key via `documento`), Ventas have no unique natural identifier. The same product + same client + same quantity could theoretically repeat. The `id_legacy` field stores the legacy `Venta.id`, providing a stable, unique trace key without requiring an extra mapping table.

**Trade-off**: No schema impact on templates or wrappers (the field is purely for migration idempotency). It remains in the form for future idempotent re-runs.

**Current status**: Implemented in `migrar_ventas_dynamic`. The field is auto-created if absent. Verified across 2+ idempotent executions.

---

## Decision: Documento as Natural Key for Cliente Migration

**Decision**: Use the existing `documento` field (unique in both legacy `Cliente.documento` and dynamic `Clientes.documento`) as the idempotency key for client migration, without adding extra fields.

**Reason**: The `documento` field is already unique in both systems. No schema change needed. Lookups are performed via `ValorCampo(campo__nombre='documento', valor=documento)`.

**Current status**: Implemented in `migrar_clientes_dynamic`. Verified across 2+ idempotent executions.

---

## Decision: Hook Disabling During Venta Migration

**Decision**: Temporarily disable the `hook_post_crear` on the `Ventas` form while migrating legacy sales data.

**Reason**: The hook `post_crear_venta` decrements product stock. During migration, this would cause double-decrement: the stock was already decremented when the original sale occurred, and the current dynamic product stock reflects that decrement. Re-executing it would create incorrect stock levels.

**Implementation**: Save the original hook path, set `formulario.hook_post_crear = None`, run `DS.crear()`, then restore the hook within a `try/finally` block.

**Current status**: Implemented in `migrar_ventas_dynamic`. Verified that stock levels remain correct after migration.

---

## Decision: App Preservation After Model Removal

**Decision**: Keep `apps.legacy.ventas` in `INSTALLED_APPS` even after removing its models (`Venta`, `Cliente`) and dropping their database tables.

**Reason**: The app still contains active, non-replaceable components:
- `hooks.py` — `post_crear_venta` hook referenced by the dynamic Ventas form
- `templatetags/formatos.py` — template tags (`formato_pesos`, etc.) used by templates
- `views_dynamic.py` — 1107 lines of active dynamic views
- `migrations/` — 9 migration files forming the migration chain

Removing the app from `INSTALLED_APPS` would require moving all these components to a different app, which adds unnecessary risk and complexity.

**Trade-off**: The app directory has no `models.py` with actual model classes, which is non-standard but functional in Django. A comment placeholder explains the change.

**Alternative considered**: Migrate views/hooks/templatetags to `dynamic_forms` or a new `ventas` app under `apps/shared/`. Rejected because this would require:
- Updating all template `{% load %}` statements referencing `formatos.py`
- Updating the hook path in the database (`Formulario.hook_post_crear`)
- Changing imports in `config/urls.py`
- No functional benefit — the current structure works correctly

**Current status**: Applied in Fase 3 (ventas) and Fase 4 (productos). Both `apps.legacy.ventas` and `apps.legacy.productos` remain in `INSTALLED_APPS` as thin apps with no models, preserving hooks, templatetags, views_dynamic, and wrappers.

**Productos specific**: `apps.legacy.productos` preserves `views_dynamic.py` (dynamic views), `wrappers.py` (DynamicProductWrapper, DynamicMovimientoInventarioWrapper, etc.), and `migrations/` (migration chain). Unlike ventas, it does not have hooks or templatetags — it only needs views and wrappers.

---

## Decision: Single Source of Truth for Form Name Constants

**Decision**: All form-level string constants (`FORM_PRODUCTOS`, `FORM_VENTAS`, `FORM_CLIENTES`, `FORM_MOVIMIENTOS_INVENTARIO`) are defined exclusively in `services_dynamic.py`. Other files import from there.

**Reason**: Before Phase 5, these constants were duplicated in 7 files (both `views_dynamic.py` files, 4 management commands, and `services_dynamic.py`). Any change to a form name required updating all 7 locations, which was error-prone. Centralizing them in `services_dynamic.py` eliminates the maintenance burden.

**Current status**: Implemented in Phase 5. All 6 consumer files now import from the canonical source in `services_dynamic.py`.

---

## Decision: Identificador Principal as BooleanField on Campo

**Decision**: Add `identificador_principal` as a `BooleanField(default=False)` on the `Campo` model, with auto-unsetting logic in `save()` to ensure only one field per formulario has this flag.

**Reason**: The identifier is a property of a field, not a separate entity. Storing it directly on `Campo` avoids creating a new model or configuration table. The `save()` override automatically desmarca other fields in the same formulario when one is marked as identifier, enforcing the single-identifier constraint at the database level.

**Current status**: Implemented in `models.py`. Migration `0007` applied. The admin, templates, and view processing all support this field. Forms can now auto-create an identifier field on creation (Phase 5).

---

## Decision: Moneda Type as Text Storage with Number Validation

**Decision**: Add `moneda` as a new type in `Campo.TIPOS` with validation accepting integers and decimals up to 2 decimal places. Stored as text in `ValorCampo.valor`, consistent with all other EAV types. Visual prefix `$` rendered via Bootstrap input-group.

**Reason**: The EAV pattern stores all values as text. Adding a new type with formatted validation (max 2 decimals, non-negative) provides field-level enforcement while keeping storage consistent. The Bootstrap input-group provides visual context without storing the symbol. Future regional formatting (COP, USD, EUR) can be added without schema changes.

**Current status**: Implemented in `models.py`, `validators.py`, and all relevant templates. See `Fase de mejoras Dynamic Forms (7 fases)` in SESSION_LOG.md.

---

## Decision: Extensible Booleano Validation

**Decision**: Extend booleano validation to accept 12 variants (Sí, Si, No, True, False, 1, 0, yes, no, on, off) and normalize all to internal format `Sí`/`No`.

**Reason**: Previous implementation only accepted `on` (from HTML checkboxes). Real-world data from Excel imports, APIs, or manual entry may use any of these common boolean representations. Normalizing to the existing format ensures full backward compatibility.

**Current status**: Implemented in `validators.py`. All accepted forms normalized automatically.

---

## Decision: Datetime Conversion in Excel Import

**Decision**: Convert openpyxl `datetime` objects to `YYYY-MM-DD` strings during `leer_excel()` before passing to validation.

**Reason**: openpyxl returns datetime objects for date-formatted cells. The EAV system expects text values. Converting in the import layer avoids type errors downstream and ensures compatibility with existing date validation. Text-based dates (user-typed) continue to work unchanged.

**Current status**: Implemented in `import_service.py.leer_excel()`. 

---

## Decision: Enterprise Import/Export Architecture (v2.0)

**Decision**: Evolve the import/export subsystem from a flat `import_service.py` + single view into a modular architecture with dedicated submodules for each concern: formats, detection, quality, conflict resolution, audit, rollback, and pipeline orchestration.

**Reason**: The original `import_service.py` (859 lines) combined parsing, matching, validation, importing, template generation, and error reporting in one file. As the system grew (ColumnMatcher, 4 import modes, Excel templates, multi-step wizard), the file became hard to maintain. The new architecture:
- Separates each concern into its own module (`detector.py`, `quality.py`, `conflict.py`, `audit.py`, `rollback.py`)
- Uses a `Pipeline` orchestrator to coordinate the full workflow
- Introduces `ImportLog`, `ImportAudit`, `ImportSnapshot` models for full traceability
- Provides history views with detail, rollback, and error report download
- Remains fully backward compatible — `import_service.py` unchanged; the pipeline is an opt-in alternative

**Components created**:

Subpackage `import_export/`:
- `__init__.py` — Exports ImportPipeline, DataDetector, QualityAnalyzer, RollbackManager, AuditLogger
- `pipeline.py` — Pipeline orchestrator with `PipelineConfig`/`PipelineResult` dataclasses
- `detector.py` — DataDetector: type inference, duplicate & outlier detection
- `quality.py` — QualityAnalyzer: 1-5 star rating with penalty/bonus system
- `conflict.py` — ConflictDetector: duplicated columns, field conflicts, unmatched columns
- `audit.py` — AuditLogger: detailed per-action logging with 7 event types (creacion, actualizacion, error, advertencia, decision, ignorado, rollback)
- `rollback.py` — RollbackManager: snapshot-based revert with mode-aware delete/restore
- `formats/base.py` — BaseParser abstract class with ParseResult dataclass
- `formats/excel.py` — ExcelParser with sheet scoring, header detection, data row detection

**Models** (database):
- `ImportLog` — Full import metadata: file info, hash, mode, estado, counts, quality, confianza
- `ImportAudit` — Per-event audit trail: tipo, registro_id, campo_nombre, valor_anterior/nuevo, mensaje
- `ImportSnapshot` — Pre-import value snapshots for rollback: registro FK, valores_anteriores JSON

**Views/URLs**:
- `historial_importaciones` — Paginated table with quality stars, mode badges, KPIs
- `detalle_importacion` — Full detail with audit trail, snapshots, conflict/warning display
- `revertir_importacion` — Confirmation page + POST execution
- `descargar_reporte_errores` — Excel download of error audit events

**Templates**:
- `templates/dynamic_forms/import_export/historial_importaciones.html`
- `templates/dynamic_forms/import_export/detalle_importacion.html`
- `templates/dynamic_forms/import_export/revertir_importacion.html`

**Integration**:
- `import_service.py` — new `importar_con_pipeline()` function
- `urls.py` — 5 new routes for history/detail/rollback/errors
- `views.py` — 4 new enterprise views + json/json import
- `admin.py` — 3 new ModelAdmins (ImportLog, ImportAudit, ImportSnapshot)
- Templates `ver_registros.html` and `importar_excel.html` — "Historial" button added
- AppConfig labels fixed for migrations: `productos` → `ProductosConfig(label='productos')`

**Trade-off**: The pipeline is not yet the default for `importar_excel` view. Backward compatibility is preserved. The pipeline can be swapped in by modifying `views.py` to call `importar_con_pipeline()` instead of `previsualizar()` + `importar()`.

**Current status**: Implemented. Migration `0008` applied. All models, modules, views, URLs, and templates created. `python manage.py check` — 0 issues. `makemigrations --check` — No changes detected. All imports verified.

---

## Decision: Three-Layer Defense for `relacion` Type Inference

**Decision**: Protect against invalid `relacion` type assignment at three independent layers: AI prompt guidance, form creation logic, and runtime validation.

**Reason**: The root cause was that `tipo=relacion` was being assigned by the AI (or MemoryLearner) to columns containing business identifiers (SKU, Código, ID Almacén, Folio, etc.), but the validator assumed all `relacion` values were `Registro.id` primary keys. Three layers of defense prevent this:

1. **Prompt layer** (detect_fields.md): Explicit rules tell the AI that columns named "Código", "ID", "SKU", "ID Relación Almacén", etc. should be `codigo`, not `relacion`. Also clarifies that `relacion` is only for values representing internal DB primary keys.

2. **Form creation layer** (`_handle_create_form`): When the AI suggests `tipo=relacion`, the system resolves `related_form` against actual `Formulario` objects. If the target form doesn't exist or `related_form` isn't specified, the field is automatically downgraded to `codigo`. This prevents creating structurally incomplete `relacion` fields (with `formulario_destino=NULL`).

3. **Validation layer** (`_validar_valor_campo`): If a `relacion` field has `formulario_destino_id=NULL`, the validator skips the `Registro.id` existence check entirely (same behavior as `codigo`). Only when `formulario_destino_id` is set does it validate that the referenced Registro exists.

**Trade-off**: A `relacion` field without `formulario_destino` will never be validated as a true relationship at the DB level. This is acceptable because such fields are already invalid by design (they should have been `codigo`).

**Current status**: Implemented. Three-layer defense active. All existing code that handles `relacion` (views.py:356, views.py:320, dynamic_values.py:77) already checks `formulario_destino_id` and is unaffected. 
