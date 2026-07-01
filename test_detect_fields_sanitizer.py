"""
test_detect_fields_sanitizer.py — Verify that AI field type sanitizer
prevents 'relacion' from reaching the database.

This test ensures that the architectural decision "AI never creates
relaciones" is enforced at the code level.

Usage:
    python test_detect_fields_sanitizer.py [--verbose]

Returns exit code 0 if ALL tests pass, 1 if any fail.
"""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

import django
django.setup()

from apps.platform.document_intelligence.views import _sanitize_ai_field_type

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


# ======================================================================
# TEST 1: Sanitizer converts 'relacion' to 'codigo'
# ======================================================================


def test_sanitizer_converts_relacion():
    section("1. _sanitize_ai_field_type converts 'relacion' to 'codigo'")
    ok = True

    result = _sanitize_ai_field_type('relacion')
    expected = 'codigo'
    log(f"_sanitize_ai_field_type('relacion') = '{result}' (expected '{expected}')",
        result == expected)
    if result != expected:
        ok = False

    return ok


# ======================================================================
# TEST 2: Sanitizer keeps other types unchanged
# ======================================================================


def test_sanitizer_keeps_other_types():
    section("2. _sanitize_ai_field_type keeps other types unchanged")
    ok = True

    test_cases = [
        ('texto', 'texto'),
        ('codigo', 'codigo'),
        ('numero', 'numero'),
        ('moneda', 'moneda'),
        ('fecha', 'fecha'),
        ('booleano', 'booleano'),
        ('lista', 'lista'),
        ('email', 'email'),
        ('url', 'url'),
        ('telefono', 'telefono'),
        ('textarea', 'textarea'),
        ('imagen', 'imagen'),
        ('archivo', 'archivo'),
        ('calculado', 'calculado'),
        ('', ''),
        (None, None),
    ]

    for input_type, expected in test_cases:
        result = _sanitize_ai_field_type(input_type)
        log(f"'{input_type}' -> '{result}' (expected '{expected}')",
            result == expected)
        if result != expected:
            ok = False

    return ok


# ======================================================================
# TEST 3: Verify that prompt no longer lists 'relacion' as allowed type
# ======================================================================


def test_prompt_excludes_relacion():
    section("3. detect_fields.md prompt excludes 'relacion' from allowed types")
    ok = True

    from pathlib import Path
    prompt_path = Path("apps/platform/ai/prompts/detect_fields.md")
    if not prompt_path.exists():
        log("Prompt file not found", False)
        return False

    content = prompt_path.read_text(encoding="utf-8")

    # The types list must NOT include 'relacion'
    import re
    for match in re.finditer(r'\([^)]*texto[^)]*\)', content):
        types_list = match.group()
        if 'relacion' in types_list:
            log(f"'relacion' found in types list: {types_list}", False)
            ok = False
        else:
            log(f"Types list has no 'relacion': {types_list}", True)

    # The prompt must have a rule about NUNCA using relacion (may appear as explanatory text)
    if "NUNCA" in content and "relacion" in content.lower():
        log("NUNCA relacion rule found in prompt", True)
    else:
        log("NUNCA relacion rule NOT found in prompt", False)
        ok = False

    return ok


# ======================================================================
# Test runner
# ======================================================================


def main():
    tests = [
        ("Sanitizer converts 'relacion' to 'codigo'", test_sanitizer_converts_relacion),
        ("Sanitizer keeps other types unchanged", test_sanitizer_keeps_other_types),
        ("Prompt excludes 'relacion' from allowed types", test_prompt_excludes_relacion),
    ]

    total = len(tests)
    passed = 0
    failed = 0

    print(f"\n{'#'*60}")
    print(f"  AI Field Type Sanitizer — Verification Suite")
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
