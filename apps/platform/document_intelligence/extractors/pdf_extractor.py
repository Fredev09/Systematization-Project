"""
pdf_extractor.py — PDF document extractor.

Extracts text and images from PDF files.
Uses PyMuPDF (fitz) when available; falls back gracefully.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from apps.platform.document_intelligence.extractors.base import (
    DocumentExtractor,
    ExtractedDocument,
    ExtractedTable,
)
from apps.platform.ai.utils import extract_text_from_pdf, file_to_base64

logger = logging.getLogger(__name__)

MAX_PDF_PAGES = 100
MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MB


class PDFExtractor(DocumentExtractor):
    """Extracts content from PDF files."""

    def extract(self, file_path: str | Path) -> ExtractedDocument:
        path = Path(file_path)
        doc = ExtractedDocument(
            document_type="pdf",
            title=path.name,
        )

        # Extract text
        raw_text = extract_text_from_pdf(path, max_pages=MAX_PDF_PAGES)
        doc.raw_text = raw_text

        # Extract embedded images (for invoice analysis)
        try:
            import fitz
            pdf_doc = fitz.open(str(path))
            for page_num in range(min(len(pdf_doc), 5)):  # Max 5 pages
                page = pdf_doc[page_num]
                for img_index, img in enumerate(page.get_images(full=True)):
                    xref = img[0]
                    base_image = pdf_doc.extract_image(xref)
                    mime = base_image.get("ext", "png")
                    mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
                    mime_type = mime_map.get(mime, f"image/{mime}")
                    import base64
                    doc.images.append((mime_type, base64.b64encode(base_image["image"]).decode("utf-8")))
            pdf_doc.close()
        except ImportError:
            logger.debug("PyMuPDF not available for image extraction")
        except Exception as e:
            logger.warning("PDF image extraction error: %s", e)

        # Try to detect tables from text
        if raw_text.strip():
            lines = raw_text.split("\n")
            # Simple table detection: lines with consistent delimiter patterns
            table_lines = []
            for line in lines:
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 3:  # Pipe-separated table
                    table_lines.append(parts)
                elif line.count("  ") >= 3:  # Space-separated
                    parts = [p.strip() for p in line.split("  ") if p.strip()]
                    if len(parts) >= 3:
                        table_lines.append(parts)

            if table_lines:
                table = ExtractedTable(
                    name="Detected Table",
                    headers=table_lines[0] if table_lines else [],
                    rows=table_lines[1:] if len(table_lines) > 1 else [],
                    row_count=len(table_lines) - 1 if len(table_lines) > 1 else 0,
                    confidence=0.7,
                )
                doc.tables = [table]
                doc.columns = table.headers
                doc.rows = table.rows

        doc.confidence = 0.8 if doc.raw_text else 0.3
        doc.metadata["char_count"] = len(raw_text)
        doc.metadata["line_count"] = raw_text.count("\n") + 1

        return doc

    def validate(self, file_path: str | Path) -> None:
        super().validate(file_path)
        path = Path(file_path)
        size = path.stat().st_size
        if size > MAX_PDF_SIZE:
            raise ValueError(
                f"PDF file too large: {size / 1024 / 1024:.1f} MB "
                f"(max {MAX_PDF_SIZE / 1024 / 1024:.0f} MB)"
            )
        # Check if it's a valid PDF
        try:
            with open(path, "rb") as f:
                header = f.read(5)
            if header != b"%PDF-":
                raise ValueError("File is not a valid PDF")
        except Exception as e:
            if "File is not a valid PDF" in str(e):
                raise
            raise ValueError(f"Cannot validate PDF: {e}")

    @classmethod
    def supported_extensions(cls) -> list[str]:
        return [".pdf"]
