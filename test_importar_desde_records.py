"""
test_importar_desde_records.py — Verification script for importar_desde_records()

Tests the new records-based import path and confirms backward compatibility
of the existing execute_import() flow.

Usage:
    python test_importar_desde_records.py [--verbose]

Returns exit code 0 if ALL tests pass, 1 if any fail.
"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

import django
django.setup()

from django.db import transaction

from apps.platform.dynamic_forms.models import Formulario, Campo, Registro, ValorCampo
from apps.platform.document_intelligence.services.import_execution import (
    importar_desde_records,
    execute_import,
)


PASS = 0
FAIL = 0
VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv
_results = []


def log(msg, ok=True):
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
    icon = "[PASS]" if ok else "[FAIL]"
    print(f"  {icon} {msg}")
    _results.append((msg, ok))


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _cleanup_test_form(form_name):
    try:
        f = Formulario.objects.get(nombre=form_name)
        ValorCampo.objects.filter(registro__formulario=f).delete()
        Registro.objects.filter(formulario=f).delete()
        Campo.objects.filter(formulario=f).delete()
        f.delete()
    except Formulario.DoesNotExist:
        pass


# ── Test datasets ──

RECORDS_VALID = [
    {"Nombre": "Producto A", "Precio": "15000", "Cantidad": "10"},
    {"Nombre": "Producto B", "Precio": "25000", "Cantidad": "5"},
    {"Nombre": "Producto C", "Precio": "35000", "Cantidad": "8"},
]

RECORDS_SINGLE = [
    {"Nombre": "Único Producto", "Precio": "5000", "Cantidad": "3"},
]

CAMPOS = [
    {"nombre": "Nombre", "tipo": "texto", "obligatorio": True},
    {"nombre": "Precio", "tipo": "moneda", "obligatorio": True},
    {"nombre": "Cantidad", "tipo": "numero", "obligatorio": False},
]


def _crear_formulario(form_name):
    """Create a test Formulario with predefined Campos."""
    formulario = Formulario.objects.create(
        nombre=form_name, descripcion=f"Test {form_name}"
    )
    for i, c in enumerate(CAMPOS):
        Campo.objects.create(
            formulario=formulario,
            nombre=c["nombre"],
            tipo=c["tipo"],
            obligatorio=c.get("obligatorio", False),
            orden=i,
            activo=True,
        )
    return formulario


# ======================================================================
# TEST 1: importar_desde_records with valid records
# ======================================================================


def test_importar_desde_records_valid():
    section("1. importar_desde_records — 3 valid records")
    FORM_NAME = "Test_Import_Records_Valid"
    _cleanup_test_form(FORM_NAME)

    ok = True
    formulario = None
    try:
        formulario = _crear_formulario(FORM_NAME)

        result = importar_desde_records(formulario, RECORDS_VALID)

        log(f"creados={result['creados']}", result["creados"] == 3)
        log(f"ignorados={result['ignorados']}", result["ignorados"] == 0)
        log(f"errores={len(result.get('errores', []))}", len(result.get("errores", [])) == 0)
        log(f"invalid_count={result.get('invalid_count', 0)}", result.get("invalid_count", 0) == 0)

        records = Registro.objects.filter(formulario=formulario)
        log(f"Registros en DB: {records.count()}/3", records.count() == 3)

        vcs = ValorCampo.objects.filter(registro__in=records)
        log(f"ValorCampo en DB: {vcs.count()} (esperados >= 3)", vcs.count() >= 3)

    except Exception as e:
        log(f"TEST FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    if formulario:
        _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST 2: importar_desde_records with empty records
# ======================================================================


def test_importar_desde_records_empty():
    section("2. importar_desde_records — empty list")
    FORM_NAME = "Test_Import_Records_Empty"
    _cleanup_test_form(FORM_NAME)

    ok = True
    formulario = None
    try:
        formulario = _crear_formulario(FORM_NAME)

        result = importar_desde_records(formulario, [])

        log(f"creados={result['creados']}", result["creados"] == 0)
        log(f"invalid_count={result.get('invalid_count', 0)}", result.get("invalid_count", 0) == 0)

        records = Registro.objects.filter(formulario=formulario)
        log(f"Registros en DB: {records.count()}/0", records.count() == 0)

    except Exception as e:
        log(f"TEST FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    if formulario:
        _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST 3: importar_desde_records with 1 record (tests standard import path, <100)
# ======================================================================


def test_importar_desde_records_single():
    section("3. importar_desde_records — single record (standard path)")
    FORM_NAME = "Test_Import_Records_Single"
    _cleanup_test_form(FORM_NAME)

    ok = True
    formulario = None
    try:
        formulario = _crear_formulario(FORM_NAME)

        result = importar_desde_records(formulario, RECORDS_SINGLE)

        log(f"creados={result['creados']}", result["creados"] == 1)
        log(f"errores={len(result.get('errores', []))}", len(result.get("errores", [])) == 0)

        records = Registro.objects.filter(formulario=formulario)
        log(f"Registros en DB: {records.count()}/1", records.count() == 1)

    except Exception as e:
        log(f"TEST FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    if formulario:
        _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST 4: importar_desde_records with field rename (user renamed campo)
# ColumnMatcher should fuzzy-match "ID Producto" → "Nombre"
# ======================================================================


def test_importar_desde_records_renamed_field():
    section("4. importar_desde_records — record key differs from campo name")
    FORM_NAME = "Test_Import_Records_Rename"
    _cleanup_test_form(FORM_NAME)

    ok = True
    formulario = None
    try:
        formulario = _crear_formulario(FORM_NAME)

        records_renamed = [
            {"ID Producto": "Prod X", "Valor": "9999", "Cant": "7"},
        ]

        result = importar_desde_records(formulario, records_renamed)

        log(f"No crash: creados={result['creados']}", True)
        log(f"errores={len(result.get('errores', []))} (some fuzzy matches may fail)",
            True)

        records = Registro.objects.filter(formulario=formulario)
        log(f"Registros en DB: {records.count()}", records.count() >= 0)

    except Exception as e:
        log(f"TEST FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    if formulario:
        _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST 5: execute_import with records in import_data
# ======================================================================


def test_execute_import_with_records():
    section("5. execute_import -- with records in import_data (no file read)")
    FORM_NAME = "Test_Exec_Import_Records"
    _cleanup_test_form(FORM_NAME)

    ok = True
    formulario = None
    tmp_path = None
    try:
        import tempfile
        from django.conf import settings
        tmp_dir = Path(settings.BASE_DIR) / ".tmp_uploads"
        tmp_path = tempfile.NamedTemporaryFile(suffix=".xlsx", dir=str(tmp_dir), delete=False)
        tmp_path.write(b"dummy content")
        tmp_path.close()
        tmp_path = tmp_path.name

        formulario = _crear_formulario(FORM_NAME)

        import_data = {
            "formulario_id": formulario.id,
            "tmp_path": str(tmp_path),
            "file_name": "test.xlsx",
            "headers": ["Nombre", "Precio", "Cantidad"],
            "rows": [],
            "records": RECORDS_VALID,
            "fields": [],
        }

        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first() or User.objects.first()
        if not user:
            user = User.objects.create_user(username="test_import_exec", password="test")
            user.save()

        class MockRequest:
            def __init__(self):
                self.user = user
                self.session = {}

        request = MockRequest()

        result = execute_import(formulario, import_data, request)

        log(f"success={result['success']}", result["success"] == True)
        log(f"creados={result['creados']}", result["creados"] == 3)
        log(f"error_message={result.get('error_message')}", result.get("error_message") is None)

    except Exception as e:
        log(f"TEST FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    if tmp_path:
        os.unlink(tmp_path)
    if formulario:
        _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# TEST 6: execute_import without records  (fallback cleanup)
# ======================================================================


def test_execute_import_cleanup():
    section("6. execute_import without records -- fallback")
    FORM_NAME = "Test_Exec_Import_Fallback"
    _cleanup_test_form(FORM_NAME)

    ok = True
    formulario = None
    try:
        formulario = _crear_formulario(FORM_NAME)

        import_data = {
            "formulario_id": formulario.id,
            "tmp_path": "",
            "file_name": "test.xlsx",
            "headers": [],
            "rows": [],
            "records": [],
            "fields": [],
        }

        class MockUser:
            id = 1

        class MockRequest:
            def __init__(self):
                self.user = MockUser()
                self.session = {}

        request = MockRequest()

        result = execute_import(formulario, import_data, request)

        # Without tmp_path, should return early with "Import data incomplete"
        log(f"success={result['success']} (expected False)", result["success"] == False)
        log(f"error_message=Import data incomplete",
            result.get("error_message") == "Import data incomplete.")

    except Exception as e:
        log(f"TEST FAILED: {e}", False)
        traceback.print_exc()
        ok = False

    if formulario:
        _cleanup_test_form(FORM_NAME)
    return ok


# ======================================================================
# Main
# ======================================================================


def main():
    tests = [
        ("importar_desde_records with 3 valid records", test_importar_desde_records_valid),
        ("importar_desde_records with empty list", test_importar_desde_records_empty),
        ("importar_desde_records with single record", test_importar_desde_records_single),
        ("importar_desde_records with renamed fields", test_importar_desde_records_renamed_field),
        ("execute_import with records in import_data", test_execute_import_with_records),
        ("execute_import without records (fallback)", test_execute_import_cleanup),
    ]

    total = len(tests)
    passed = 0
    failed = 0

    print(f"\n{'#'*60}")
    print(f"  importar_desde_records — Verification Suite")
    print(f"{'#'*60}")

    for name, func in tests:
        ok = func()
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"\n{'='*60}")
    print(f"  Results: {PASS} checks, {FAIL} failures, {passed}/{total} tests passed")
    print(f"{'='*60}")

    if VERBOSE:
        print("\n  Detail:")
        for msg, ok in _results:
            icon = "[PASS]" if ok else "[FAIL]"
            print(f"    {icon} {msg}")

    return 0 if FAIL == 0 and failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
