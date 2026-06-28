"""
csv_extractor.py — CSV document extractor.

Extracts headers, rows, and metadata from CSV files.
Handles different delimiters, encodings, and quoting.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any, Optional

from apps.platform.document_intelligence.extractors.base import (
    DocumentExtractor,
    ExtractedDocument,
    ExtractedTable,
)

logger = logging.getLogger(__name__)

MAX_CSV_ROWS = 100000
MAX_CSV_BYTES = 100 * 1024 * 1024  # 100 MB


class CSVExtractor(DocumentExtractor):
    """Extracts content from CSV files."""

    def extract(self, file_path: str | Path) -> ExtractedDocument:
        path = Path(file_path)
        doc = ExtractedDocument(
            document_type="csv",
            title=path.name,
        )

        # Detect encoding and delimiter
        encoding = self._detect_encoding(path)
        delimiter = self._detect_delimiter(path, encoding)

        doc.metadata["encoding"] = encoding
        doc.metadata["delimiter"] = delimiter

        try:
            with open(path, "r", encoding=encoding, errors="replace") as f:
                reader = csv.reader(f, delimiter=delimiter)
                rows: list[list[str]] = []
                for row_idx, row in enumerate(reader):
                    if row_idx > MAX_CSV_ROWS:
                        doc.warnings.append(f"CSV truncated at {MAX_CSV_ROWS} rows")
                        break
                    cleaned = [c.strip() for c in row]
                    rows.append(cleaned)
        except Exception as e:
            raise ValueError(f"Cannot read CSV file: {e}")

        if not rows:
            raise ValueError("CSV file is empty")

        # First non-empty row is headers
        headers = rows[0] if rows else []
        data_rows = rows[1:] if len(rows) > 1 else []

        # Filter out completely empty rows
        data_rows = [r for r in data_rows if any(c for c in r)]

        table = ExtractedTable(
            name="default",
            headers=headers,
            rows=data_rows,
            row_count=len(data_rows),
            confidence=1.0,
        )

        doc.tables = [table]
        doc.columns = headers
        doc.rows = data_rows
        doc.raw_text = "\n".join(
            " | ".join(row) for row in rows[:200]
        )
        doc.confidence = 1.0 if headers else 0.5
        doc.metadata["total_rows"] = len(data_rows)
        doc.metadata["total_columns"] = len(headers)
        doc.metadata["encoding"] = encoding

        return doc

    def validate(self, file_path: str | Path) -> None:
        super().validate(file_path)
        path = Path(file_path)
        size = path.stat().st_size
        if size > MAX_CSV_BYTES:
            raise ValueError(
                f"CSV file too large: {size / 1024 / 1024:.1f} MB "
                f"(max {MAX_CSV_BYTES / 1024 / 1024:.0f} MB)"
            )

    @staticmethod
    def _detect_encoding(path: Path) -> str:
        """Detect file encoding. Default to utf-8."""
        try:
            import chardet
            raw = path.read_bytes()[:10000]
            result = chardet.detect(raw)
            return result.get("encoding", "utf-8") or "utf-8"
        except ImportError:
            return "utf-8"

    @staticmethod
    def _detect_delimiter(path: Path, encoding: str) -> str:
        """Detect CSV delimiter by analyzing the first line."""
        try:
            with open(path, "r", encoding=encoding, errors="replace") as f:
                first_line = f.readline()[:2000]
        except Exception:
            return ","

        # Count potential delimiters
        delimiters = [",", ";", "\t", "|"]
        counts = {d: first_line.count(d) for d in delimiters}
        best = max(counts, key=counts.get)
        return best if counts[best] > 0 else ","

    @classmethod
    def supported_extensions(cls) -> list[str]:
        return [".csv"]
