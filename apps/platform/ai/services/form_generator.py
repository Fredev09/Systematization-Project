"""
form_generator.py — Automatic form generator service.

Takes analyzed fields and generates a complete FormProposal with:
  - Form name and description
  - Ordered list of fields with types, validations, and metadata
  - Identifier field suggestion
  - Currency field suggestion
  - Suggested relationships
  - Confidence score

The proposal is NOT saved to DB — the user reviews and confirms first.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from apps.platform.ai.exceptions import AnalysisError
from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.ai.services.prompt_manager import get_prompt_manager
from apps.platform.ai.types import (
    DetectedField,
    FieldType,
    FormProposal,
)

logger = logging.getLogger(__name__)


class FormGenerator:
    """
    Generates complete form proposals from field analysis.

    Usage:
        generator = FormGenerator(provider=gemini_provider)
        proposal = generator.generate(
            fields=detected_fields,
            source_name="Productos.xlsx",
        )
        print(proposal.form_name, proposal.confidence)
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

    def generate(
        self,
        fields: list[DetectedField],
        source_name: str = "",
        description: str = "",
        use_cache: bool = True,
    ) -> FormProposal:
        """
        Generate a complete form proposal from detected fields.

        Args:
            fields: List of detected fields from FieldDetector or DocumentAnalyzer.
            source_name: Optional name of the source document.
            description: Optional user description of the form.
            use_cache: Whether to use cached results.

        Returns:
            FormProposal with form name, fields, and confidence.

        Raises:
            AnalysisError: If fields list is empty.
        """
        if not fields:
            raise AnalysisError("form_generator", "No fields provided to generate form")

        # Step 1: Auto-assign metadata (order, identifier, currency)
        fields = self._auto_assign_metadata(fields)

        # Step 2: Suggest form name from fields
        form_name = self._suggest_form_name(fields, source_name, description)

        # Step 3: Calculate overall confidence
        overall_confidence = self._calculate_confidence(fields)

        # Step 4: Collect warnings
        warnings = self._collect_warnings(fields)

        return FormProposal(
            form_name=form_name,
            form_description=description or f"Formulario generado a partir de {source_name or 'análisis de datos'}",
            fields=fields,
            confidence=overall_confidence,
            source_document=source_name or None,
            warnings=warnings,
        )

    def generate_from_analysis(
        self,
        analysis_result: Any,  # DocumentAnalysis or InvoiceData
        source_name: str = "",
        use_cache: bool = True,
    ) -> FormProposal:
        """
        Generate a form proposal from a DocumentAnalysis or InvoiceData result.
        Convenience wrapper around generate().
        """
        # Extract fields from whichever result type
        from apps.platform.ai.types import DocumentAnalysis, InvoiceData

        fields: list[DetectedField] = []

        if hasattr(analysis_result, "fields") and analysis_result.fields:
            fields = analysis_result.fields
        elif hasattr(analysis_result, "detected_fields") and analysis_result.detected_fields:
            fields = analysis_result.detected_fields

        if not fields:
            # Generate fields from detected tables
            if hasattr(analysis_result, "tables"):
                for table in analysis_result.tables:
                    for idx, header in enumerate(table.headers):
                        fields.append(DetectedField(
                            name=header,
                            suggested_type="texto",
                            confidence=table.confidence,
                            order=idx,
                        ))

        if not fields:
            raise AnalysisError("form_generator", "No fields could be extracted from the analysis")

        return self.generate(
            fields=fields,
            source_name=source_name or getattr(analysis_result, "file_name", ""),
            use_cache=use_cache,
        )

    def generate_from_description(
        self,
        description: str,
        use_cache: bool = True,
    ) -> FormProposal:
        """
        Generate a form proposal from a natural language description.

        Usage:
            proposal = generator.generate_from_description(
                "Necesito un formulario para registrar clientes "
                "con nombre, email, teléfono y dirección"
            )
        """
        from apps.platform.ai.services.field_detector import FieldDetector

        detector = FieldDetector(provider=self.provider, prompt_manager=self.pm)
        fields = detector.analyze_text(description, use_cache=use_cache)

        if not fields:
            raise AnalysisError(
                "form_generator",
                "No se pudieron detectar campos desde la descripción",
            )

        return self.generate(
            fields=fields,
            description=description,
            use_cache=use_cache,
        )

    # ──────────────────────────────────────────────
    # Internal logic
    # ──────────────────────────────────────────────

    def _auto_assign_metadata(self, fields: list[DetectedField]) -> list[DetectedField]:
        """
        Auto-assign order, identifier, currency, and required flags.
        """
        # Sort by confidence (highest first) for priority
        sorted_fields = sorted(fields, key=lambda f: f.confidence, reverse=True)

        identifier_candidates = []
        currency_candidates = []

        for idx, field in enumerate(sorted_fields):
            # Assign order
            field.order = idx

            name_lower = field.name.lower().strip()

            # Detect identifier candidate
            if any(kw in name_lower for kw in
                   ["código", "codigo", "id", "identificador", "cód", "sku",
                    "referencia", "cédula", "cedula", "documento"]):
                identifier_candidates.append(field)
                field.is_identifier = True
                if field.confidence < 0.7:
                    field.confidence = 0.7

            # Detect currency candidate
            if any(kw in name_lower for kw in
                   ["precio", "valor", "costo", "total", "subtotal", "monto"]):
                currency_candidates.append(field)
                field.suggested_type = FieldType.MONEDA
                if field.confidence < 0.7:
                    field.confidence = 0.7

            # Detect required fields
            if any(kw in name_lower for kw in
                   ["nombre", "código", "codigo", "email", "correo"]):
                field.required = True

            # Set unique on identifiers
            if field.is_identifier:
                field.unique = True

        # Ensure at least the first identifier candidate stays as identifier
        if identifier_candidates:
            identifier_candidates[0].is_identifier = True
            identifier_candidates[0].unique = True

        return sorted_fields

    def _suggest_form_name(
        self,
        fields: list[DetectedField],
        source_name: str,
        description: str,
    ) -> str:
        """
        Suggest a form name from the fields and source.
        """
        # From source file name
        if source_name:
            name = source_name
            # Remove extension and clean
            for ext in [".xlsx", ".xls", ".csv", ".pdf", ".txt"]:
                if name.lower().endswith(ext):
                    name = name[:-len(ext)]
            # Capitalize and clean
            name = name.replace("_", " ").replace("-", " ").strip()
            if name:
                return name.title()

        # From description
        if description:
            words = description.split()[:5]
            return " ".join(words).title()

        # From fields
        field_names = [f.name for f in fields if f.confidence > 0.5]
        if field_names:
            prefix = field_names[0].strip().capitalize()
            return f"{prefix} y más ({len(field_names)} campos)"

        return "Formulario sin nombre"

    def _calculate_confidence(self, fields: list[DetectedField]) -> float:
        """Calculate overall confidence from individual field confidences."""
        if not fields:
            return 0.0
        return sum(f.confidence for f in fields) / len(fields)

    def _collect_warnings(self, fields: list[DetectedField]) -> list[str]:
        """Collect warnings about the form proposal."""
        warnings = []

        # Low confidence fields
        low_conf_fields = [f for f in fields if f.confidence < 0.5]
        if low_conf_fields:
            warnings.append(
                f"Campos con baja confianza ({len(low_conf_fields)}): "
                + ", ".join(f.name for f in low_conf_fields)
            )

        # Fields without identified type
        text_fields = [f for f in fields if f.suggested_type == FieldType.TEXTO]
        if text_fields and len(text_fields) > len(fields) * 0.7:
            warnings.append(
                "La mayoría de campos son tipo texto. "
                "Revisa que los tipos sean correctos."
            )

        # Missing identifier
        if not any(f.is_identifier for f in fields):
            warnings.append(
                "No se detectó un campo identificador. "
                "Considera agregar un campo 'Código' o 'ID'."
            )

        return warnings
