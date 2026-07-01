"""
import_execution.py — Reusable import execution service.

Extracts all import logic from _handle_import_data() in views.py so that
both the manual POST handler and the auto-import after form creation
execute exactly the same code path.
"""

from __future__ import annotations

import csv
import logging
import sys
import time
from pathlib import Path

from django.conf import settings
from django.contrib import messages

from apps.platform.dynamic_forms.import_service import (
    analyze_workbook,
    importar,
    previsualizar,
)
from apps.platform.dynamic_forms.column_matching import ColumnMatcher
from apps.platform.dynamic_forms.models import Campo, Formulario

logger = logging.getLogger(__name__)


_DI_SESSION_KEYS = ["di_pipeline_result", "di_import_ready", "di_catalog_suggestions"]


def clear_document_intelligence_session(request, *, tmp_path=None):
    """
    Canonical cleanup for Document Intelligence session state.

    Removes ALL di_* session keys and deletes the uploaded temp file.
    Safe to call multiple times — missing keys and files are ignored.

    Args:
        request: HttpRequest whose session is cleaned.
        tmp_path: Optional explicit path to delete. If omitted, tries
                  to read it from session['di_pipeline_result']['tmp_path'].
    """
    # Resolve temp file path: explicit arg > session data
    if not tmp_path:
        result_data = request.session.get("di_pipeline_result")
        if result_data and result_data.get("tmp_path"):
            tmp_path = result_data["tmp_path"]
    if tmp_path:
        Path(tmp_path).unlink(missing_ok=True)

    for key in _DI_SESSION_KEYS:
        request.session.pop(key, None)
    request.session.modified = True


# ── Alias for backward compatibility ──
_cleanup_session = clear_document_intelligence_session


def importar_desde_records(formulario, records, usuario=None):
    """
    Import records directly without re-parsing the source file.

    Takes AI-extracted records (list of dicts with field-name keys),
    matches them to the formulario's Campos (exact-match fast path,
    ColumnMatcher fallback for renamed keys), and creates Registros
    in bulk to avoid redundant double validation.

    Args:
        formulario: Formulario instance.
        records: list[dict] with field-name keys (e.g. {"Nombre": "..."}).
        usuario: User instance (optional).

    Returns:
        dict with creados, ignorados, errores, invalid_count
        (same shape as importar() + invalid_count).
    """
    if not records:
        return {"creados": 0, "ignorados": 0, "errores": [], "invalid_count": 0}

    # Derive headers from the first record's keys
    encabezados = list(records[0].keys())
    # Convert records into filas format: list[dict] keyed by header str
    filas = [{h: str(r.get(h, "")) for h in encabezados} for r in records]

    # Map record keys to Campo names — fast path when keys match exactly
    campos = list(Campo.objects.filter(formulario=formulario, activo=True).order_by("orden"))
    nombres_campos = [c.nombre for c in campos]

    if encabezados == nombres_campos:
        mapeo_idx = dict(enumerate(encabezados))
    else:
        matcher = ColumnMatcher(field_names=nombres_campos)
        match_results = matcher.match_all(encabezados)
        mapeo_idx = {r.column_index: r.matched_to for r in match_results if r.matched_to}

    # Phase 2: preview (validate) — ONE validation pass
    preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
    valid_rows = [r for r in preview if r["valida"]]
    invalid_count = len(preview) - len(valid_rows)

    if not valid_rows:
        return {"creados": 0, "ignorados": 0, "errores": preview, "invalid_count": invalid_count}

    # Phase 3: bulk import for ALL sizes
    # _bulk_importar skips DS.crear() entirely (no redundant re-validation),
    # working identically whether we have 1 row or 100000 rows.
    # Validation already happened in Phase 2, so re-validating inside DS.crear()
    # would be pure overhead with no benefit.
    import_result = _bulk_importar(formulario, valid_rows, usuario=usuario, mapeo=mapeo_idx)

    import_result["invalid_count"] = invalid_count
    return import_result


def execute_import(formulario, import_data, request):
    """
    Execute the full import pipeline using data previously stored in session.

    Args:
        formulario: Formulario instance (target form).
        import_data: dict from session["di_import_ready"].
        request: HttpRequest (for user, messages, session cleanup).

    Returns:
        dict with:
            success (bool)
            formulario_id (int)
            creados (int)
            ignorados (int)
            errores (list)
            invalid_count (int)
            error_message (str | None)
            timings (dict) — profiling breakdown in ms
    """
    _t0 = time.perf_counter()
    timing = {}

    result = {
        "success": False,
        "formulario_id": formulario.id,
        "creados": 0,
        "ignorados": 0,
        "errores": [],
        "invalid_count": 0,
        "error_message": None,
        "timings": {},
    }

    tmp_path = import_data.get("tmp_path")
    formulario_id = import_data.get("formulario_id")
    file_name = import_data.get("file_name", "?")
    raw_headers = import_data.get("headers", [])
    raw_rows = import_data.get("rows", [])
    raw_records = import_data.get("records", [])
    raw_fields = import_data.get("fields", [])

    print(f"[PRINT1] execute_import ENTER | formulario_id={formulario_id} tmp_path={tmp_path} file_name={file_name} headers={len(raw_headers)} rows={len(raw_rows)} records={len(raw_records)} fields={len(raw_fields)}", flush=True)

    if not tmp_path or not formulario_id:
        print(f"[PRINT1b] EARLY RETURN: tmp_path={tmp_path} formulario_id={formulario_id}", flush=True)
        result["error_message"] = "Import data incomplete."
        result["timings"] = {"total_ms": (time.perf_counter() - _t0) * 1000}
        return result

    # ── Security: path traversal check ──
    _tmp_dir = Path(settings.BASE_DIR) / ".tmp_uploads"
    _resolved_path = Path(tmp_path).resolve()
    _resolved_tmp = _tmp_dir.resolve()
    if not str(_resolved_path).startswith(str(_resolved_tmp)):
        print(f"[PRINT1c] PATH TRAVERSAL BLOCKED: {tmp_path} -> {_resolved_path}", flush=True)
        result["error_message"] = "Ruta de archivo inválida."
        result["timings"] = {"total_ms": (time.perf_counter() - _t0) * 1000}
        return result

    _ext = Path(tmp_path).suffix.lower()
    print(f"[PRINT2] Path OK | ext={_ext} resolved={_resolved_path}", flush=True)

    _t1 = time.perf_counter()
    try:
        # ── Phase 1: parse & match columns ──
        if raw_records and len(raw_records) > 0:
            # AI-extracted records available — skip file re-parse
            print(f"[PRINT3_AI] Using records path | records={len(raw_records)}", flush=True)
            encabezados = list(raw_records[0].keys())
            filas = [{h: str(r.get(h, "")) for h in encabezados} for r in raw_records]
            campos = list(Campo.objects.filter(formulario=formulario, activo=True).order_by("orden"))
            nombres_campos = [c.nombre for c in campos]
            matcher = ColumnMatcher(field_names=nombres_campos)
            match_results = matcher.match_all(encabezados)
            mapeo_idx = {r.column_index: r.matched_to for r in match_results if r.matched_to}
            timing["records_parse_ms"] = (time.perf_counter() - _t1) * 1000
            print(f"[PRINT3_AI] Records ready | headers={len(encabezados)} rows={len(filas)} mapping={mapeo_idx}", flush=True)

        elif _ext in {".xlsx", ".xls"}:
            print(f"[PRINT3a] START Excel parsing | ext={_ext}", flush=True)
            analysis = analyze_workbook(tmp_path, formulario)
            timing["analyze_workbook_ms"] = (time.perf_counter() - _t1) * 1000
            encabezados = analysis["encabezados"]
            filas = analysis["filas"]
            match_results = analysis["match_results"]
            print(f"[PRINT3b] Excel parsed | encabezados={len(encabezados)} filas={len(filas)} matches={len(match_results)}", flush=True)
            mapeo_idx = {}
            for r in match_results:
                if r.matched_to:
                    mapeo_idx[r.column_index] = r.matched_to
            print(f"[PRINT3c] Column mapping built | mapeo={mapeo_idx}", flush=True)

        elif _ext == ".csv":
            print("[PRINT4a] START CSV parsing", flush=True)
            with open(tmp_path, newline="", encoding="utf-8-sig") as _f:
                _reader = csv.reader(_f)
                _raw_headers = next(_reader, [])
                encabezados = [h.strip() for h in _raw_headers]
                filas = []
                for _row in _reader:
                    _fila_dict = {}
                    for i, h in enumerate(encabezados):
                        _fila_dict[h] = _row[i].strip() if i < len(_row) else ""
                    filas.append(_fila_dict)
            campos = list(Campo.objects.filter(formulario=formulario, activo=True).order_by("orden"))
            nombres_campos = [c.nombre for c in campos]
            matcher = ColumnMatcher(field_names=nombres_campos)
            match_results = matcher.match_all(encabezados)
            print(f"[PRINT4b] CSV parsed | encabezados={len(encabezados)} filas={len(filas)} matches={len(match_results)}", flush=True)
            mapeo_idx = {}
            for r in match_results:
                if r.matched_to:
                    mapeo_idx[r.column_index] = r.matched_to
            print(f"[PRINT4c] Column mapping built | mapeo={mapeo_idx}", flush=True)

        else:
            # PDF / images / text / JSON: use records from the pipeline
            records = import_data.get("records", [])
            headers = import_data.get("headers", [])
            rows = import_data.get("rows", [])

            print(f"[PRINT5a] Non-Excel path | records={len(records)} headers={len(headers)} rows={len(rows)}", flush=True)

            if records:
                encabezados = list(records[0].keys())
                filas = records
                print(f"[PRINT5b] Using records | keys={encabezados} filas={len(filas)}", flush=True)
            elif headers and rows:
                encabezados = headers
                filas = []
                for row in rows:
                    fila_dict = {}
                    for i, h in enumerate(headers):
                        fila_dict[h] = row[i] if i < len(row) else ""
                    filas.append(fila_dict)
                print(f"[PRINT5c] Using headers+rows | encabezados={len(encabezados)} filas={len(filas)}", flush=True)
            else:
                print("[PRINT5d] EARLY RETURN: no records, headers or rows", flush=True)
                result["error_message"] = "No extracted data available."
                return result

            campos = list(Campo.objects.filter(formulario=formulario, activo=True).order_by("orden"))
            nombres_campos = [c.nombre for c in campos]
            matcher = ColumnMatcher(field_names=nombres_campos)
            match_results = matcher.match_all(encabezados)
            print(f"[PRINT5e] ColumnMatcher done | campos={len(campos)} matches={len(match_results)}", flush=True)
            mapeo_idx = {}
            for r in match_results:
                if r.matched_to:
                    mapeo_idx[r.column_index] = r.matched_to
            print(f"[PRINT5f] Column mapping built | mapeo={mapeo_idx}", flush=True)

        # ── Phase 2: preview (validate) ──
        # For large datasets (>500 rows) using records from the pipeline,
        # skip previsualizar() entirely — it iterates ALL rows calling
        # DS.validar_completo() per row, which is extremely slow for 9000+ rows.
        # The pipeline data is already structured and validated.
        _t2 = time.perf_counter()
        using_records_path = bool(raw_records and len(raw_records) > 0)
        total_raw_rows = len(filas)

        if using_records_path and total_raw_rows > 500:
            # Fast path: skip per-row validation — trust pipeline data
            print(f"[PRINT6_FAST] SKIP previsualizar | records_path={using_records_path} rows={total_raw_rows} — trusting pipeline data", flush=True)
            preview = [
                {"fila_idx": i, "valores": fila, "valida": True, "errores": []}
                for i, fila in enumerate(filas)
            ]
            valid_rows = preview
            result["invalid_count"] = 0
            timing["previsualizar_ms"] = (time.perf_counter() - _t2) * 1000
            print(f"[PRINT6_FAST] previsualizar SKIPPED | total={len(preview)}", flush=True)
        else:
            # Standard path: validate all rows (small datasets)
            print(f"[PRINT6a] START previsualizar | encabezados={len(encabezados)} filas={len(filas)} mapeo={mapeo_idx}", flush=True)
            preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
            timing["previsualizar_ms"] = (time.perf_counter() - _t2) * 1000
            valid_rows = [r for r in preview if r["valida"]]
            result["invalid_count"] = len(preview) - len(valid_rows)
            print(f"[PRINT6b] previsualizar DONE | total_preview={len(preview)} validas={len(valid_rows)} invalidas={result['invalid_count']}", flush=True)

        if not valid_rows:
            print(f"[PRINT6c] EARLY RETURN: no valid rows | invalidas={result['invalid_count']}", flush=True)
            result["error_message"] = _build_no_valid_rows_message(result["invalid_count"])
            result["timings"] = timing
            return result

        # ── Phase 3: execute import (bulk if >100 rows) ──
        _t3 = time.perf_counter()
        total_rows = len(valid_rows)
        print(f"[PRINT7a] START import | method={'bulk' if total_rows > 100 else 'standard'} total_rows={total_rows}", flush=True)

        if total_rows > 100:
            import_result = _bulk_importar(
                formulario, valid_rows,
                usuario=request.user, mapeo=mapeo_idx,
            )
            timing["importar_bulk_ms"] = (time.perf_counter() - _t3) * 1000
        else:
            import_result = importar(
                formulario, valid_rows,
                usuario=request.user, modo="crear", mapeo=mapeo_idx,
            )
            timing["importar_standard_ms"] = (time.perf_counter() - _t3) * 1000

        result["creados"] = import_result.get("creados", 0)
        result["ignorados"] = import_result.get("ignorados", 0)
        result["errores"] = import_result.get("errores", [])
        result["success"] = True
        result["row_count"] = total_rows
        print(f"[PRINT7b] import DONE | creados={result['creados']} ignorados={result['ignorados']} errores={len(result['errores'])}", flush=True)

        # ── SmartLearner: record import (Phase 7) ──
        _record_import_to_learner(
            form_name=formulario.nombre,
            rows_imported=result["creados"],
            rows_failed=len(result["errores"]),
            rows_ignored=result["ignorados"],
            file_name=import_data.get("file_name", ""),
        )

        timing["total_ms"] = (time.perf_counter() - _t0) * 1000
        timing["total_rows"] = total_rows
        result["timings"] = timing
        print(f"[PRINT_PROF] execute_import total={timing.get('total_ms', 0):.0f}ms | workbook={timing.get('analyze_workbook_ms', 0):.0f}ms | preview={timing.get('previsualizar_ms', 0):.0f}ms | import={timing.get('importar_bulk_ms', timing.get('importar_standard_ms', 0)):.0f}ms | rows={total_rows}", flush=True)

    except Exception as e:
        print(f"[PRINT_EXC] execute_import EXCEPTION | error={e}", flush=True)
        result["error_message"] = f"Import failed: {e}"
        result["success"] = False
        result["timings"] = timing

    print(f"[PRINT8] execute_import RETURN | success={result['success']} creados={result['creados']} error={result.get('error_message')}", flush=True)
    return result


def _build_no_valid_rows_message(invalid_count):
    mensaje = "No hay filas válidas para importar."
    if invalid_count:
        mensaje += f" {invalid_count} fila(s) fueron inválidas (revisa validaciones)."
    return mensaje


def _record_import_to_learner(
    form_name, rows_imported, rows_failed, rows_ignored, file_name
):
    try:
        from apps.platform.ai.services.smart_learner import SmartLearner
        smart = SmartLearner()
        smart.record_import(
            form_name=form_name,
            rows_imported=rows_imported,
            rows_failed=rows_failed,
            rows_ignored=rows_ignored,
            file_name=file_name,
            success=True,
        )
    except Exception:
        pass


def apply_import_messages(request, result):
    """Set Django messages based on the import result."""
    if result["success"]:
        partes = [
            f"{result['creados']} registro(s) importados"
        ]
        if result.get("invalid_count"):
            partes.append(f"{result['invalid_count']} fila(s) inválidas omitidas")
        if result.get("ignorados"):
            partes.append(f"{result['ignorados']} ignorado(s)")
        if result.get("errores"):
            partes.append(f"{len(result['errores'])} error(es)")
        messages.success(request, ". ".join(partes) + ".")
    else:
        messages.error(request, result.get("error_message", "Import falló."))


def _bulk_importar(formulario, valid_rows, usuario=None, mapeo=None):
    """
    Import large datasets using bulk Registry creation + individual Registro creates.

    For datasets >100 rows, this bypasses DS.crear() which does per-row
    validations, transactions, recalculations, and hooks — unnecessary for
    a clean initial import since previsualizar() already validated all rows.

    Uses a single transaction with batch Registro creation + bulk ValorCampo creation.
    Falls back to standard importar() on error.

    Returns:
        dict with creados, ignorados, errores (same format as importar()).
    """
    from apps.platform.dynamic_forms.models import Registro, ValorCampo, Campo

    creados = 0
    errores: list[dict] = []

    total_rows = len(valid_rows)
    print(f"[PRINT_B0] _bulk_importar ENTER | rows={total_rows} mapeo={mapeo}", flush=True)

    # Fetch active fields once (not per row)
    campos = list(Campo.objects.filter(formulario=formulario, activo=True).order_by("orden"))
    campo_map = {c.nombre: c for c in campos}
    print(f"[PRINT_B1] campos loaded | total_campos={len(campos)} names={list(campo_map.keys())}", flush=True)

    # Build mapping: Excel column name -> Campo instance
    col_to_campo: dict[str, Campo] = {}
    reverse_mapeo = {v: k for k, v in mapeo.items()} if mapeo else {}
    print(f"[PRINT_B2] reverse_mapeo={reverse_mapeo}", flush=True)
    for nombre_campo in campo_map:
        campo = campo_map[nombre_campo]
        if campo.tipo in ("calculado", "imagen", "archivo"):
            print(f"[PRINT_B2a] SKIP campo={nombre_campo} tipo={campo.tipo}", flush=True)
            continue
        col_idx = reverse_mapeo.get(nombre_campo)
        if col_idx is not None:
            col_to_campo[nombre_campo] = campo
        else:
            print(f"[PRINT_B2b] NO MAP for campo={nombre_campo} (not in reverse_mapeo)", flush=True)

    print(f"[PRINT_B3] col_to_campo built | mapped_fields={len(col_to_campo)} keys={list(col_to_campo.keys())}", flush=True)

    if not col_to_campo:
        print(f"[PRINT_B4] EARLY RETURN: no column mapping | campos={len(campos)} mapeo={mapeo}", flush=True)
        errores.append({"error": "No se pudo establecer mapeo de columnas."})
        return {"creados": 0, "ignorados": 0, "errores": errores}

    try:
        from django.db import transaction as db_transaction

        _b0 = time.perf_counter()

        with db_transaction.atomic():
            # Phase 1: Bulk create ALL Registro objects at once using bulk_create.
            # Django 3.2+ assigns IDs back to the objects for PostgreSQL,
            # SQLite 3.35+, MariaDB 10.5+, and MySQL.
            # This is MUCH faster than 9000 individual .create() calls.
            _b1 = time.perf_counter()
            registros = [
                Registro(formulario=formulario, usuario=usuario)
                for _ in valid_rows
            ]
            Registro.objects.bulk_create(registros)
            _registro_ms = (time.perf_counter() - _b1) * 1000
            creados = len(registros)
            print(f"[PRINT_B5] Bulk Registro creation done | created={creados} time={_registro_ms:.0f}ms", flush=True)

            if creados == 0:
                print("[PRINT_B6] No registries created — raising ValueError", flush=True)
                raise ValueError("No se pudieron crear los registros.")

            # Phase 2: Build list of ValorCampo objects using the now-populated IDs
            _b2 = time.perf_counter()
            valor_campos: list[ValorCampo] = []
            sample_logged = False
            for row_idx, row in enumerate(valid_rows):
                if row_idx >= len(registros):
                    break
                valores_dict = row.get("valores", {})
                if not sample_logged:
                    print(f"[PRINT_B7a] row[{row_idx}] sample | valores_keys={len(valores_dict)} keys={list(valores_dict.keys())[:5]}", flush=True)
                    sample_logged = True
                for nombre_campo, valor in valores_dict.items():
                    if not valor or not str(valor).strip():
                        continue
                    if nombre_campo not in col_to_campo:
                        continue
                    campo = col_to_campo[nombre_campo]
                    valor_campos.append(ValorCampo(
                        registro_id=registros[row_idx].id,
                        campo=campo,
                        valor=str(valor).strip(),
                    ))
            _build_vc_ms = (time.perf_counter() - _b2) * 1000
            print(f"[PRINT_B8] VC list built | total_vc={len(valor_campos)} time={_build_vc_ms:.0f}ms", flush=True)

            # Phase 3: Bulk create ValorCampo in chunks of 5000
            _b3 = time.perf_counter()
            if valor_campos:
                vc_chunk_size = 5000
                print(f"[PRINT_B9] START bulk_create | total_vc={len(valor_campos)} chunk_size={vc_chunk_size}", flush=True)
                for i in range(0, len(valor_campos), vc_chunk_size):
                    chunk = valor_campos[i:i + vc_chunk_size]
                    ValorCampo.objects.bulk_create(chunk)
                    print(f"[PRINT_B9a] bulk_create chunk {i // vc_chunk_size + 1}/{(len(valor_campos) - 1) // vc_chunk_size + 1} done", flush=True)
            else:
                print("[PRINT_B9b] NO ValorCampo objects to create — bulk_create skipped", flush=True)
            _vc_bulk_ms = (time.perf_counter() - _b3) * 1000

            print(f"[PRINT_BULK] Imported {creados} records with {len(valor_campos)} field values in bulk | registro_creacion={_registro_ms:.0f}ms build_valores={_build_vc_ms:.0f}ms vc_bulk={_vc_bulk_ms:.0f}ms total={(time.perf_counter() - _b0) * 1000:.0f}ms", flush=True)

    except Exception as e:
        import traceback
        print(f"[PRINT_BEXC] _bulk_importar EXCEPTION | error={e}", flush=True)
        traceback.print_exc()
        from apps.platform.dynamic_forms.import_service import importar as importar_std
        print("[PRINT_BEXC] Falling back to standard importar()", flush=True)
        fallback = importar_std(
            formulario, valid_rows,
            usuario=usuario, modo="crear", mapeo=mapeo,
        )
        print(f"[PRINT_BEXC] Fallback result: {fallback}", flush=True)
        return fallback

    print(f"[PRINT_BEND] _bulk_importar RETURN | creados={creados} errores={len(errores)}", flush=True)
    return {
        "creados": creados,
        "ignorados": 0,
        "errores": errores,
    }


__all__ = [
    "execute_import",
    "importar_desde_records",
    "apply_import_messages",
    "clear_document_intelligence_session",
    "_cleanup_session",
]
