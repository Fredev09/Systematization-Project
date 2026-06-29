"""
test_edge_case_documents.py — Phase 6: Generate edge case test documents.

Produces real files in the .tmp_uploads/ directory for manual testing
of edge cases through the Document Intelligence UI.

Usage:
    python test_edge_case_documents.py

Files are created in .tmp_uploads/edge_test_*.xlsx/csv/pdf/png
"""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

import django
django.setup()

from pathlib import Path
from django.conf import settings

from apps.platform.document_intelligence.test_data_generators import (
    xlsx_bytes, csv_bytes, pdf_bytes, image_bytes,
    STD_HEADERS, STD_ROWS,
    EDGE_SPECIAL_CHARS_HEADERS, EDGE_SPECIAL_CHARS_ROWS,
    EDGE_TYPES_HEADERS, EDGE_TYPES_ROWS,
    EDGE_UTF8_HEADERS, EDGE_UTF8_ROWS,
)


def _write_file(dirpath, name, data):
    path = dirpath / name
    path.write_bytes(data)
    return path


def main():
    tmp_dir = Path(settings.BASE_DIR) / ".tmp_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating edge case documents in: {tmp_dir}")
    print()

    generators = [
        ("edge_test_standard.xlsx", xlsx_bytes(STD_HEADERS, STD_ROWS),
         "Standard 3-row dataset with 5 columns"),
        ("edge_test_standard.csv", csv_bytes(STD_HEADERS, STD_ROWS),
         "Standard CSV version"),
        ("edge_test_standard.pdf", pdf_bytes("Productos Test", STD_HEADERS, STD_ROWS),
         "Standard PDF with table"),
        ("edge_test_special_chars.xlsx",
         xlsx_bytes(EDGE_SPECIAL_CHARS_HEADERS, EDGE_SPECIAL_CHARS_ROWS),
         "Special characters: café, ümlaut, русский, 中文"),
        ("edge_test_special_chars.csv",
         csv_bytes(EDGE_SPECIAL_CHARS_HEADERS, EDGE_SPECIAL_CHARS_ROWS),
         "CSV with special characters"),
        ("edge_test_data_types.xlsx", xlsx_bytes(EDGE_TYPES_HEADERS, EDGE_TYPES_ROWS),
         "Data types: integers, decimals, currency, booleans, dates"),
        ("edge_test_data_types.csv", csv_bytes(EDGE_TYPES_HEADERS, EDGE_TYPES_ROWS),
         "CSV with data types"),
        ("edge_test_utf8.xlsx", xlsx_bytes(EDGE_UTF8_HEADERS, EDGE_UTF8_ROWS),
         "UTF-8 special symbols: €, ¥, ©, ®, ∆"),
        ("edge_test_utf8.csv", csv_bytes(EDGE_UTF8_HEADERS, EDGE_UTF8_ROWS),
         "CSV with UTF-8 symbols"),
        ("edge_test_empty_cols.xlsx",
         xlsx_bytes(["Name", "", "Price", "Qty"],
                     [["Prod A", "x", "10000", "5"]]),
         "Empty column header"),
        ("edge_test_dup_cols.xlsx",
         xlsx_bytes(["Name", "Price", "Price", "Qty"],
                     [["Prod A", "10000", "20000", "5"]]),
         "Duplicate column 'Price'"),
        ("edge_test_boolean_variants.xlsx",
         xlsx_bytes(["Name", "Active"],
                     [[f"Row {v}", v] for v in
                      ["Si", "No", "True", "False", "1", "0", "yes", "no", "on", "off"]]),
         "10 boolean variants"),
        ("edge_test_semicolon.csv",
         csv_bytes(STD_HEADERS, STD_ROWS, delimiter=";"),
         "Semicolon-delimited CSV"),
        ("edge_test_empty_rows.xlsx",
         xlsx_bytes(["Name", "Value"],
                     [["Row1", "OK"], ["", ""], ["Row3", "OK"], ["", "partial"], ["", ""]]),
         "Mix of empty and partial rows"),
        ("edge_test_large.xlsx",
         xlsx_bytes(STD_HEADERS,
                     [[f"Product {i}", str(10000 + i), str(i), "2026-01-01", "Si"]
                      for i in range(1000)]),
         "1000 rows for performance testing"),
        ("edge_test_image.png",
         image_bytes(["Product Name: Test Product",
                      "Price: $25,000",
                      "Stock: 100"], "PNG"),
         "Image with text (no OCR in offline mode)"),
    ]

    for name, data, desc in generators:
        path = _write_file(tmp_dir, name, data)
        size_kb = len(data) / 1024
        print(f"  {'✅' if path.exists() else '❌'} {name} ({size_kb:.1f} KB)")
        print(f"     {desc}")

    print(f"\nGenerated {len(generators)} files.")
    print(f"\nUpload these files from: {tmp_dir}")


if __name__ == "__main__":
    main()
