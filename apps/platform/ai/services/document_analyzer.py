"""
document_analyzer.py — Universal document analysis service.

Accepts any document type (Excel, CSV, PDF, image, text) and returns
a normalized DocumentAnalysis structure.

Pipeline:
  1. Detect document type (from file extension / MIME / content)
  2. Extract text content (using utils.py extractors)
  3. Call AI provider for structured analysis
  4. Parse and validate the response
  5. Return DocumentAnalysis with confidence score

Supports caching via the provider's built-in cache.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional, Union

from apps.platform.ai.exceptions import (
    AnalysisError,
    UnsupportedDocumentType,
)
from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.ai.services.prompt_manager import get_prompt_manager
from apps.platform.ai.types import (
    AIResponse,
    DetectedField,
    DetectedTable,
    DocumentAnalysis,
    DocumentType,
)
from apps.platform.ai.utils import (
    compute_file_hash,
    extract_text_from_csv,
    extract_text_from_excel,
    extract_text_from_pdf,
    file_to_base64,
    safe_json_parse,
    truncate_text,
)

logger = logging.getLogger(__name__)

# Max file size for text extraction (50 MB)
MAX_FILE_SIZE = 50 * 1024 * 1024

# Supported extensions mapped to document types
EXTENSION_MAP: dict[str, DocumentType] = {
    ".xlsx": DocumentType.EXCEL,
    ".xls": DocumentType.EXCEL,
    ".csv": DocumentType.CSV,
    ".pdf": DocumentType.PDF,
    ".jpg": DocumentType.IMAGE,
    ".jpeg": DocumentType.IMAGE,
    ".png": DocumentType.IMAGE,
    ".webp": DocumentType.IMAGE,
    ".gif": DocumentType.IMAGE,
    ".txt": DocumentType.TEXT,
    ".md": DocumentType.TEXT,
    ".json": DocumentType.TEXT,
}


class DocumentAnalyzer:
    """
    Analyzes documents of any supported type.

    Usage:
        analyzer = DocumentAnalyzer(provider=gemini_provider)
        result = analyzer.analyze("factura.xlsx")
        print(result.fields, result.confidence)
    """

    def __init__(
        self,
        provider: BaseAIProvider,
        prompt_manager: Optional[Any] = None,
    ):
        self.provider = provider
        self.pm = prompt_manager or get_prompt_manager()

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    def analyze(
        self,
        file_path: Union[str, Path],
        document_type: Optional[DocumentType] = None,
        use_cache: bool = True,
    ) -> DocumentAnalysis:
        """
        Analyze a document file.

        Args:
            file_path: Path to the file.
            document_type: Optional override. Auto-detected from extension.
            use_cache: Whether to use cached results.

        Returns:
            DocumentAnalysis with extracted fields, tables, and metadata.

        Raises:
            UnsupportedDocumentType: If file type is not supported.
            AnalysisError: If analysis fails.
        """
        path = Path(file_path)
        t0 = time.perf_counter()

        if not path.exists():
            raise AnalysisError(str(path), "File not found")

        file_size = path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            raise AnalysisError(
                str(path),
                f"File too large: {file_size / 1024 / 1024:.1f} MB "
                f"(max {MAX_FILE_SIZE / 1024 / 1024:.0f} MB)",
            )

        doc_type = document_type or self._detect_type(path)

        # Extract raw content
        raw_text, metadata = self._extract(path, doc_type)

        if not raw_text.strip():
            raise AnalysisError(str(path), "No content could be extracted")

        # Build analysis prompt
        prompt = self.pm.render(
            "detect_table",
            document_type=doc_type.value,
            raw_content=truncate_text(raw_text, 15000),
            file_name=path.name,
        )

        # Call AI provider
        response = self.provider.analyze_document(
            content=prompt,
            system_instruction=(
                "Eres un analista de documentos experto. "
                "Extrae tablas, campos y metadatos del documento proporcionado. "
                "Responde SIEMPRE en español colombiano."
            ),
            use_cache=use_cache,
        )

        elapsed_ms = (time.perf_counter() - t0) * 1000

        if not response.success:
            raise AnalysisError(str(path), response.error or "AI analysis failed")

        # Parse response
        return self._parse_response(
            raw_text=raw_text,
            ai_response=response,
            doc_type=doc_type,
            metadata=metadata,
            elapsed_ms=elapsed_ms,
        )

    def analyze_text_direct(
        self,
        text: str,
        document_type: DocumentType = DocumentType.TEXT,
        use_cache: bool = True,
    ) -> DocumentAnalysis:
        """
        Analyze raw text directly (without a file).

        Useful for processing text already in memory (e.g., from an upload).
        """
        t0 = time.perf_counter()

        prompt = self.pm.render(
            "detect_table",
            document_type=document_type.value,
            raw_content=truncate_text(text, 15000),
            file_name="direct_input",
        )

        response = self.provider.analyze_document(
            content=prompt,
            system_instruction=(
                "Eres un analista de documentos experto. "
                "Extrae tablas, campos y metadatos del texto proporcionado. "
                "Responde SIEMPRE en español colombiano."
            ),
            use_cache=use_cache,
        )

        elapsed_ms = (time.perf_counter() - t0) * 1000

        if not response.success:
            raise AnalysisError("direct_input", response.error or "AI analysis failed")

        return self._parse_response(
            raw_text=text,
            ai_response=response,
            doc_type=document_type,
            metadata={"source": "direct_input"},
            elapsed_ms=elapsed_ms,
        )

    # ──────────────────────────────────────────────
    # Internal methods
    # ──────────────────────────────────────────────

    def _detect_type(self, path: Path) -> DocumentType:
        """Detect document type from file extension."""
        ext = path.suffix.lower()
        doc_type = EXTENSION_MAP.get(ext)
        if doc_type is None:
            raise UnsupportedDocumentType(ext)
        return doc_type

    def _extract(self, path: Path, doc_type: DocumentType) -> tuple[str, dict[str, Any]]:
        """
        Extract raw text content from a document.
        Returns (text, metadata).
        """
        metadata: dict[str, Any] = {
            "file_name": path.name,
            "file_size": path.stat().st_size,
            "document_type": doc_type.value,
        }

        if doc_type == DocumentType.EXCEL:
            text = extract_text_from_excel(path)
        elif doc_type == DocumentType.CSV:
            text = extract_text_from_csv(path)
        elif doc_type == DocumentType.PDF:
            text = extract_text_from_pdf(path)
        elif doc_type in (DocumentType.IMAGE,):
            # For images, we'll pass the base64 to the provider
            mime, b64 = file_to_base64(path)
            metadata["mime_type"] = mime
            metadata["base64_length"] = len(b64)
            # Return a placeholder text; the actual image data goes through
            # analyze_image path
            return f"[Image: {path.name}]", metadata
        elif doc_type == DocumentType.TEXT:
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            text = ""

        metadata["char_count"] = len(text)
        metadata["line_count"] = text.count("\n") + 1

        return text, metadata

    def _parse_response(
        self,
        raw_text: str,
        ai_response: AIResponse,
        doc_type: DocumentType,
        metadata: dict[str, Any],
        elapsed_ms: float,
    ) -> DocumentAnalysis:
        """
        Parse the AI response into a DocumentAnalysis.
        Tries JSON first; falls back to text heuristic parsing.
        """
        # Try JSON path
        if ai_response.json_data:
            return self._parse_json_response(
                ai_response.json_data,
                raw_text,
                doc_type,
                metadata,
                elapsed_ms,
            )

        # Try to parse JSON from text
        parsed = safe_json_parse(ai_response.text)
        if parsed:
            return self._parse_json_response(
                parsed, raw_text, doc_type, metadata, elapsed_ms,
            )

        # Fallback: create minimal analysis from raw text
        logger.warning("AI response was not JSON. Using fallback parsing.")
        warnings = ["AI response was not structured JSON. Results may be incomplete."]
        return DocumentAnalysis(
            document_type=doc_type,
            raw_text=raw_text,
            metadata=metadata,
            warnings=warnings + [ai_response.text[:500]],
            confidence=0.3,
            processing_time_ms=elapsed_ms,
        )

    def _parse_json_response(
        self,
        data: dict[str, Any],
        raw_text: str,
        doc_type: DocumentType,
        metadata: dict[str, Any],
        elapsed_ms: float,
    ) -> DocumentAnalysis:
        """Parse a JSON response into DocumentAnalysis."""
        fields = []
        for f_data in data.get("fields", []):
            if isinstance(f_data, dict):
                fields.append(DetectedField(
                    name=f_data.get("name", ""),
                    suggested_type=f_data.get("type", "texto"),
                    required=f_data.get("required", False),
                    unique=f_data.get("unique", False),
                    is_identifier=f_data.get("is_identifier", False),
                    confidence=f_data.get("confidence", 0.0),
                    explanation=f_data.get("explanation", ""),
                ))

        tables = []
        for t_data in data.get("tables", []):
            if isinstance(t_data, dict):
                tables.append(DetectedTable(
                    name=t_data.get("name", ""),
                    headers=t_data.get("headers", []),
                    rows=t_data.get("rows", []),
                    row_count=len(t_data.get("rows", [])),
                    confidence=t_data.get("confidence", 0.0),
                ))

        warnings = data.get("warnings", [])
        if isinstance(warnings, list):
            warnings = [str(w) for w in warnings]

        return DocumentAnalysis(
            document_type=DocumentType(data.get("document_type", doc_type.value)),
            tables=tables,
            fields=fields,
            metadata={**metadata, **data.get("metadata", {})},
            confidence=data.get("confidence", ai_response.json_data.get("confidence", 0.0) if ai_response.json_data else 0.0),
            warnings=warnings,
            raw_text=raw_text,
            processing_time_ms=elapsed_ms,
        )
