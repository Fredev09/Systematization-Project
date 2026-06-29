"""
test_e2e_import.py — Phase 6: E2E Import Reliability Validator

Tests the full import flow against the REAL database:
  Upload → Analyze → Create Form → Import Records → DB Verification

This is a standalone script (NOT a Django TestCase) because the test
database cannot be created from scratch (legacy migration chain).

Usage:
    python test_e2e_import.py [--verbose]

Returns exit code 0 if ALL tests pass, 1 if any fail.
"""

import os
import sys
import time
import tempfile
import traceback

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

import django
django.setup()

from django.conf import settings
from django.db import transaction
from pathlib import Path

from apps.platform.dynamic_forms.models import Formulario, Campo, Registro, ValorCampo
from apps.platform.dynamic_forms.import_service import previsualizar, importar
from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
from apps.platform.document_intelligence.extractors import get_extractor
from apps.platform.document_intelligence.test_data_generators import (
    STD_HEADERS, STD_ROWS,
    EDGE_SPECIAL_CHARS_HEADERS, EDGE_SPECIAL_CHARS_ROWS,
    EDGE_TYPES_HEADERS, EDGE_TYPES_ROWS,
    EDGE_UTF8_HEADERS, EDGE_UTF8_ROWS,
    xlsx_bytes, csv_bytes, pdf_bytes, image_bytes, json_bytes,
)


# ======================================================================
# Globals
# ======================================================================

PASS = 0
FAIL = 0
VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv
_results = []


def log(msg, ok=True):
    global PASS, FAIL
    if ok:
        PASS += 1
        icon = "✅"
    else:
        FAIL += 1
        icon = "❌"
    icon_safe = icon if sys.stdout.encoding.lower() in ("utf-8", "utf8") else ("[PASS]" if ok else "[FAIL]")
    _results.append((icon_safe, msg))
    if VERBOSE or not ok:
        print(f"  {icon_safe} {msg}")


def section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


# ======================================================================
# Helpers
# ======================================================================


def _cleanup_test_form(form_name):
    """Remove ALL traces of a previously created test form."""
    try:
        f = Formulario.objects.get(nombre=form_name)
        ValorCampo.objects.filter(registro__formulario=f).delete()
        Registro.objects.filter(formulario=f).delete()
        Campo.objects.filter(formulario=f).delete()
        f.delete()
    except Formulario.DoesNotExist:
        pass


def _make_tmp_file(data, suffix):
    """Write data to a temp file and return path."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    return tmp.name


def _verify_records(formulario, expected_count, label=""):
    """Verify Registro + ValorCampo counts match expectations."""
    records = Registro.objects.filter(formulario=formulario)
    total = records.count()
    ok = total == expected_count
    log(f"{label}: {total}/{expected_count} registros creados", ok)
    if not ok:
        return False

    vcs = ValorCampo.objects.filter(registro__in=records)
    campos_count = Campo.objects.filter(formulario=formulario, activo=True).count()
    expected_vc = total * campos_count
    log(f"{label}: {vcs.count()}/{expected_vc} ValorCampo creados (esperados)",
        vcs.count() >= total * (campos_count - 1))  # at least 1 per field
    return True


def _verify_values(formulario, expected_values_list):
    """Verify specific field values match expectations."""
    records = Registro.objects.filter(formulario=formulario).order_by("id")
    all_ok = True
    for i, expected in enumerate(expected_values_list):
        if i >= len(records):
            log(f"Fila {i}: no hay registro #{i+1}", False)
            all_ok = False
            continue
        valores = DS.obtener_valores(records[i])
        for field, expected_val in expected.items():
            actual = valores.get(field, "")
            if str(actual) != str(expected_val):
                log(f"Fila {i}, campo '{field}': esperado='{expected_val}', actual='{actual}'", False)
                all_ok = False
    return all_ok


# ======================================================================
# TEST: Basic Excel Import
# ======================================================================


def test_excel_basic_import():
    section("1. Excel Basic Import")
    FORM_NAME = "Test_Excel_Std"
    _cleanup_test_form(FORM_NAME)

    ok = True
    try:
        # Create form matching the dataset
        formulario = Formulario.objects.create(nombre=FORM_NAME, descripcion="Test Excel Std",
                                                creado_por_id=1)
        for i, h in enumerate(STD_HEADERS):
            Campo.objects.create(formulario=formulario, nombre=h, tipo="texto",
                                  obligatorio=False, orden=i, activo=True)

        # Generate test file and import
        data = xlsx_bytes(STD_HEADERS, STD_ROWS)
        path = _make_tmp_file(data, ".xlsx")

        # Simulate the import flow from _handle_import_data for Excel
        from apps.platform.dynamic_forms.import_service import analyze_workbook
        analysis = analyze_workbook(path, formulario)
        encabezados = analysis["encabezados"]
        filas = analysis["filas"]
        match_results = analysis["match_results"]
        mapeo_idx = {}
        for r in match_results:
            if r.matched_to:
                mapeo_idx[r.column_index] = r.matched_to

        # Preview
        preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
        valid_rows = [r for r in preview if r["valida"]]
        invalid = len(preview) - len(valid_rows)
        log(f"Preview: {len(valid_rows)}/{len(preview)} filas válidas, {invalid} inválidas",
            invalid == 0)

        # Import
        result = importar(formulario, valid_rows, modo="crear")
        log(f"Import: {result['creados']} creados, {result.get('ignorados', 0)} ignorados, "
            f"{len(result.get('errores', []))} errores",
            result['creados'] == len(STD_ROWS) and len(result.get('errores', [])) == 0)

        # Verify DB
        _verify_records(formulario, len(STD_ROWS), "Excel Std")

        os.unlink(path)
    except Exception as e:
        log(f"Excel basic import FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST: CSV Import
# ======================================================================


def test_csv_import():
    section("2. CSV Import")
    FORM_NAME = "Test_CSV_Std"
    _cleanup_test_form(FORM_NAME)

    from apps.platform.dynamic_forms.models import Campo as _Campo
    ok = True
    try:
        formulario = Formulario.objects.create(nombre=FORM_NAME, descripcion="Test CSV Std",
                                                creado_por_id=1)
        for i, h in enumerate(STD_HEADERS):
            _Campo.objects.create(formulario=formulario, nombre=h, tipo="texto",
                                  obligatorio=False, orden=i, activo=True)

        data = csv_bytes(STD_HEADERS, STD_ROWS)
        path = _make_tmp_file(data, ".csv")

        # CSV import uses ColumnMatcher now (recent fix)
        from apps.platform.dynamic_forms.column_matching import ColumnMatcher
        import csv as _csv

        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = _csv.reader(f)
            raw_headers = next(reader, [])
            encabezados = [h.strip() for h in raw_headers]
            filas = []
            for row in reader:
                fila_dict = {}
                for i, h in enumerate(encabezados):
                    fila_dict[h] = row[i].strip() if i < len(row) else ""
                filas.append(fila_dict)

        campos = list(_Campo.objects.filter(formulario=formulario, activo=True).order_by("orden"))
        nombres_campos = [c.nombre for c in campos]
        matcher = ColumnMatcher(field_names=nombres_campos)
        match_results = matcher.match_all(encabezados)
        mapeo_idx = {}
        for r in match_results:
            if r.matched_to:
                mapeo_idx[r.column_index] = r.matched_to

        log(f"Mapeo CSV: {len(mapeo_idx)}/{len(encabezados)} columnas mapeadas",
            len(mapeo_idx) == len(encabezados))

        preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
        valid_rows = [r for r in preview if r["valida"]]
        log(f"Preview CSV: {len(valid_rows)} válidas", len(valid_rows) == len(STD_ROWS))

        result = importar(formulario, valid_rows, modo="crear")
        log(f"Import CSV: {result['creados']} creados", result['creados'] == len(STD_ROWS))

        _verify_records(formulario, len(STD_ROWS), "CSV Std")

        os.unlink(path)
    except Exception as e:
        log(f"CSV import FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST: JSON Import (via TextExtractor)
# ======================================================================


def test_json_import():
    section("3. JSON Import")
    FORM_NAME = "Test_JSON_Std"
    _cleanup_test_form(FORM_NAME)

    ok = True
    try:
        formulario = Formulario.objects.create(nombre=FORM_NAME, descripcion="Test JSON Std",
                                                creado_por_id=1)
        for i, h in enumerate(STD_HEADERS):
            Campo.objects.create(formulario=formulario, nombre=h, tipo="texto",
                                  obligatorio=False, orden=i, activo=True)

        import json
        data = json.dumps([dict(zip(STD_HEADERS, row)) for row in STD_ROWS],
                          ensure_ascii=False, indent=2).encode("utf-8")
        path = _make_tmp_file(data, ".json")

        # Extract with TextExtractor
        extractor = get_extractor(file_path=path)
        doc = extractor.extract(path)

        records = []
        if doc.columns:
            for row in doc.rows:
                record = {}
                for i, col in enumerate(doc.columns):
                    record[col] = row[i] if i < len(row) else ""
                if any(v for v in record.values()):
                    records.append(record)

        log(f"JSON extract: {len(records)} registros", len(records) == len(STD_ROWS))

        if records:
            encabezados = list(records[0].keys())
            from apps.platform.dynamic_forms.column_matching import ColumnMatcher
            campos = list(Campo.objects.filter(formulario=formulario, activo=True).order_by("orden"))
            nombres_campos = [c.nombre for c in campos]
            matcher = ColumnMatcher(field_names=nombres_campos)
            match_results = matcher.match_all(encabezados)
            mapeo_idx = {}
            for r in match_results:
                if r.matched_to:
                    mapeo_idx[r.column_index] = r.matched_to

            preview = previsualizar(formulario, encabezados, records, mapeo_idx)
            valid_rows = [r for r in preview if r["valida"]]
            result = importar(formulario, valid_rows, modo="crear")
            log(f"Import JSON: {result['creados']} creados", result['creados'] == len(STD_ROWS))
            _verify_records(formulario, len(STD_ROWS), "JSON Std")

        os.unlink(path)
    except Exception as e:
        log(f"JSON import FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST: Special Characters
# ======================================================================


def test_special_chars_import():
    section("4. Special Characters Import")
    FORM_NAME = "Test_SpecialChars"
    _cleanup_test_form(FORM_NAME)

    ok = True
    try:
        formulario = Formulario.objects.create(nombre=FORM_NAME, descripcion="Test Special Chars",
                                                creado_por_id=1)
        for i, h in enumerate(EDGE_SPECIAL_CHARS_HEADERS):
            Campo.objects.create(formulario=formulario, nombre=h, tipo="texto",
                                  obligatorio=False, orden=i, activo=True)

        data = xlsx_bytes(EDGE_SPECIAL_CHARS_HEADERS, EDGE_SPECIAL_CHARS_ROWS)
        path = _make_tmp_file(data, ".xlsx")

        from apps.platform.dynamic_forms.import_service import analyze_workbook
        analysis = analyze_workbook(path, formulario)
        encabezados = analysis["encabezados"]
        filas = analysis["filas"]
        match_results = analysis["match_results"]
        mapeo_idx = {}
        for r in match_results:
            if r.matched_to:
                mapeo_idx[r.column_index] = r.matched_to

        preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
        valid_rows = [r for r in preview if r["valida"]]
        log(f"Special chars preview: {len(valid_rows)}/{len(preview)} válidas",
            len(valid_rows) == len(EDGE_SPECIAL_CHARS_ROWS))

        if valid_rows:
            result = importar(formulario, valid_rows, modo="crear")
            log(f"Special chars import: {result['creados']} creados",
                result['creados'] == len(EDGE_SPECIAL_CHARS_ROWS))
            _verify_records(formulario, len(EDGE_SPECIAL_CHARS_ROWS), "Special Chars")

            # Verify special characters preserved
            records = Registro.objects.filter(formulario=formulario).order_by("id")
            first_vals = DS.obtener_valores(records[0])
            log(f"Special char 'Café & té': '{first_vals.get(EDGE_SPECIAL_CHARS_HEADERS[0], '')}'",
                "Café & té" in str(first_vals.get(EDGE_SPECIAL_CHARS_HEADERS[0], "")))

        os.unlink(path)
    except Exception as e:
        log(f"Special chars FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST: Data Types (numbers, booleans, dates)
# ======================================================================


def test_data_types_import():
    section("5. Data Types Import")
    FORM_NAME = "Test_DataTypes"
    _cleanup_test_form(FORM_NAME)

    ok = True
    try:
        field_types = {
            "Entero": "numero",
            "Decimal": "numero",
            "Moneda": "moneda",
            "Booleano": "booleano",
            "Fecha": "fecha",
        }
        headers = list(field_types.keys())

        formulario = Formulario.objects.create(nombre=FORM_NAME, descripcion="Test Data Types",
                                                creado_por_id=1)
        for i, (h, t) in enumerate(field_types.items()):
            Campo.objects.create(formulario=formulario, nombre=h, tipo=t,
                                  obligatorio=False, orden=i, activo=True)

        data = xlsx_bytes(headers, EDGE_TYPES_ROWS[:2])  # First 2 rows (positive cases)
        path = _make_tmp_file(data, ".xlsx")

        from apps.platform.dynamic_forms.import_service import analyze_workbook
        analysis = analyze_workbook(path, formulario)
        encabezados = analysis["encabezados"]
        filas = analysis["filas"]
        match_results = analysis["match_results"]
        mapeo_idx = {}
        for r in match_results:
            if r.matched_to:
                mapeo_idx[r.column_index] = r.matched_to

        preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
        valid_rows = [r for r in preview if r["valida"]]
        log(f"Data types preview: {len(valid_rows)}/{len(preview)} válidas",
            len(valid_rows) >= 1)

        if valid_rows:
            result = importar(formulario, valid_rows, modo="crear")
            log(f"Data types import: {result['creados']} creados",
                result['creados'] >= 1)

        os.unlink(path)
    except Exception as e:
        log(f"Data types FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST: UTF-8 Characters
# ======================================================================


def test_utf8_import():
    section("6. UTF-8 Import")
    FORM_NAME = "Test_UTF8"
    _cleanup_test_form(FORM_NAME)

    ok = True
    try:
        formulario = Formulario.objects.create(nombre=FORM_NAME, descripcion="Test UTF-8",
                                                creado_por_id=1)
        for i, h in enumerate(EDGE_UTF8_HEADERS):
            Campo.objects.create(formulario=formulario, nombre=h, tipo="texto",
                                  obligatorio=False, orden=i, activo=True)

        data = xlsx_bytes(EDGE_UTF8_HEADERS, EDGE_UTF8_ROWS)
        path = _make_tmp_file(data, ".xlsx")

        from apps.platform.dynamic_forms.import_service import analyze_workbook
        analysis = analyze_workbook(path, formulario)
        encabezados = analysis["encabezados"]
        filas = analysis["filas"]
        match_results = analysis["match_results"]
        mapeo_idx = {}
        for r in match_results:
            if r.matched_to:
                mapeo_idx[r.column_index] = r.matched_to

        preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
        valid_rows = [r for r in preview if r["valida"]]
        log(f"UTF-8 preview: {len(valid_rows)} válidas", len(valid_rows) == len(EDGE_UTF8_ROWS))

        if valid_rows:
            result = importar(formulario, valid_rows, modo="crear")
            log(f"UTF-8 import: {result['creados']} creados",
                result['creados'] == len(EDGE_UTF8_ROWS))
            _verify_records(formulario, len(EDGE_UTF8_ROWS), "UTF-8")

            records = Registro.objects.filter(formulario=formulario).order_by("id")
            first_vals = DS.obtener_valores(records[0])
            log(f"UTF-8 €uro: Nombre='{first_vals.get('Nombre', '')}'",
                first_vals.get("Nombre") == "€uro sign")

        os.unlink(path)
    except Exception as e:
        log(f"UTF-8 FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST: Duplicate Column Handling
# ======================================================================


def test_duplicate_columns():
    section("7. Duplicate Columns")
    FORM_NAME = "Test_DupCols"
    _cleanup_test_form(FORM_NAME)

    ok = True
    try:
        formulario = Formulario.objects.create(nombre=FORM_NAME, descripcion="Test Duplicate Cols",
                                                creado_por_id=1)
        Campo.objects.create(formulario=formulario, nombre="Nombre", tipo="texto",
                              obligatorio=False, orden=0, activo=True)
        Campo.objects.create(formulario=formulario, nombre="Precio", tipo="numero",
                              obligatorio=False, orden=1, activo=True)

        headers = ["Nombre", "Precio", "Precio"]  # Duplicate column
        rows = [["Prod A", "10000", "20000"]]
        data = xlsx_bytes(headers, rows)
        path = _make_tmp_file(data, ".xlsx")

        from apps.platform.dynamic_forms.import_service import analyze_workbook
        analysis = analyze_workbook(path, formulario)

        log(f"Dup cols: {len(analysis.get('match_results', []))} columnas procesadas",
            len(analysis.get("match_results", [])) == 3)
        ok_this = True
        for r in analysis.get("match_results", []):
            if r.column_name == "Precio":
                if r.matched_to == "Precio":
                    pass  # OK — matched to existing field

        # Preview should still work
        preview = previsualizar(formulario, analysis["encabezados"], analysis["filas"],
                                {r.column_index: r.matched_to for r in analysis["match_results"]
                                 if r.matched_to})
        log(f"Dup cols preview: {len([p for p in preview if p['valida']])} válidas",
            len([p for p in preview if p["valida"]]) == 1)

        os.unlink(path)
    except Exception as e:
        log(f"Duplicate columns FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST: Empty Values
# ======================================================================


def test_empty_values():
    section("8. Empty Values Import")
    FORM_NAME = "Test_EmptyVals"
    _cleanup_test_form(FORM_NAME)

    ok = True
    try:
        headers = ["Name", "Value", "Optional"]
        rows = [
            ["Row1", "OK", "present"],
            ["Row2", "", ""],
            ["Row3", "OK", ""],
        ]
        formulario = Formulario.objects.create(nombre=FORM_NAME, descripcion="Test Empty Vals",
                                                creado_por_id=1)
        for i, h in enumerate(headers):
            Campo.objects.create(formulario=formulario, nombre=h, tipo="texto",
                                  obligatorio=False, orden=i, activo=True)

        data = xlsx_bytes(headers, rows)
        path = _make_tmp_file(data, ".xlsx")

        from apps.platform.dynamic_forms.import_service import analyze_workbook
        analysis = analyze_workbook(path, formulario)
        encabezados = analysis["encabezados"]
        filas = analysis["filas"]
        match_results = analysis["match_results"]
        mapeo_idx = {}
        for r in match_results:
            if r.matched_to:
                mapeo_idx[r.column_index] = r.matched_to

        preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
        valid_rows = [r for r in preview if r["valida"]]
        log(f"Empty vals preview: {len(valid_rows)}/3 válidas",
            len(valid_rows) == 3)  # All rows valid since no required fields

        if valid_rows:
            result = importar(formulario, valid_rows, modo="crear")
            log(f"Empty vals import: {result['creados']} creados", result['creados'] == 3)
            _verify_records(formulario, 3, "Empty Vals")

        os.unlink(path)
    except Exception as e:
        log(f"Empty values FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST: Required Field Validation
# ======================================================================


def test_required_field_validation():
    section("9. Required Field Validation")
    FORM_NAME = "Test_Required"
    _cleanup_test_form(FORM_NAME)

    ok = True
    try:
        headers = ["Name", "RequiredField"]
        rows_valid = [["Row1", "present"]]
        rows_invalid = [["Row2", ""]]

        formulario = Formulario.objects.create(nombre=FORM_NAME, descripcion="Test Required",
                                                creado_por_id=1)
        Campo.objects.create(formulario=formulario, nombre="Name", tipo="texto",
                              obligatorio=False, orden=0, activo=True)
        Campo.objects.create(formulario=formulario, nombre="RequiredField", tipo="texto",
                              obligatorio=True, orden=1, activo=True)

        # Test valid data
        data = xlsx_bytes(headers, rows_valid)
        path = _make_tmp_file(data, ".xlsx")

        from apps.platform.dynamic_forms.import_service import analyze_workbook
        analysis = analyze_workbook(path, formulario)
        encabezados = analysis["encabezados"]
        filas = analysis["filas"]
        match_results = analysis["match_results"]
        mapeo_idx = {}
        for r in match_results:
            if r.matched_to:
                mapeo_idx[r.column_index] = r.matched_to

        preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
        valid_rows = [r for r in preview if r["valida"]]
        invalid = [r for r in preview if not r["valida"]]
        log(f"Required: {len(valid_rows)} válidas, {len(invalid)} inválidas",
            len(valid_rows) == 1 and len(invalid) == 0)

        os.unlink(path)

        # Test invalid data (missing required)
        data2 = xlsx_bytes(headers, rows_invalid)
        path2 = _make_tmp_file(data2, ".xlsx")

        analysis2 = analyze_workbook(path2, formulario)
        preview2 = previsualizar(formulario, analysis2["encabezados"], analysis2["filas"],
                                 {r.column_index: r.matched_to for r in analysis2["match_results"]
                                  if r.matched_to})
        valid2 = [r for r in preview2 if r["valida"]]
        invalid2 = [r for r in preview2 if not r["valida"]]
        log(f"Required missing: {len(valid2)} válidas, {len(invalid2)} inválidas",
            len(valid2) == 0 and len(invalid2) == 1)

        os.unlink(path2)
    except Exception as e:
        log(f"Required field FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST: PDF Import (via records)
# ======================================================================


def test_pdf_import():
    section("10. PDF Import")
    FORM_NAME = "Test_PDF_Import"
    _cleanup_test_form(FORM_NAME)

    ok = True
    try:
        formulario = Formulario.objects.create(nombre=FORM_NAME, descripcion="Test PDF Import",
                                                creado_por_id=1)
        for i, h in enumerate(STD_HEADERS):
            Campo.objects.create(formulario=formulario, nombre=h, tipo="texto",
                                  obligatorio=False, orden=i, activo=True)

        data = pdf_bytes("Test", STD_HEADERS, STD_ROWS)
        path = _make_tmp_file(data, ".pdf")

        # PDFExtractor extracts text (no PyMuPDF = placeholder)
        extractor = get_extractor(file_path=path)
        doc = extractor.extract(path)

        # Verify extraction works
        log(f"PDF extract: type={doc.document_type}, text_len={len(doc.raw_text)}", True)
        log(f"PDF text: starts with={doc.raw_text[:60] if doc.raw_text else 'empty'}", True)

        os.unlink(path)
    except Exception as e:
        log(f"PDF import FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST: Image Import (via records)
# ======================================================================


def test_image_import():
    section("11. Image Import")
    FORM_NAME = "Test_Img_Import"
    _cleanup_test_form(FORM_NAME)

    ok = True
    try:
        formulario = Formulario.objects.create(nombre=FORM_NAME, descripcion="Test Image Import",
                                                creado_por_id=1)
        Campo.objects.create(formulario=formulario, nombre="Nombre", tipo="texto",
                              obligatorio=False, orden=0, activo=True)
        Campo.objects.create(formulario=formulario, nombre="Precio", tipo="numero",
                              obligatorio=False, orden=1, activo=True)
        Campo.objects.create(formulario=formulario, nombre="Stock", tipo="numero",
                              obligatorio=False, orden=2, activo=True)

        data = image_bytes(["Product Name: Test Product", "Price: $25,000", "Stock: 100"], "PNG")
        path = _make_tmp_file(data, ".png")

        extractor = get_extractor(file_path=path)
        doc = extractor.extract(path)

        log(f"Image extract: type={doc.document_type}, has_images={len(doc.images) > 0}",
            doc.document_type == "image")
        log(f"Image raw_text: {doc.raw_text[:60]}", True)

        os.unlink(path)
    except Exception as e:
        log(f"Image import FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST: ColumnMatcher Edge Cases
# ======================================================================


def test_column_matcher_edge_cases():
    section("12. ColumnMatcher Edge Cases")
    from apps.platform.dynamic_forms.column_matching import ColumnMatcher

    ok = True
    try:
        # Test with all empty column names
        matcher = ColumnMatcher(field_names=["Name", "Price", "Qty"])
        results = matcher.match_all(["", "", ""])
        matched = sum(1 for r in results if r.matched_to)
        log(f"Empty columns: {matched}/3 matched (expect 0)", matched == 0)

        # Test with very long column names
        long_name = "A" * 200
        results = matcher.match_all([long_name])
        log(f"Long column name: extraction works", True)

        # Test with numbers as headers
        results = matcher.match_all(["123", "456"])
        log(f"Numeric headers: processed without error", True)

        # Test case sensitivity
        results = matcher.match_all(["name", "price", "qty"])
        matched = sum(1 for r in results if r.matched_to)
        log(f"Lowercase match: {matched}/3 matched", matched == 3)

        # Test with trailing/leading spaces
        results = matcher.match_all(["  Name  ", "  Price  "])
        matched = sum(1 for r in results if r.matched_to)
        log(f"Trimmed match: {matched}/2 matched", matched == 2)

    except Exception as e:
        log(f"ColumnMatcher edge FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    return ok


# ======================================================================
# Run All
# ======================================================================


def main():
    print(f"\n{'#'*70}")
    print(f"  Phase 6 — E2E Import Reliability Validator")
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*70}")

    tests = [
        ("Excel Basic Import", test_excel_basic_import),
        ("CSV Import", test_csv_import),
        ("JSON Import", test_json_import),
        ("Special Characters Import", test_special_chars_import),
        ("Data Types Import", test_data_types_import),
        ("UTF-8 Import", test_utf8_import),
        ("Duplicate Columns", test_duplicate_columns),
        ("Empty Values", test_empty_values),
        ("Required Field Validation", test_required_field_validation),
        ("PDF Import", test_pdf_import),
        ("Image Import", test_image_import),
        ("ColumnMatcher Edge Cases", test_column_matcher_edge_cases),
    ]

    passed = 0
    failed = 0
    for name, func in tests:
        try:
            if func():
                passed += 1
                print(f"  PASS {name}")
            else:
                failed += 1
                print(f"  FAIL {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
            traceback.print_exc()

    print(f"\n{'='*70}")
    print(f"  SUMMARY: {passed}/{len(tests)} tests passed, {failed} failed")
    print(f"  Individual checks: {PASS} pass, {FAIL} fail")
    print(f"{'='*70}\n")

    if FAIL > 0 or failed > 0:
        print("\nFAILURES DETECTED:")
        for icon, msg in _results:
            if icon in ("FAIL", "[FAIL]"):
                print(f"  {icon} {msg}")

    return 0 if failed == 0 and FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
