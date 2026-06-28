"""
invoice_analyzer.py — Invoice analysis service.

Extracts normalized invoice data from images, PDFs, scans, or text.
Returns an InvoiceData object without saving to DB — pure analysis only.

Pipeline:
  1. Extract text or image data from source
  2. Load invoice analysis prompt
  3. Call AI provider
  4. Parse and validate against invoice schema
  5. Return InvoiceData with confidence score

Supports OCR-style analysis via image-capable providers (Gemini, etc.).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional, Union

from apps.platform.ai.exceptions import AnalysisError, UnsupportedDocumentType
from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.ai.services.prompt_manager import get_prompt_manager
from apps.platform.ai.types import (
    AIResponse,
    DetectedField,
    DocumentType,
    InvoiceData,
)
from apps.platform.ai.utils import (
    extract_text_from_pdf,
    file_to_base64,
    safe_json_parse,
    truncate_text,
)

logger = logging.getLogger(__name__)


class InvoiceAnalyzer:
    """
    Analyzes invoices from images, PDFs, or text.

    Usage:
        analyzer = InvoiceAnalyzer(provider=gemini_provider)
        invoice = analyzer.analyze("factura.pdf")
        print(invoice.provider, invoice.total, invoice.confidence)
    """

    # Keywords that indicate an invoice document
    INVOICE_KEYWORDS = [
        "factura", "invoice", "recibo", "cuenta de cobro",
        "comprobante", "recibo de caja", "facturación",
        "nit", "númer", "total", "subtotal", "iva",
    ]

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
        use_cache: bool = True,
    ) -> InvoiceData:
        """
        Analyze an invoice from a file (image, PDF, or text).

        Args:
            file_path: Path to the invoice file.
            use_cache: Whether to use cached results.

        Returns:
            InvoiceData with extracted fields and confidence.

        Raises:
            AnalysisError: If analysis fails.
            UnsupportedDocumentType: If file type is not supported.
        """
        path = Path(file_path)
        t0 = time.perf_counter()

        if not path.exists():
            raise AnalysisError(str(path), "File not found")

        ext = path.suffix.lower()

        # Route to appropriate analysis method
        if ext in (".jpg", ".jpeg", ".png", ".webp"):
            return self._analyze_image(path, use_cache, t0)
        elif ext == ".pdf":
            return self._analyze_pdf(path, use_cache, t0)
        elif ext in (".txt", ".md", ".json"):
            text = path.read_text(encoding="utf-8", errors="replace")
            return self._analyze_text(text, path.name, use_cache, t0)
        else:
            raise UnsupportedDocumentType(ext)

    def analyze_image_direct(
        self,
        image_base64: str,
        mime_type: str = "image/jpeg",
        file_name: str = "invoice_image",
        use_cache: bool = True,
    ) -> InvoiceData:
        """
        Analyze an invoice from a base64-encoded image (e.g., from a mobile upload).
        """
        t0 = time.perf_counter()
        prompt = self.pm.render(
            "detect_invoice",
            document_type="imagen de factura",
        )

        response = self.provider.analyze_image(
            image_data=image_base64,
            mime_type=mime_type,
            system_instruction=(
                "Eres un contador experto colombiano. "
                "Extrae todos los datos de esta factura con la máxima precisión. "
                "Responde ÚNICAMENTE con JSON válido."
            ),
            use_cache=use_cache,
        )

        return self._parse_response(
            response, file_name, image_base64, t0,
            source_type="imagen",
        )

    def analyze_text_direct(
        self,
        text: str,
        file_name: str = "invoice_text",
        use_cache: bool = True,
    ) -> InvoiceData:
        """
        Analyze an invoice from raw text.
        """
        return self._analyze_text(text, file_name, use_cache, time.perf_counter())

    # ──────────────────────────────────────────────
    # Internal methods
    # ──────────────────────────────────────────────

    def _analyze_image(
        self,
        path: Path,
        use_cache: bool,
        t0: float,
    ) -> InvoiceData:
        """Analyze an invoice image."""
        mime, b64 = file_to_base64(path)

        prompt = self.pm.render(
            "detect_invoice",
            document_type="imagen de factura",
        )

        response = self.provider.analyze_image(
            image_data=b64,
            mime_type=mime,
            system_instruction=(
                "Eres un contador experto colombiano. "
                "Extrae todos los datos de esta factura con la máxima precisión. "
                "Responde ÚNICAMENTE con JSON válido."
            ),
            use_cache=use_cache,
        )

        return self._parse_response(
            response, path.name, b64, t0, source_type="imagen",
        )

    def _analyze_pdf(
        self,
        path: Path,
        use_cache: bool,
        t0: float,
    ) -> InvoiceData:
        """Analyze an invoice PDF."""
        text = extract_text_from_pdf(path, max_pages=5)
        if not text or text.startswith("[PDF"):
            # Fall back to image-based analysis
            try:
                mime, b64 = file_to_base64(path)
                return self._analyze_image(path, use_cache, t0)
            except Exception:
                logger.warning("PDF text extraction returned no content for %s", path.name)
                return InvoiceData(
                    provider="",
                    confidence=0.0,
                    warnings=["No se pudo extraer texto del PDF. Intenta con una imagen."],
                )

        return self._analyze_text(text, path.name, use_cache, t0)

    def _analyze_text(
        self,
        text: str,
        file_name: str,
        use_cache: bool,
        t0: float,
    ) -> InvoiceData:
        """Analyze invoice text."""
        if not text.strip():
            return InvoiceData(
                confidence=0.0,
                warnings=["No hay contenido de texto para analizar."],
            )

        prompt = self.pm.render(
            "detect_invoice",
            document_type="texto de factura",
        )

        prompt_full = (
            f"{prompt}\n\n"
            f"--- TEXTO DE LA FACTURA ---\n"
            f"{truncate_text(text, 20000)}"
        )

        response = self.provider.analyze_document(
            content=prompt_full,
            system_instruction=(
                "Eres un contador experto colombiano. "
                "Extrae todos los datos de esta factura con la máxima precisión. "
                "Responde ÚNICAMENTE con JSON válido."
            ),
            use_cache=use_cache,
        )

        return self._parse_response(
            response, file_name, text, t0, source_type="texto",
        )

    def _parse_response(
        self,
        response: AIResponse,
        file_name: str,
        raw_content: str,
        t0: float,
        source_type: str = "texto",
    ) -> InvoiceData:
        """
        Parse AI response into InvoiceData.
        """
        elapsed_ms = (time.perf_counter() - t0) * 1000
        warnings: list[str] = []

        # Try JSON from structured response first
        data = response.json_data

        # Fallback to text parse
        if not data and response.text:
            data = safe_json_parse(response.text)

        if not data:
            warnings.append("La respuesta de IA no fue JSON válido. Resultados limitados.")
            return InvoiceData(
                warnings=warnings + [response.text[:500]],
                confidence=0.2,
            )

        # Map common field name variations
        def _get(*keys: str) -> Any:
            """Get first matching key from data dict."""
            for key in keys:
                val = data.get(key)
                if val is not None:
                    return val
            return ""

        def _to_float(val: Any) -> float:
            """Convert value to float safely."""
            if val is None:
                return 0.0
            if isinstance(val, (int, float)):
                return float(val)
            try:
                return float(str(val).replace("$", "").replace(",", "").replace(" ", ""))
            except (ValueError, TypeError):
                return 0.0

        # Parse detected fields
        detected_fields = []
        raw_fields = data.get("fields", data.get("campos", []))
        if isinstance(raw_fields, list):
            for f_data in raw_fields:
                if isinstance(f_data, dict):
                    detected_fields.append(DetectedField(
                        name=f_data.get("name", f_data.get("nombre", "")),
                        suggested_type=f_data.get("type", f_data.get("tipo", "texto")),
                        confidence=f_data.get("confidence", f_data.get("confianza", 0.0)),
                        explanation=f_data.get("explanation", ""),
                    ))

        # Parse items
        items = data.get("items", data.get("productos", data.get("detalles", [])))
        if isinstance(items, list):
            items = [
                {
                    "descripcion": item.get("descripcion", item.get("description", "")),
                    "cantidad": _to_float(item.get("cantidad", item.get("quantity", 0))),
                    "valor_unitario": _to_float(item.get("valor_unitario", item.get("unit_price", 0))),
                    "total": _to_float(item.get("total", 0)),
                }
                for item in items
                if isinstance(item, dict)
            ]

        # Parse warnings
        raw_warnings = data.get("warnings", [])
        if isinstance(raw_warnings, list):
            warnings.extend(str(w) for w in raw_warnings)

        if not response.success:
            warnings.append(response.error or "Error en la respuesta de IA")

        return InvoiceData(
            provider=_get("provider", "proveedor", "empresa", "razon_social"),
            nit=_get("nit", "NIT", "identificacion", "documento"),
            invoice_number=_get("invoice_number", "numero", "número", "consecutivo", "factura_numero"),
            date=_get("date", "fecha", "fecha_emision"),
            currency=_get("currency", "moneda", "divisa") or "COP",
            subtotal=_to_float(_get("subtotal", "sub_total", "base")),
            taxes=_to_float(_get("taxes", "impuestos", "iva", "total_impuestos")),
            total=_to_float(_get("total", "total_pagar", "valor_total")),
            items=items,
            detected_fields=detected_fields,
            confidence=_to_float(data.get("confidence", data.get("confianza", response.json_data.get("confidence", 0.0) if response.json_data else 0.5))),
            warnings=warnings,
            raw_json=data,
        )
