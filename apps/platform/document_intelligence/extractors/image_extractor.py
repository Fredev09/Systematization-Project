"""
image_extractor.py — Image document extractor.

Extracts image data as base64 for AI analysis.
Does NOT perform OCR — that's delegated to the AI provider.
"""

from __future__ import annotations

import logging
from pathlib import Path

from apps.platform.document_intelligence.extractors.base import (
    DocumentExtractor,
    ExtractedDocument,
)
from apps.platform.ai.utils import file_to_base64

logger = logging.getLogger(__name__)

MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB


class ImageExtractor(DocumentExtractor):
    """Extracts image data for AI analysis."""

    def extract(self, file_path: str | Path) -> ExtractedDocument:
        path = Path(file_path)
        mime, b64 = file_to_base64(path)

        doc = ExtractedDocument(
            document_type="image",
            title=path.name,
            raw_text=f"[Image: {path.name} ({mime}, {len(b64)} bytes base64)]",
            images=[(mime, b64)],
            confidence=1.0,
        )
        doc.metadata["mime_type"] = mime
        doc.metadata["image_width"] = ""
        doc.metadata["image_height"] = ""

        # Try to get image dimensions
        try:
            from PIL import Image
            img = Image.open(path)
            doc.metadata["image_width"] = img.width
            doc.metadata["image_height"] = img.height
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Could not get image dimensions: %s", e)

        return doc

    def validate(self, file_path: str | Path) -> None:
        super().validate(file_path)
        path = Path(file_path)
        size = path.stat().st_size
        if size > MAX_IMAGE_SIZE:
            raise ValueError(
                f"Image too large: {size / 1024 / 1024:.1f} MB "
                f"(max {MAX_IMAGE_SIZE / 1024 / 1024:.0f} MB)"
            )

    @classmethod
    def supported_extensions(cls) -> list[str]:
        return [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"]
