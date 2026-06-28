"""
extractors — Document extractor implementations.

Factory function get_extractor() returns the appropriate extractor
based on file extension or MIME type.

Every extractor returns the same ExtractedDocument structure.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from apps.platform.document_intelligence.extractors.base import (
    DocumentExtractor,
    ExtractedDocument,
)
from apps.platform.document_intelligence.extractors.excel_extractor import (
    ExcelExtractor,
)
from apps.platform.document_intelligence.extractors.csv_extractor import (
    CSVExtractor,
)
from apps.platform.document_intelligence.extractors.pdf_extractor import (
    PDFExtractor,
)
from apps.platform.document_intelligence.extractors.image_extractor import (
    ImageExtractor,
)
from apps.platform.document_intelligence.extractors.text_extractor import (
    TextExtractor,
)

logger = logging.getLogger(__name__)

# Extension → Extractor mapping
_EXTENSION_REGISTRY: dict[str, type[DocumentExtractor]] = {
    ".xlsx": ExcelExtractor,
    ".xls": ExcelExtractor,
    ".csv": CSVExtractor,
    ".pdf": PDFExtractor,
    ".jpg": ImageExtractor,
    ".jpeg": ImageExtractor,
    ".png": ImageExtractor,
    ".webp": ImageExtractor,
    ".gif": ImageExtractor,
    ".bmp": ImageExtractor,
    ".tiff": ImageExtractor,
    ".txt": TextExtractor,
    ".md": TextExtractor,
    ".json": TextExtractor,
    ".xml": TextExtractor,
}

# MIME → Extension mapping (for uploads that provide MIME type)
_MIME_REGISTRY: dict[str, str] = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "text/csv": ".csv",
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "text/plain": ".txt",
    "application/json": ".json",
    "text/xml": ".xml",
    "application/xml": ".xml",
}


def get_extractor(
    file_path: Optional[str | Path] = None,
    mime_type: Optional[str] = None,
    extension: Optional[str] = None,
) -> DocumentExtractor:
    """
    Factory: returns the appropriate extractor for a given file.

    Resolution order:
      1. Explicit `extension` parameter
      2. From `file_path` suffix
      3. From `mime_type` → extension lookup
      4. Default: TextExtractor

    Args:
        file_path: Optional file path (used to determine extension).
        mime_type: Optional MIME type.
        extension: Explicit extension override (e.g., ".pdf").

    Returns:
        DocumentExtractor instance.

    Raises:
        ValueError: If no extractor is found for the given type.
    """
    ext = None

    if extension:
        ext = extension.lower()
    elif file_path:
        ext = Path(file_path).suffix.lower()
    elif mime_type:
        ext = _MIME_REGISTRY.get(mime_type.lower())

    if ext and ext in _EXTENSION_REGISTRY:
        extractor_class = _EXTENSION_REGISTRY[ext]
        logger.debug("Extractor: %s → %s", ext, extractor_class.__name__)
        return extractor_class()

    # Default fallback for unknown types
    logger.warning(
        "No extractor found for extension='%s', mime='%s'. Using TextExtractor fallback.",
        ext, mime_type,
    )
    return TextExtractor()


def register_extractor(extension: str, extractor_class: type[DocumentExtractor]) -> None:
    """Register a custom extractor for an extension (plugin system)."""
    ext = extension.lower().strip()
    if not ext.startswith("."):
        ext = f".{ext}"
    _EXTENSION_REGISTRY[ext] = extractor_class
    logger.info("Extractor registered: %s → %s", ext, extractor_class.__name__)


def supported_extensions() -> list[str]:
    """Return list of supported file extensions."""
    return sorted(_EXTENSION_REGISTRY.keys())


__all__ = [
    "DocumentExtractor",
    "ExtractedDocument",
    "get_extractor",
    "register_extractor",
    "supported_extensions",
]
