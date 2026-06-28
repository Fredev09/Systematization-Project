"""
base.py — Abstract DocumentExtractor interface.

All extractors must implement extract() and return an ExtractedDocument.
This is the UNIVERSAL OUTPUT STRUCTURE for ALL document types.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ======================================================================
# Universal output structure — EVERY extractor returns this
# ======================================================================


@dataclass
class ExtractedTable:
    """A table detected inside a document."""
    name: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    row_count: int = 0
    confidence: float = 1.0


@dataclass
class ExtractedDocument:
    """
    Universal output structure for ALL document extractors.

    Every extractor (Excel, CSV, PDF, Image, Text) returns exactly this.
    No exceptions. No extra fields.

    Attributes:
        document_type: Detected document type (excel, csv, pdf, image, text, invoice, etc.)
        title: Document title or filename.
        sheets: List of sheet names (for Excel/workbooks) or ["default"].
        tables: List of detected tables.
        columns: List of column headers (primary table).
        rows: List of data rows (primary table, as list of strings).
        metadata: Dict with file info, row counts, etc.
        raw_text: Full extracted text content.
        images: List of (mime_type, base64_data) tuples for embedded images.
        confidence: Extraction confidence (0.0 to 1.0).
        warnings: List of warnings during extraction.
    """
    document_type: str = "unknown"
    title: str = ""
    sheets: list[str] = field(default_factory=lambda: ["default"])
    tables: list[ExtractedTable] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    images: list[tuple[str, str]] = field(default_factory=list)
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return len(self.rows)

    @property
    def total_columns(self) -> int:
        return len(self.columns)

    @property
    def is_empty(self) -> bool:
        return not self.rows and not self.raw_text

    def to_markdown_table(self, max_rows: int = 10) -> str:
        """Convert primary table to markdown for AI prompts."""
        lines: list[str] = []
        if self.columns:
            lines.append("| " + " | ".join(self.columns) + " |")
            lines.append("| " + " | ".join("---" for _ in self.columns) + " |")
            for row in self.rows[:max_rows]:
                padded = [
                    row[i] if i < len(row) else ""
                    for i in range(len(self.columns))
                ]
                lines.append("| " + " | ".join(padded) + " |")
        if len(self.rows) > max_rows:
            remaining = len(self.rows) - max_rows
            lines.append(f"| *... y {remaining} filas más* |")
        return "\n".join(lines)


# ======================================================================
# Base extractor
# ======================================================================


class DocumentExtractor(ABC):
    """
    Abstract base for document extractors.

    Subclasses MUST implement:
      - extract(file_path) -> ExtractedDocument

    Subclasses MAY override:
      - validate(file_path) -> None  (raise ValueError on invalid)
      - supported_extensions() -> list[str]
    """

    @abstractmethod
    def extract(self, file_path: str | Path) -> ExtractedDocument:
        """
        Extract content from a document file.

        Args:
            file_path: Path to the document file.

        Returns:
            ExtractedDocument with standardized structure.

        Raises:
            ValueError: If the file is invalid or cannot be extracted.
            UnsupportedDocumentType: If the file type is not supported.
        """
        ...

    def validate(self, file_path: str | Path) -> None:
        """
        Validate the file before extraction.
        Raises ValueError if validation fails.

        Default implementation checks file existence and size.
        """
        path = Path(file_path)
        if not path.exists():
            raise ValueError(f"File not found: {path}")
        if path.stat().st_size == 0:
            raise ValueError(f"File is empty: {path}")

    def extract_safe(self, file_path: str | Path) -> ExtractedDocument:
        """
        Safe extraction with validation and error handling.
        Never raises — returns ExtractedDocument with warnings on failure.
        """
        try:
            self.validate(file_path)
            return self.extract(file_path)
        except Exception as e:
            logger.error("Extraction failed for %s: %s", file_path, e, exc_info=True)
            return ExtractedDocument(
                title=Path(file_path).name,
                confidence=0.0,
                warnings=[f"Extraction failed: {e}"],
                metadata={"error": str(e), "file_path": str(file_path)},
            )

    @classmethod
    def supported_extensions(cls) -> list[str]:
        """Return list of supported file extensions for this extractor."""
        return []
