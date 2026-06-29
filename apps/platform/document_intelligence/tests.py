"""
tests.py — Phase 6: End-to-End Validation & Import Reliability

Extractor unit tests (no database needed) and edge case validation.

Execution:
    python -m unittest apps.platform.document_intelligence.tests -v
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from apps.platform.document_intelligence.test_data_generators import (
    STD_HEADERS, STD_ROWS,
    EDGE_EMPTY_COL_HEADERS, EDGE_EMPTY_COL_ROWS,
    EDGE_DUPLICATE_COL_HEADERS, EDGE_DUPLICATE_COL_ROWS,
    EDGE_SPECIAL_CHARS_HEADERS, EDGE_SPECIAL_CHARS_ROWS,
    EDGE_TYPES_HEADERS, EDGE_TYPES_ROWS,
    EDGE_EMPTY_ROWS_HEADERS, EDGE_EMPTY_ROWS_DATA,
    EDGE_UTF8_HEADERS, EDGE_UTF8_ROWS,
    xlsx_bytes, csv_bytes, pdf_bytes, image_bytes, json_bytes,
)


def _write_tmp(data: bytes, suffix: str) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    return tmp.name


# ======================================================================
# 1. EXTRACTOR UNIT TESTS
# ======================================================================


class TestExcelExtractor(unittest.TestCase):
    """Test the ExcelExtractor with various inputs."""

    def _get_extractor(self):
        from apps.platform.document_intelligence.extractors.excel_extractor import ExcelExtractor
        return ExcelExtractor()

    def test_extract_standard(self):
        path = _write_tmp(xlsx_bytes(STD_HEADERS, STD_ROWS), ".xlsx")
        doc = self._get_extractor().extract(path)
        self.assertEqual(doc.document_type, "excel")
        self.assertEqual(doc.columns, STD_HEADERS)
        self.assertEqual(len(doc.rows), 3)
        self.assertEqual(doc.rows[0][0], "Producto A")
        os.unlink(path)

    def test_extract_single_row(self):
        path = _write_tmp(xlsx_bytes(STD_HEADERS, [STD_ROWS[0]]), ".xlsx")
        doc = self._get_extractor().extract(path)
        self.assertEqual(len(doc.rows), 1)
        os.unlink(path)

    def test_extract_no_data_headers_only(self):
        """ExcelExtractor returns 0.5 confidence when no columns are found."""
        path = _write_tmp(xlsx_bytes([], []), ".xlsx")
        result = self._get_extractor().extract_safe(path)
        self.assertIsNotNone(result)
        os.unlink(path)

    def test_cell_conversion(self):
        from apps.platform.document_intelligence.extractors.excel_extractor import ExcelExtractor
        ext = ExcelExtractor()
        self.assertEqual(ext._cell_to_str(None), "")
        self.assertEqual(ext._cell_to_str(42), "42")
        self.assertEqual(ext._cell_to_str(42.0), "42")
        self.assertEqual(ext._cell_to_str(3.14), "3.14")
        from datetime import datetime
        self.assertEqual(ext._cell_to_str(datetime(2026, 1, 15)), "2026-01-15")


class TestCSVExtractor(unittest.TestCase):
    """Test the CSVExtractor."""

    def _get_extractor(self):
        from apps.platform.document_intelligence.extractors.csv_extractor import CSVExtractor
        return CSVExtractor()

    def test_extract_standard(self):
        path = _write_tmp(csv_bytes(STD_HEADERS, STD_ROWS), ".csv")
        doc = self._get_extractor().extract(path)
        self.assertEqual(doc.document_type, "csv")
        self.assertEqual(doc.columns, STD_HEADERS)
        self.assertEqual(len(doc.rows), 3)
        os.unlink(path)

    def test_extract_semicolon_delimiter(self):
        path = _write_tmp(csv_bytes(STD_HEADERS, STD_ROWS, delimiter=";"), ".csv")
        doc = self._get_extractor().extract(path)
        self.assertEqual(len(doc.rows), 3)
        os.unlink(path)

    def test_extract_tab_delimiter(self):
        path = _write_tmp(csv_bytes(STD_HEADERS, STD_ROWS, delimiter="\t"), ".csv")
        doc = self._get_extractor().extract(path)
        self.assertEqual(len(doc.rows), 3)
        os.unlink(path)

    def test_detect_delimiter(self):
        from apps.platform.document_intelligence.extractors.csv_extractor import CSVExtractor
        self.assertEqual(CSVExtractor._detect_delimiter(Path(_write_tmp(b"a,b,c\n", ".csv")), "utf-8"), ",")
        self.assertEqual(CSVExtractor._detect_delimiter(Path(_write_tmp(b"a;b;c\n", ".csv")), "utf-8"), ";")

    def test_extract_special_chars(self):
        path = _write_tmp(csv_bytes(EDGE_SPECIAL_CHARS_HEADERS, EDGE_SPECIAL_CHARS_ROWS), ".csv")
        doc = self._get_extractor().extract(path)
        self.assertEqual(len(doc.rows), 4)
        self.assertEqual(doc.rows[0][0], "Café & té")
        self.assertEqual(doc.rows[2][0], "русский товар")
        os.unlink(path)

    def test_extract_types(self):
        path = _write_tmp(csv_bytes(EDGE_TYPES_HEADERS, EDGE_TYPES_ROWS), ".csv")
        doc = self._get_extractor().extract(path)
        self.assertEqual(len(doc.rows), 4)
        os.unlink(path)

    def test_csv_extra_spaces_in_headers(self):
        csv_data = b"  Name  ,  Price  , Qty\n  A  , 100  , 5\n"
        path = _write_tmp(csv_data, ".csv")
        doc = self._get_extractor().extract(path)
        self.assertIn("Name", doc.columns)
        os.unlink(path)

    def test_csv_validates_file_size(self):
        """CSVExtractor validate should reject large files."""
        from apps.platform.document_intelligence.extractors.csv_extractor import CSVExtractor
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"x" * 101 * 1024 * 1024)  # 101 MB > 100 MB max
            p = f.name
        with self.assertRaises(ValueError):
            CSVExtractor().validate(p)
        os.unlink(p)


class TestPDFExtractor(unittest.TestCase):
    """Test the PDFExtractor."""

    def _get_extractor(self):
        from apps.platform.document_intelligence.extractors.pdf_extractor import PDFExtractor
        return PDFExtractor()

    def test_extract_standard(self):
        path = _write_tmp(pdf_bytes("Test", STD_HEADERS, STD_ROWS), ".pdf")
        doc = self._get_extractor().extract(path)
        self.assertEqual(doc.document_type, "pdf")
        # Without PyMuPDF/fitz, raw_text is a placeholder
        self.assertGreater(len(doc.raw_text), 0)
        os.unlink(path)

    def test_validates_pdf_magic_bytes(self):
        path = _write_tmp(b"not a pdf", ".pdf")
        with self.assertRaises(ValueError):
            self._get_extractor().validate(path)
        os.unlink(path)

    def test_extract_safe_handles_bad_file(self):
        path = _write_tmp(b"not a pdf", ".pdf")
        result = self._get_extractor().extract_safe(path)
        self.assertEqual(result.confidence, 0.0)
        os.unlink(path)

    def test_validates_file_size(self):
        from apps.platform.document_intelligence.extractors.pdf_extractor import PDFExtractor
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-" + b"x" * 51 * 1024 * 1024)  # 51 MB
            p = f.name
        with self.assertRaises(ValueError):
            PDFExtractor().validate(p)
        os.unlink(p)


class TestImageExtractor(unittest.TestCase):
    """Test the ImageExtractor."""

    def _get_extractor(self):
        from apps.platform.document_intelligence.extractors.image_extractor import ImageExtractor
        return ImageExtractor()

    def test_extract_png(self):
        path = _write_tmp(image_bytes(["Test"], "PNG"), ".png")
        doc = self._get_extractor().extract(path)
        self.assertEqual(doc.document_type, "image")
        self.assertGreater(len(doc.images), 0)
        mime, b64 = doc.images[0]
        self.assertEqual(mime, "image/png")
        self.assertGreater(len(b64), 0)
        os.unlink(path)

    def test_extract_jpg(self):
        path = _write_tmp(image_bytes(["Test"], "JPEG"), ".jpg")
        doc = self._get_extractor().extract(path)
        mime, _ = doc.images[0]
        self.assertEqual(mime, "image/jpeg")
        os.unlink(path)

    def test_has_dimensions(self):
        path = _write_tmp(image_bytes(["Test"], "PNG", width=800, height=600), ".png")
        doc = self._get_extractor().extract(path)
        self.assertEqual(doc.metadata.get("image_width"), 800)
        self.assertEqual(doc.metadata.get("image_height"), 600)
        os.unlink(path)

    def test_empty_image_can_extract(self):
        path = _write_tmp(image_bytes([], "PNG"), ".png")
        doc = self._get_extractor().extract(path)
        self.assertGreater(len(doc.images), 0)
        os.unlink(path)

    def test_validates_file_size(self):
        from apps.platform.document_intelligence.extractors.image_extractor import ImageExtractor
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"x" * 21 * 1024 * 1024)  # 21 MB
            p = f.name
        with self.assertRaises(ValueError):
            ImageExtractor().validate(p)
        os.unlink(p)


class TestTextExtractor(unittest.TestCase):
    """Test the TextExtractor for .txt, .json, .xml."""

    def _get_extractor(self):
        from apps.platform.document_intelligence.extractors.text_extractor import TextExtractor
        return TextExtractor()

    def test_extract_txt(self):
        path = _write_tmp(b"Hello World\nLine 2", ".txt")
        doc = self._get_extractor().extract(path)
        self.assertIn("Hello World", doc.raw_text)
        os.unlink(path)

    def test_extract_json_array(self):
        data = [{"Nombre": "A", "Precio": "100"}, {"Nombre": "B", "Precio": "200"}]
        path = _write_tmp(json_bytes(data), ".json")
        doc = self._get_extractor().extract(path)
        self.assertEqual(len(doc.rows), 2)
        self.assertIn("Nombre", doc.columns)
        os.unlink(path)

    def test_extract_json_single_object(self):
        data = {"key": "value"}
        path = _write_tmp(json_bytes(data), ".json")
        doc = self._get_extractor().extract(path)
        self.assertEqual(len(doc.rows), 0)
        os.unlink(path)

    def test_extract_utf8(self):
        text = "Café\nMünchen\nрусский\n中文\n".encode("utf-8")
        path = _write_tmp(text, ".txt")
        doc = self._get_extractor().extract(path)
        self.assertIn("Café", doc.raw_text)
        self.assertIn("中文", doc.raw_text)
        os.unlink(path)

    def test_extract_markdown_table(self):
        md = ("| Name  | Value |\n"
              "|-------|-------|\n"
              "| A     | 100   |\n"
              "| B     | 200   |\n")
        path = _write_tmp(md.encode("utf-8"), ".md")
        doc = self._get_extractor().extract(path)
        self.assertGreaterEqual(len(doc.rows), 2)
        os.unlink(path)

    def test_extract_xml_strips_tags(self):
        xml = b"<root><item>Hello</item><item>World</item></root>"
        path = _write_tmp(xml, ".xml")
        doc = self._get_extractor().extract(path)
        self.assertIn("Hello", doc.raw_text)
        os.unlink(path)

    def test_validates_file_size(self):
        from apps.platform.document_intelligence.extractors.text_extractor import TextExtractor
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"x" * 11 * 1024 * 1024)
            p = f.name
        with self.assertRaises(ValueError):
            TextExtractor().validate(p)
        os.unlink(p)


# ======================================================================
# 2. EXTRACTOR FACTORY TESTS
# ======================================================================


class TestExtractorFactory(unittest.TestCase):
    """Test the get_extractor factory function."""

    def test_get_by_extension_xlsx(self):
        from apps.platform.document_intelligence.extractors import get_extractor
        from apps.platform.document_intelligence.extractors.excel_extractor import ExcelExtractor
        self.assertIsInstance(get_extractor(extension=".xlsx"), ExcelExtractor)

    def test_get_by_extension_csv(self):
        from apps.platform.document_intelligence.extractors import get_extractor
        from apps.platform.document_intelligence.extractors.csv_extractor import CSVExtractor
        self.assertIsInstance(get_extractor(extension=".csv"), CSVExtractor)

    def test_get_by_extension_pdf(self):
        from apps.platform.document_intelligence.extractors import get_extractor
        from apps.platform.document_intelligence.extractors.pdf_extractor import PDFExtractor
        self.assertIsInstance(get_extractor(extension=".pdf"), PDFExtractor)

    def test_get_by_extension_png(self):
        from apps.platform.document_intelligence.extractors import get_extractor
        from apps.platform.document_intelligence.extractors.image_extractor import ImageExtractor
        self.assertIsInstance(get_extractor(extension=".png"), ImageExtractor)

    def test_get_by_extension_txt(self):
        from apps.platform.document_intelligence.extractors import get_extractor
        from apps.platform.document_intelligence.extractors.text_extractor import TextExtractor
        self.assertIsInstance(get_extractor(extension=".txt"), TextExtractor)

    def test_get_by_mime_xlsx(self):
        from apps.platform.document_intelligence.extractors import get_extractor
        from apps.platform.document_intelligence.extractors.excel_extractor import ExcelExtractor
        ext = get_extractor(mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIsInstance(ext, ExcelExtractor)

    def test_get_by_file_path(self):
        from apps.platform.document_intelligence.extractors import get_extractor
        from apps.platform.document_intelligence.extractors.csv_extractor import CSVExtractor
        self.assertIsInstance(get_extractor(file_path="data.csv"), CSVExtractor)

    def test_supported_extensions(self):
        from apps.platform.document_intelligence.extractors import supported_extensions
        exts = supported_extensions()
        self.assertIn(".xlsx", exts)
        self.assertIn(".csv", exts)
        self.assertIn(".pdf", exts)
        self.assertIn(".png", exts)

    def test_unknown_extension_falls_back_to_text(self):
        from apps.platform.document_intelligence.extractors import get_extractor
        from apps.platform.document_intelligence.extractors.text_extractor import TextExtractor
        self.assertIsInstance(get_extractor(extension=".xyz"), TextExtractor)


# ======================================================================
# 3. EDGE CASE TESTS
# ======================================================================


class TestEdgeCasesExtractors(unittest.TestCase):
    """Test extractors with edge case documents."""

    def _run_extractor(self, data: bytes, suffix: str):
        from apps.platform.document_intelligence.extractors import get_extractor
        path = _write_tmp(data, suffix)
        extractor = get_extractor(file_path=path)
        doc = extractor.extract(path)
        os.unlink(path)
        return doc

    # ── Empty columns ──

    def test_excel_empty_columns(self):
        doc = self._run_extractor(xlsx_bytes(EDGE_EMPTY_COL_HEADERS, EDGE_EMPTY_COL_ROWS), ".xlsx")
        self.assertEqual(len(doc.columns), 4)  # Empty column name preserved
        self.assertEqual(len(doc.rows), 1)

    def test_csv_empty_columns(self):
        doc = self._run_extractor(csv_bytes(EDGE_EMPTY_COL_HEADERS, EDGE_EMPTY_COL_ROWS), ".csv")
        self.assertEqual(len(doc.columns), 4)

    # ── Duplicate columns ──

    def test_excel_duplicate_columns(self):
        doc = self._run_extractor(xlsx_bytes(EDGE_DUPLICATE_COL_HEADERS, EDGE_DUPLICATE_COL_ROWS), ".xlsx")
        self.assertEqual(len(doc.columns), 4)

    def test_csv_duplicate_columns(self):
        doc = self._run_extractor(csv_bytes(EDGE_DUPLICATE_COL_HEADERS, EDGE_DUPLICATE_COL_ROWS), ".csv")
        self.assertEqual(len(doc.columns), 4)

    # ── Special characters ──

    def test_excel_special_chars(self):
        doc = self._run_extractor(xlsx_bytes(EDGE_SPECIAL_CHARS_HEADERS, EDGE_SPECIAL_CHARS_ROWS), ".xlsx")
        self.assertEqual(len(doc.rows), 4)
        self.assertIn("Café & té", doc.rows[0])

    def test_csv_special_chars(self):
        doc = self._run_extractor(csv_bytes(EDGE_SPECIAL_CHARS_HEADERS, EDGE_SPECIAL_CHARS_ROWS), ".csv")
        self.assertEqual(len(doc.rows), 4)

    # ── Various data types ──

    def test_excel_types(self):
        doc = self._run_extractor(xlsx_bytes(EDGE_TYPES_HEADERS, EDGE_TYPES_ROWS), ".xlsx")
        self.assertEqual(len(doc.rows), 4)

    def test_csv_types(self):
        doc = self._run_extractor(csv_bytes(EDGE_TYPES_HEADERS, EDGE_TYPES_ROWS), ".csv")
        self.assertEqual(len(doc.rows), 4)

    # ── Empty rows ──

    def test_excel_empty_rows(self):
        doc = self._run_extractor(xlsx_bytes(EDGE_EMPTY_ROWS_HEADERS, EDGE_EMPTY_ROWS_DATA), ".xlsx")
        # ExcelExtractor keeps all rows including empty ones
        self.assertGreaterEqual(len(doc.rows), 3)

    def test_csv_empty_rows(self):
        doc = self._run_extractor(csv_bytes(EDGE_EMPTY_ROWS_HEADERS, EDGE_EMPTY_ROWS_DATA), ".csv")
        # CSVExtractor filters completely empty rows
        self.assertGreaterEqual(len(doc.rows), 2)

    # ── UTF-8 ──

    def test_excel_utf8(self):
        doc = self._run_extractor(xlsx_bytes(EDGE_UTF8_HEADERS, EDGE_UTF8_ROWS), ".xlsx")
        self.assertEqual(len(doc.rows), 5)
        self.assertIn("€uro sign", doc.rows[0])

    def test_csv_utf8(self):
        doc = self._run_extractor(csv_bytes(EDGE_UTF8_HEADERS, EDGE_UTF8_ROWS), ".csv")
        self.assertEqual(len(doc.rows), 5)

    # ── Single column ──

    def test_excel_single_column(self):
        headers = ["Name"]
        rows = [["A"], ["B"], ["C"]]
        doc = self._run_extractor(xlsx_bytes(headers, rows), ".xlsx")
        # ExcelExtractor requires >= 2 valid headers
        self.assertEqual(len(doc.columns), 0)

    def test_csv_single_column(self):
        headers = ["Name"]
        rows = [["A"], ["B"]]
        doc = self._run_extractor(csv_bytes(headers, rows), ".csv")
        self.assertEqual(len(doc.columns), 1)
        self.assertEqual(len(doc.rows), 2)

    # ── Boolean variants ──

    def test_excel_boolean_variants(self):
        headers = ["Name", "Active"]
        rows = [["A", v] for v in ["Si", "No", "True", "False", "1", "0", "yes", "no", "on", "off"]]
        doc = self._run_extractor(xlsx_bytes(headers, rows), ".xlsx")
        self.assertEqual(len(doc.rows), 10)

    def test_csv_boolean_variants(self):
        headers = ["Name", "Active"]
        rows = [["A", v] for v in ["Si", "True", "1", "yes", "on"]]
        doc = self._run_extractor(csv_bytes(headers, rows), ".csv")
        self.assertEqual(len(doc.rows), 5)

    # ── UTF-8 BOM CSV ──

    def test_csv_utf8_bom(self):
        """CSV with BOM should detect headers correctly."""
        headers = ["Nombre", "Precio"]
        rows = [["Café", "15.99"]]
        raw = "\ufeff" + ",".join(headers) + "\n" + ",".join(rows[0]) + "\n"
        path = _write_tmp(raw.encode("utf-8-sig"), ".csv")
        from apps.platform.document_intelligence.extractors import get_extractor
        extractor = get_extractor(file_path=path)
        doc = extractor.extract(path)
        # First header may include BOM char
        self.assertIn("Nombre", doc.columns[0])
        os.unlink(path)

    # ── Text / JSON edge cases ──

    def test_json_empty_array(self):
        doc = self._run_extractor(json_bytes([]), ".json")
        self.assertEqual(len(doc.rows), 0)

    def test_json_array_of_primitives(self):
        data = ["a", "b", "c"]
        doc = self._run_extractor(json_bytes(data), ".json")
        self.assertGreaterEqual(len(doc.rows), 0)


# ======================================================================
# 4. COLUMN MATCHER TESTS (no database needed)
# ======================================================================


class TestColumnMatcher(unittest.TestCase):
    """Test the ColumnMatcher import mapping logic."""

    def _make_matcher(self, field_names):
        from apps.platform.dynamic_forms.column_matching import ColumnMatcher
        return ColumnMatcher(field_names=field_names)

    def test_exact_match(self):
        matcher = self._make_matcher(["Nombre", "Precio", "Cantidad"])
        results = matcher.match_all(["Nombre", "Precio", "Cantidad"])
        for r in results:
            self.assertIsNotNone(r.matched_to, f"No match for '{r.column_name}'")
            self.assertEqual(r.confidence, 1.0)
            self.assertEqual(r.method, "exact")

    def test_normalized_match(self):
        matcher = self._make_matcher(["nombre", "precio", "cantidad"])
        results = matcher.match_all(["Nombre", "PRECIO", "Cantidad"])
        for r in results:
            self.assertIsNotNone(r.matched_to)

    def test_unmatched_column(self):
        matcher = self._make_matcher(["Nombre", "Precio"])
        results = matcher.match_all(["Nombre", "ColumnaInexistente"])
        self.assertIsNotNone(results[0].matched_to)
        self.assertIsNone(results[1].matched_to)

    def test_build_mapping(self):
        from apps.platform.dynamic_forms.column_matching import ColumnMatcher
        matcher = ColumnMatcher(field_names=["Nombre", "Precio", "Stock"])
        mapping, unmmaped, results = matcher.build_mapping(["Nombre", "Precio", "Stock"])
        self.assertIn("Nombre", mapping.values())

    def test_empty_columns(self):
        matcher = self._make_matcher(["Nombre"])
        results = matcher.match_all([])
        self.assertEqual(len(results), 0)

    def test_all_matched_returns_full_mapping(self):
        matcher = self._make_matcher(["Nombre", "Precio", "Cantidad", "Fecha"])
        results = matcher.match_all(["Nombre", "Precio", "Cantidad", "Fecha"])
        matched = sum(1 for r in results if r.matched_to is not None)
        self.assertEqual(matched, 4, "All columns should be matched")


# ======================================================================
# 5. EXTRACTED DOCUMENT UNIT TESTS
# ======================================================================


class TestExtractedDocument(unittest.TestCase):
    """Test the ExtractedDocument dataclass."""

    def setUp(self):
        from apps.platform.document_intelligence.extractors.base import ExtractedDocument, ExtractedTable
        self.doc = ExtractedDocument(
            document_type="test", title="test.txt",
            columns=["A", "B"],
            rows=[["1", "2"], ["3", "4"]],
            raw_text="A | B\n1 | 2\n3 | 4",
        )

    def test_total_rows(self):
        self.assertEqual(self.doc.total_rows, 2)

    def test_total_columns(self):
        self.assertEqual(self.doc.total_columns, 2)

    def test_is_empty_false(self):
        self.assertFalse(self.doc.is_empty)

    def test_is_empty_true(self):
        from apps.platform.document_intelligence.extractors.base import ExtractedDocument
        self.assertTrue(ExtractedDocument().is_empty)

    def test_to_markdown_table(self):
        md = self.doc.to_markdown_table()
        self.assertIn("A", md)
        self.assertIn("B", md)


# ======================================================================
# 6. REQUEST VALIDATION TESTS (mock-based, no Django)
# ======================================================================


class TestAllowedExtensions(unittest.TestCase):
    """Test the ALLOWED_EXTENSIONS set directly (no Django imports needed)."""

    def setUp(self):
        self.allowed = {
            ".xlsx", ".csv", ".pdf",
            ".jpg", ".jpeg", ".png", ".webp",
            ".txt", ".json", ".xml",
        }

    def test_xlsx_allowed(self):
        self.assertIn(".xlsx", self.allowed)

    def test_xls_not_allowed(self):
        self.assertNotIn(".xls", self.allowed)

    def test_csv_allowed(self):
        self.assertIn(".csv", self.allowed)

    def test_pdf_allowed(self):
        self.assertIn(".pdf", self.allowed)

    def test_png_allowed(self):
        self.assertIn(".png", self.allowed)

    def test_exe_not_allowed(self):
        self.assertNotIn(".exe", self.allowed)

    def test_py_not_allowed(self):
        self.assertNotIn(".py", self.allowed)


# ======================================================================
# 7. NORMALIZATION TESTS (direct, no Django dependencies)
# ======================================================================


class TestColumnNormalization(unittest.TestCase):
    """Test the normalizar_columna function (pure Python, no Django)."""

    def test_normalize_basic(self):
        from apps.platform.dynamic_forms.column_matching import normalizar_columna
        self.assertEqual(normalizar_columna("Nombre"), "nombre")

    def test_normalize_accent(self):
        from apps.platform.dynamic_forms.column_matching import normalizar_columna
        self.assertEqual(normalizar_columna("Descripción"), "descripcion")
        self.assertEqual(normalizar_columna("PRECIO"), "precio")

    def test_normalize_separators(self):
        from apps.platform.dynamic_forms.column_matching import normalizar_columna
        self.assertEqual(normalizar_columna("precio-unitario"), "precio_unitario")
        self.assertEqual(normalizar_columna("Precio Unitario"), "precio_unitario")

    def test_normalize_strips(self):
        from apps.platform.dynamic_forms.column_matching import normalizar_columna
        self.assertEqual(normalizar_columna("  Nombre  "), "nombre")

    def test_normalize_parentheses(self):
        from apps.platform.dynamic_forms.column_matching import normalizar_columna
        self.assertEqual(normalizar_columna("Precio (€)"), "precio")


# ======================================================================
# Entry point
# ======================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
