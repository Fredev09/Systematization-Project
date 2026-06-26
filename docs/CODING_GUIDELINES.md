# Coding Guidelines

Coding conventions extracted from the existing codebase.

## Naming Conventions

- **Code identifiers**: English (e.g., `DynamicProductWrapper`, `obtener_valor`, `crear`).
- **User-facing strings**: Spanish (e.g., `'El campo "nombre" es obligatorio.'`, templates in Spanish).
- **App labels**: Dotted paths starting with `apps.*` (e.g., `apps.platform.dynamic_forms`).
- **Dynamic view files**: Named `views_dynamic.py` within the app.
- **Abbreviation**: `DynamicService` is always imported as `DS`.
- **Form constants**: Uppercase with underscore prefix in `services_dynamic.py` (e.g., `FORM_PRODUCTOS = 'Productos'`).

## Service Usage

- All `DynamicService` methods are **static**. Never instantiate `DynamicService()`.
- Business modules call `DynamicService` methods, never directly access `Formulario`/`Campo`/`Registro`/`ValorCampo` models in view code.
- Exceptions: hooks and wrappers may access models directly when needed (e.g., `ValorCampo.objects.update_or_create` in hooks).
- Always use `DS.cargar_valores_mapa(registros)` for bulk reads rather than N+1 `DS.obtener_valor()` calls.
- Prefer `DS.filtrar()` with keyword arguments over manual queryset construction.
- Use `DS.obtener_campos_activos('FormName')` instead of querying `Campo` directly.

## Wrapper Usage

- Wrappers receive `(registro, valores_dict)` where `valores_dict` comes from `DS.cargar_valores_mapa()`.
- Wrapper attribute names must match the attribute names expected by templates (which match legacy model field names).
- Type conversion is done inside the wrapper constructor, not in the view or template.
- Missing values get safe defaults (empty string for text, `Decimal('0')` for numbers, `0` for integers).
- Wrappers are **not cached or persisted** — constructed fresh on each request.
- Fallback product resolvers exist in wrappers for cases where relation resolution is not available.

## Query Optimization

- **Bulk value loading**: Use `DS.cargar_valores_mapa(registros, formulario)` to load all values for multiple records in a single query. This is critical for list views.
- **Aggregation in Python**: `DS.sumar()`, `DS.contar()`, and `DS.top()` load values and aggregate in Python rather than in SQL (due to EAV structural limitations).
- **Pessimistic locking**: Use `select_for_update()` for stock-sensitive operations to prevent race conditions.
- **Transaction atomicity**: All `DS.crear()` and `DS.actualizar()` calls run inside `transaction.atomic()`.
- **Filter chaining**: `DS.filtrar()` chains `INNER JOIN` on `ValorCampo` for each filter. Avoid excessive filters in a single call.

## Dynamic Forms Rules

1. **Two-pass save**: Normal fields first, then calculated fields. Never save a calculated field in the first pass.
2. **All values as strings**: Store everything as a string in `ValorCampo.valor`. Convert at read time in wrappers or services.
3. **Booleans as Sí/No**: Boolean values are stored as `'Sí'` or `'No'`, not Python booleans or integers.
4. **Relations as IDs**: Relation-type fields store the target `Registro.id` as a string.
5. **Field names are keys**: Field identification is by name string, not by ID, in most service methods.
6. **Form names are constants**: Use the named constants (`FORM_PRODUCTOS`, etc.) instead of string literals.

## Template Compatibility

- Templates expect **attribute access**, not dict access: `{{ producto.nombre }}`, not `{{ producto.nombre_campo.valor }}`.
- Use **wrappers** to bridge EAV data to template expectations.
- Template filters from `apps.legacy.ventas.templatetags.formatos`:
  - `formato_pesos` — formats number as `$1.234.567`
  - `formato_numero` — formats number with thousands separator
- Template tags from `apps.platform.dynamic_forms.templatetags.dynamic_values`:
  - `campo_valor`, `relacion_display`, `resolver_url_imagen`, `get_campos_formulario`
- Context processor `configuracion_tienda` provides `config` object to all templates.

## URL Conventions

- Format: `/module/action/<id>/` (e.g., `/productos/editar/42/`, `/venta/historial/`).
- `app_name` set in each app's `urls.py` for `{% url %}` template resolution.
- Authentication required on all business endpoints via `@login_required` or `@admin_required`.
- The `@admin_required` decorator (in `config/permissions.py`) restricts to `Administrador` group.

## Error Handling

- Custom exceptions in `services_dynamic.py`:
  - `DynamicFormError` — base
  - `FormularioNoEncontrado` — form not found
  - `CampoNoEncontrado` — field not found
  - `ValidacionError` — validation failure (carries list of errors)
  - `ValorUnicoError` — unique constraint violation
  - `HookRecursivoError` — hook recursion detected
- All errors are raised, never silently caught (hooks log and re-raise).
- `transaction.atomic()` ensures rollback on any failure during create/update.
- Views catch `DynamicFormError` and render error messages back to the user.
- `ProtectedError` caught in legacy delete views for referential integrity.

## Validation Strategy

- **Per-type validation**: Centralized in `apps/platform/dynamic_forms/validators.py` (`_validar_valor_campo`).
- **Multi-step validation**: Called in sequence from `DynamicService.validar_completo()`:
  1. Required fields
  2. Type validation
  3. Uniqueness (for `unico=True` fields)
  4. Custom validation function (if configured)
- **Custom validation**: Python function at a dotted path, receives `(formulario, valores_dict)`, returns `list[str]` of errors.
- **Unique constraint**: Applied at the application level (no database-level `UNIQUE` constraint exists on `ValorCampo.valor`).
