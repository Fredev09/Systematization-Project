"""
auto_form_creator.py — AI-powered automatic form creator.

Takes an extracted document and classification, generates a complete
form proposal with fields, types, validations, identifier, currency, etc.

The proposal is NOT saved to DB — the user reviews and confirms first.
Reuses apps.platform.ai.services.FieldDetector and FormGenerator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.ai.services.field_detector import FieldDetector
from apps.platform.ai.services.form_generator import FormGenerator
from apps.platform.ai.types import DetectedField, FormProposal
from apps.platform.document_intelligence.extractors.base import (
    ExtractedDocument,
)
from apps.platform.document_intelligence.services.structure_detector import (
    DocumentClassification,
)

logger = logging.getLogger(__name__)


@dataclass
class FormCreationProposal:
    """
    Complete form creation proposal for user review.

    NOT saved to DB — displayed in the review screen for user confirmation.
    """
    form_name: str
    form_description: str = ""
    fields: list[DetectedField] = field(default_factory=list)
    total_fields: int = 0
    identifier_field: Optional[str] = None
    currency_field: Optional[str] = None
    confidence: float = 0.0
    source_document: str = ""
    warnings: list[str] = field(default_factory=list)

    # Records extracted from unstructured documents (PDF, images, text).
    # For structured docs (Excel, CSV), records come from the extractor.
    records: list[dict[str, str]] = field(default_factory=list)
    records_confidence: float = 0.0
    records_reason: str = ""


class AutoFormCreator:
    """
    Automatically creates form proposals from extracted documents.

    Usage:
        creator = AutoFormCreator(provider=gemini_provider)
        proposal = creator.create_proposal(extracted_doc, classification)
        if proposal.total_fields > 0:
            # Show review screen
    """

    def __init__(self, provider: BaseAIProvider):
        self.provider = provider
        self.field_detector = FieldDetector(provider)
        self.form_generator = FormGenerator(provider)

    def create_proposal(
        self,
        extracted_doc: ExtractedDocument,
        classification: Optional[DocumentClassification] = None,
        use_cache: bool = True,
    ) -> FormCreationProposal:
        """
        Create a form proposal from an extracted document.

        Pipeline:
          1. Detect fields from document headers + sample rows
          2. Generate form proposal (name, description, fields, metadata)
          3. Build FormCreationProposal for user review

        Args:
            extracted_doc: Extracted document.
            classification: Optional document type classification.
            use_cache: Whether to use cached AI results.

        Returns:
            FormCreationProposal for user review.
        """
        source_name = extracted_doc.title
        doc_type = classification.document_type if classification else "unknown"

        has_columns = bool(extracted_doc.columns)
        raw_text = extracted_doc.raw_text if hasattr(extracted_doc, "raw_text") else ""

        # ── Structured document (Excel, CSV) — use existing column+headers path ──
        if has_columns:
            return self._create_from_structured(
                extracted_doc, doc_type, source_name, use_cache,
            )

        # ── Unstructured document (PDF, image, text) — single AI call ──
        return self._create_from_unstructured(
            extracted_doc, doc_type, source_name, raw_text, use_cache,
        )

    def _create_from_structured(
        self,
        extracted_doc: ExtractedDocument,
        doc_type: str,
        source_name: str,
        use_cache: bool,
    ) -> FormCreationProposal:
        """Create proposal from structured document (has columns/headers)."""
        form_name = self._suggest_form_name(extracted_doc, doc_type)

        # Pass ALL rows — FieldDetector._format_sample_rows will
        # uniformly sample ~20 rows internally for the LLM context.
        fields = self.field_detector.analyze_data(
            headers=extracted_doc.columns,
            sample_rows=extracted_doc.rows,
            use_cache=use_cache,
        )

        if not fields:
            logger.warning("No fields detected for %s. Using column names as text fields.", source_name)
            fields = [
                DetectedField(name=h, suggested_type="texto", confidence=0.5, order=idx)
                for idx, h in enumerate(extracted_doc.columns)
            ]

        # Generate form proposal
        proposal = self.form_generator.generate(
            fields=fields,
            source_name=source_name,
            description=f"Formulario generado a partir de {doc_type}: {source_name}",
            use_cache=use_cache,
        )

        # Find identifier and currency fields
        identifier_field = next(
            (f.name for f in proposal.fields if f.is_identifier), None
        )
        currency_field = next(
            (f.name for f in proposal.fields if f.suggested_type == "moneda"), None
        )

        return FormCreationProposal(
            form_name=proposal.form_name,
            form_description=proposal.form_description,
            fields=proposal.fields,
            total_fields=len(proposal.fields),
            identifier_field=identifier_field,
            currency_field=currency_field,
            confidence=proposal.confidence,
            source_document=source_name,
            warnings=proposal.warnings,
        )

    def _create_from_unstructured(
        self,
        extracted_doc: ExtractedDocument,
        doc_type: str,
        source_name: str,
        raw_text: str,
        use_cache: bool,
    ) -> FormCreationProposal:
        """
        Create proposal from unstructured document (no columns/headers).

        Uses a single AI call to detect fields + extract records simultaneously.
        """
        fields, records, confidence, ai_form_name = self.field_detector.analyze_unstructured(
            raw_text=raw_text,
            use_cache=use_cache,
        )

        form_name = ai_form_name or self._suggest_form_name(extracted_doc, doc_type)

        if not fields:
            logger.warning("No fields detected for unstructured doc: %s", source_name)
            return FormCreationProposal(
                form_name=form_name,
                form_description=f"Formulario generado a partir de {doc_type}: {source_name}",
                warnings=["No se pudieron detectar campos automáticamente. Usa el editor para definirlos manualmente."],
                source_document=source_name,
                records=records,
                records_confidence=confidence,
                records_reason=f"{len(records)} registros extraídos vía IA con confianza {confidence:.0%}",
            )

        # Generate form proposal
        proposal = self.form_generator.generate(
            fields=fields,
            source_name=source_name,
            description=f"Formulario generado a partir de {doc_type}: {source_name}",
            use_cache=use_cache,
        )

        # Find identifier and currency fields
        identifier_field = next(
            (f.name for f in proposal.fields if f.is_identifier), None
        )
        currency_field = next(
            (f.name for f in proposal.fields if f.suggested_type == "moneda"), None
        )

        records_reason = f"{len(records)} registros extraídos vía IA con confianza {confidence:.0%}" if records else "No se pudieron extraer registros automáticamente"

        return FormCreationProposal(
            form_name=proposal.form_name,
            form_description=proposal.form_description,
            fields=proposal.fields,
            total_fields=len(proposal.fields),
            identifier_field=identifier_field,
            currency_field=currency_field,
            confidence=proposal.confidence,
            source_document=source_name,
            warnings=proposal.warnings,
            records=records,
            records_confidence=confidence,
            records_reason=records_reason,
        )

    def _suggest_form_name(
        self,
        doc: ExtractedDocument,
        doc_type: str,
    ) -> str:
        """Suggest a form name from document info."""
        type_names = {
            "inventario": "Inventario",
            "ventas": "Ventas",
            "clientes": "Clientes",
            "productos": "Productos",
            "empleados": "Empleados",
            "facturas": "Facturas",
            "cotizaciones": "Cotizaciones",
            "compras": "Compras",
            "contratos": "Contratos",
            "pedidos": "Pedidos",
            "activos": "Activos Fijos",
            "pagos": "Pagos",
        }

        if doc_type in type_names:
            return type_names[doc_type]

        # From filename
        name = doc.title
        for ext in [".xlsx", ".xls", ".csv", ".pdf", ".txt", ".json"]:
            if name.lower().endswith(ext):
                name = name[:-len(ext)]
        name = name.replace("_", " ").replace("-", " ").strip()
        if name and len(name) > 2:
            return name.title()

        return "Documento sin clasificar"
