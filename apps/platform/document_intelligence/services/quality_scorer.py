"""
quality_scorer.py — Quality scoring service.

Assigns an overall quality score (★★★★★) with:
  - Overall score and stars
  - Field-level explanations
  - Recommendations for improvement
  - Risk assessment
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from apps.platform.document_intelligence.extractors.base import ExtractedDocument
from apps.platform.document_intelligence.services.auto_form_creator import FormCreationProposal
from apps.platform.document_intelligence.services.structure_detector import DocumentClassification

logger = logging.getLogger(__name__)


@dataclass
class QualityScore:
    """Quality assessment result."""
    overall: float = 0.0
    stars: int = 0
    label: str = ""
    field_scores: dict[str, float] = field(default_factory=dict)
    field_explanations: dict[str, str] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)


_LABELS = {5: "Excelente", 4: "Buena", 3: "Regular", 2: "Mala", 1: "Muy mala"}


class QualityScorer:
    """Scores the quality of document analysis and form proposals."""

    def score(
        self,
        extracted_doc: ExtractedDocument,
        classification: Optional[DocumentClassification] = None,
        form_proposal: Optional[FormCreationProposal] = None,
    ) -> QualityScore:
        """
        Calculate quality score.

        Factors:
          - Extraction quality (30%)
          - Classification quality (25%)
          - Form proposal quality (30%)
          - Data completeness (15%)
        """
        result = QualityScore()

        # Factor 1: Extraction quality
        extraction_score = self._score_extraction(extracted_doc)
        result.field_scores["extraccion"] = extraction_score
        result.field_explanations["extraccion"] = self._extraction_explanation(extraction_score)

        # Factor 2: Classification quality
        class_score = self._score_classification(classification)
        result.field_scores["clasificacion"] = class_score
        result.field_explanations["clasificacion"] = self._classification_explanation(class_score)

        # Factor 3: Form proposal quality
        form_score = self._score_form_proposal(form_proposal)
        result.field_scores["propuesta"] = form_score
        if form_proposal:
            result.field_explanations["propuesta"] = self._form_explanation(form_proposal)

        # Factor 4: Data completeness
        completeness = self._score_completeness(extracted_doc)
        result.field_scores["completitud"] = completeness

        # Overall weighted score
        weights = {
            "extraccion": 0.30,
            "clasificacion": 0.25,
            "propuesta": 0.30,
            "completitud": 0.15,
        }
        result.overall = sum(
            result.field_scores.get(k, 0.0) * v for k, v in weights.items()
        )

        # Stars
        result.stars = max(1, min(5, round(result.overall * 5)))
        result.label = _LABELS.get(result.stars, "Desconocida")

        # Recommendations
        self._add_recommendations(result, extracted_doc, classification, form_proposal)

        # Risks
        self._add_risks(result, extracted_doc, classification, form_proposal)

        # Strengths
        self._add_strengths(result, extracted_doc)

        return result

    def _score_extraction(self, doc: ExtractedDocument) -> float:
        if not doc or doc.is_empty:
            return 0.0
        scores = [doc.confidence]
        if doc.columns:
            scores.append(0.3)
        if doc.rows:
            scores.append(min(0.4, len(doc.rows) / 100 * 0.4))
        if doc.raw_text and len(doc.raw_text) > 100:
            scores.append(0.2)
        return min(sum(scores), 1.0)

    def _score_classification(self, classification: Optional[DocumentClassification]) -> float:
        if not classification:
            return 0.0
        if classification.document_type != "unknown":
            return classification.confidence
        return 0.2

    def _score_form_proposal(self, proposal: Optional[FormCreationProposal]) -> float:
        if not proposal or not proposal.fields:
            return 0.0
        n_fields = len(proposal.fields)
        if n_fields == 0:
            return 0.0
        has_id = 0.2 if proposal.identifier_field else 0.0
        has_currency = 0.1 if proposal.currency_field else 0.0
        confidence = proposal.confidence * 0.4
        field_variety = min(len(set(f.suggested_type for f in proposal.fields)) / 5, 1.0) * 0.3
        return min(confidence + has_id + has_currency + field_variety, 1.0)

    def _score_completeness(self, doc: ExtractedDocument) -> float:
        if not doc:
            return 0.0
        score = 0.0
        if doc.columns:
            score += 0.3
        if doc.rows:
            score += 0.3 * min(len(doc.rows) / 50, 1.0)
        if doc.raw_text:
            score += 0.2
        if doc.tables:
            score += 0.2
        return min(score, 1.0)

    def _extraction_explanation(self, score: float) -> str:
        if score >= 0.9:
            return "Extracción completa: todas las columnas y filas detectadas correctamente."
        elif score >= 0.7:
            return "Extracción aceptable: la mayoría de datos fueron extraídos."
        elif score >= 0.4:
            return "Extracción parcial: algunos datos no pudieron ser extraídos."
        return "Extracción deficiente: pocos datos pudieron ser extraídos del documento."

    def _classification_explanation(self, score: float) -> str:
        if score >= 0.8:
            return "Clasificación confiable: el tipo de documento fue identificado con alta certeza."
        elif score >= 0.5:
            return "Clasificación moderada: el tipo podría ser correcto pero hay ambigüedad."
        return "No se pudo clasificar el tipo de documento automáticamente."

    def _form_explanation(self, proposal: FormCreationProposal) -> str:
        parts = [f"{proposal.total_fields} campos detectados"]
        if proposal.identifier_field:
            parts.append(f"identificador: {proposal.identifier_field}")
        if proposal.currency_field:
            parts.append(f"moneda: {proposal.currency_field}")
        return "Propuesta: " + ", ".join(parts)

    def _add_recommendations(self, result: QualityScore, doc, classification, proposal):
        if not doc.columns:
            result.recommendations.append("No se detectaron columnas en el documento.")
        if classification and classification.document_type == "unknown":
            result.recommendations.append("El tipo de documento no pudo identificarse. Revisa el nombre del archivo.")
        if proposal and proposal.total_fields == 0:
            result.recommendations.append("No se detectaron campos. Intenta con un documento más estructurado.")
        if doc and doc.warnings:
            for w in doc.warnings[:3]:
                result.recommendations.append(f"Advertencia: {w}")
        if result.stars <= 2:
            result.recommendations.append("Considera usar un archivo Excel con encabezados claros en la primera fila.")

    def _add_risks(self, result: QualityScore, doc, classification, proposal):
        if doc and doc.confidence < 0.5:
            result.risks.append("Baja confianza en la extracción. Verifica los datos manualmente.")
        if classification and classification.document_type == "unknown":
            result.risks.append("Tipo de documento desconocido. El formulario podría no ser adecuado.")
        if proposal and proposal.total_fields > 20:
            result.risks.append("Muchos campos detectados. Revisa que todos sean necesarios.")

    def _add_strengths(self, result: QualityScore, doc):
        if doc and doc.columns:
            result.strengths.append(f"{len(doc.columns)} columnas detectadas")
        if doc and doc.rows:
            result.strengths.append(f"{len(doc.rows)} filas de datos")
        if doc and doc.document_type != "unknown":
            result.strengths.append(f"Tipo de documento identificado: {doc.document_type}")
