"""
structure_detector.py — Smart document type detector.

Analyzes extracted document content and classifies it into a known type:
  - inventory, sales, clients, products, employees, invoices,
    quotes, purchases, contracts, orders, assets, payments, unknown

Uses heuristics FIRST (column name matching, keyword detection) and
only calls AI when heuristics cannot determine the type with confidence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.ai.services.prompt_manager import get_prompt_manager
from apps.platform.document_intelligence.extractors.base import (
    ExtractedDocument,
)

logger = logging.getLogger(__name__)


# Known document type signatures (keyword → type mapping)
_TYPE_SIGNATURES: dict[str, list[str]] = {
    "inventario": [
        "stock", "existencias", "inventario", "bodega", "almacén", "almacen",
        "cantidad disponible", "unidades", "movimiento",
    ],
    "ventas": [
        "venta", "factura", "cliente", "total", "subtotal", "iva",
        "producto", "cantidad", "precio", "descuento",
    ],
    "clientes": [
        "cliente", "nombre", "apellido", "dirección", "direccion",
        "teléfono", "telefono", "email", "correo", "nit", "cédula",
        "cedula", "documento", "ciudad", "municipio",
    ],
    "productos": [
        "producto", "código", "codigo", "precio", "costo", "sku",
        "referencia", "categoria", "marca", "proveedor",
    ],
    "empleados": [
        "empleado", "trabajador", "salario", "cargo", "departamento",
        "fecha ingreso", "horario", "nómina", "nomina",
    ],
    "facturas": [
        "factura", "nf", "n° factura", "numero factura", "número factura",
        "nit", "proveedor", "fecha emisión", "fecha vencimiento",
        "subtotal", "iva", "total", "retefuente",
    ],
    "cotizaciones": [
        "cotización", "cotizacion", "propuesta", "presupuesto", "quote",
        "validez", "precio unitario",
    ],
    "compras": [
        "orden compra", "proveedor", "fecha pedido", "fecha entrega",
        "compra", "solicitud",
    ],
    "contratos": [
        "contrato", "vigencia", "fecha inicio", "fecha fin",
        "cláusula", "partes", "obligaciones",
    ],
    "pedidos": [
        "pedido", "orden", "despacho", "fecha pedido", "fecha entrega",
        "dirección envío", "direccion envio",
    ],
    "activos": [
        "activo", "activo fijo", "serial", "placa", "ubicación",
        "ubicacion", "departamento", "responsable",
    ],
    "pagos": [
        "pago", "recibo", "comprobante", "banco", "cuenta",
        "valor pagado", "fecha pago", "referencia pago",
    ],
}


@dataclass
class DocumentClassification:
    """Result of document type classification."""
    document_type: str = "unknown"
    confidence: float = 0.0
    method: str = "heuristic"
    explanation: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class StructureDetector:
    """
    Smart document type detector.

    Pipeline:
      1. Heuristic matching on column names (fast, no AI cost)
      2. Content analysis (keyword density per type category)
      3. AI analysis (ONLY if heuristic confidence < 0.70)
    """

    def __init__(self, provider: Optional[BaseAIProvider] = None):
        self.provider = provider
        self.pm = get_prompt_manager() if provider else None

    def classify(
        self,
        doc: ExtractedDocument,
        use_cache: bool = True,
    ) -> DocumentClassification:
        """
        Classify the document type.

        Args:
            doc: Extracted document.
            use_cache: Whether to use cached AI results.

        Returns:
            DocumentClassification with type, confidence, and explanation.
        """
        # STEP 1: Heuristic from column names
        heuristic_result = self._heuristic_classify(doc)
        if heuristic_result.confidence >= 0.70:
            return heuristic_result

        # STEP 2: Heuristic from content keyword density
        content_result = self._content_classify(doc)
        if content_result.confidence >= 0.70:
            return content_result

        # STEP 3: Fallback to AI for ambiguous documents
        if self.provider and self.pm:
            return self._ai_classify(doc, use_cache)

        # Final fallback
        return heuristic_result

    def _heuristic_classify(self, doc: ExtractedDocument) -> DocumentClassification:
        """Heuristic classification based on column header keywords."""
        if not doc.columns:
            return DocumentClassification(confidence=0.0)

        all_text = " ".join(h.lower() for h in doc.columns if h)
        if not all_text:
            return DocumentClassification(confidence=0.0)

        scores: dict[str, float] = {}
        for doc_type, keywords in _TYPE_SIGNATURES.items():
            score = 0.0
            for kw in keywords:
                if kw in all_text:
                    score += 1.0
                else:
                    # Partial word match
                    words = all_text.split()
                    for w in words:
                        if kw in w or w in kw:
                            score += 0.5
                            break
            if score > 0:
                scores[doc_type] = score / len(keywords)

        if not scores:
            return DocumentClassification(confidence=0.0)

        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]

        # Normalize score
        normalized = min(best_score, 1.0)

        return DocumentClassification(
            document_type=best_type,
            confidence=normalized,
            method="heuristic",
            explanation=f"Detected as '{best_type}' based on column name keywords ({normalized:.0%} confidence)",
        )

    def _content_classify(self, doc: ExtractedDocument) -> DocumentClassification:
        """Heuristic classification based on content keyword density."""
        text = doc.raw_text.lower()
        if not text or len(text) < 50:
            return DocumentClassification(confidence=0.0)

        scores: dict[str, float] = {}
        for doc_type, keywords in _TYPE_SIGNATURES.items():
            matches = sum(1 for kw in keywords if kw in text)
            if matches > 0:
                scores[doc_type] = matches / max(len(keywords) * 0.3, 1)

        if not scores:
            return DocumentClassification(confidence=0.0)

        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]

        return DocumentClassification(
            document_type=best_type,
            confidence=min(best_score, 0.95),
            method="content_heuristic",
            explanation=f"Detected as '{best_type}' based on content analysis ({best_score:.0%} confidence)",
        )

    def _ai_classify(self, doc: ExtractedDocument, use_cache: bool) -> DocumentClassification:
        """AI-powered classification fallback."""
        try:
            markdown = doc.to_markdown_table(max_rows=15)
            prompt = self.pm.render(
                "detect_table",
                document_type=doc.document_type,
                raw_content=markdown,
                file_name=doc.title,
            )

            response = self.provider.analyze_text(
                text=prompt,
                system_instruction=(
                    "Clasifica este documento en uno de estos tipos: "
                    "inventario, ventas, clientes, productos, empleados, "
                    "facturas, cotizaciones, compras, contratos, pedidos, "
                    "activos, pagos, u otros. "
                    "Responde SOLO con el nombre del tipo y tu confianza."
                ),
                use_cache=use_cache,
            )

            if response.success and response.text:
                text_lower = response.text.lower().strip()
                for doc_type in _TYPE_SIGNATURES:
                    if doc_type in text_lower:
                        return DocumentClassification(
                            document_type=doc_type,
                            confidence=0.85,
                            method="ai",
                            explanation=f"AI classified this document as '{doc_type}'",
                        )

        except Exception as e:
            logger.warning("AI classification failed: %s", e)

        return DocumentClassification(confidence=0.0, method="ai_fallback")
