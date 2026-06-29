"""
pipeline.py — Universal Document Intelligence Pipeline.

THE single pipeline that ALL documents go through:

  Document → Extractor → Normalizer → StructureDetector → AI →
  AutoFormCreator → QualityScorer → Review → Create → Import → Audit

Every document type follows exactly this pipeline.
Only the Extract step changes based on file type.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from django.conf import settings

from apps.platform.ai.exceptions import AIError
from apps.platform.ai.providers import get_provider
from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.ai.models import AIAnalysisLog
from apps.platform.document_intelligence.extractors import (
    ExtractedDocument,
    get_extractor,
)
from apps.platform.document_intelligence.services.structure_detector import (
    StructureDetector,
    DocumentClassification,
)
from apps.platform.document_intelligence.services.auto_form_creator import (
    AutoFormCreator,
    FormCreationProposal,
)
from apps.platform.document_intelligence.services.relationship_detector import (
    RelationshipDetector,
    RelationshipProposal,
)
from apps.platform.document_intelligence.services.memory_learner import (
    MemoryLearner,
)
from apps.platform.document_intelligence.services.quality_scorer import (
    QualityScorer,
    QualityScore,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for a single pipeline run."""
    file_path: str | Path
    file_name: str = ""
    user_id: Optional[int] = None
    use_cache: bool = True
    provider: Optional[BaseAIProvider] = None
    existing_form_id: Optional[int] = None
    auto_create_form: bool = True
    auto_import_data: bool = False


@dataclass
class PipelineResult:
    """Complete result of a pipeline run."""
    success: bool
    step: str = "init"
    extracted_doc: Optional[ExtractedDocument] = None
    classification: Optional[DocumentClassification] = None
    form_proposal: Optional[FormCreationProposal] = None
    relationship_proposal: Optional[RelationshipProposal] = None
    quality_score: Optional[QualityScore] = None
    created_form_id: Optional[int] = None
    import_result: Optional[dict] = None
    analysis_log_id: Optional[int] = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    processing_time_ms: float = 0.0
    cache_hit: bool = False

    # Canonical records — single source of truth for extracted data
    records: list[dict[str, str]] = field(default_factory=list)
    records_count: int = 0
    records_confidence: float = 0.0
    records_reason: str = ""


class DocumentIntelligencePipeline:
    """
    Universal document analysis pipeline.

    Usage:
        pipeline = DocumentIntelligencePipeline()
        result = pipeline.run(PipelineConfig(file_path="factura.pdf"))
        if result.success:
            print(result.form_proposal.form_name)

    Pipeline steps (ALL documents go through ALL steps):
      1. Extract — selecciona extractor por extensión
      2. OCR — solo si el doc es imagen/foto (analyze_image vía provider)
      3. Classify — detecta tipo de documento
      4. Create form — propone campos y formulario
      5. Detect relationships — busca relaciones entre campos
      6. Score quality — evalúa calidad del análisis
      7. Audit — registra en AIAnalysisLog
    """

    def __init__(self, provider: Optional[BaseAIProvider] = None):
        self.provider = provider or get_provider()
        self.extractor = None
        self.structure_detector = StructureDetector(self.provider)
        self.form_creator = AutoFormCreator(self.provider)
        self.relation_detector = RelationshipDetector(self.provider)
        self.memory_learner = MemoryLearner()
        self.quality_scorer = QualityScorer()
        self._t0: float = 0.0

    def run(self, config: PipelineConfig) -> PipelineResult:
        """Execute the complete pipeline."""
        self._t0 = time.perf_counter()
        result = PipelineResult(success=True, step="init")

        try:
            # STEP 1: Extract
            result = self._step_extract(config, result)
            if not result.success:
                return self._finalize(result)

            # STEP 2: OCR — solo para imágenes/fotos
            result = self._step_ocr(config, result)
            if not result.success:
                return self._finalize(result)

            # STEP 3: Classify document type
            result = self._step_classify(config, result)
            if not result.success:
                return self._finalize(result)

            # STEP 4: Create form proposal
            if config.auto_create_form:
                result = self._step_create_form(config, result)

            # STEP 5: Detect relationships
            result = self._step_detect_relationships(config, result)

            # STEP 6: Score quality
            result = self._step_score_quality(result)

            # STEP 7: Log to AIAnalysisLog
            result = self._step_audit(result)

            result.success = True
            result.step = "complete"

        except Exception as e:
            logger.exception("Pipeline failed at step '%s': %s", result.step, e)
            result.success = False
            result.errors.append(f"Pipeline failed at '{result.step}': {e}")

        return self._finalize(result)

    # ── Pipeline steps ──

    def _step_extract(self, config: PipelineConfig, result: PipelineResult) -> PipelineResult:
        result.step = "extract"
        path = Path(config.file_path)

        self.extractor = get_extractor(file_path=path)
        extracted = self.extractor.extract_safe(path)

        if extracted.confidence == 0.0:
            result.errors.append(f"Extraction failed: {extracted.warnings}")
            result.success = False
            return result

        if extracted.is_empty:
            result.errors.append("No content could be extracted from the document")
            result.success = False
            return result

        result.extracted_doc = extracted

        # For structured documents (Excel, CSV), convert rows to canonical records
        if extracted.columns and extracted.rows:
            try:
                cols = extracted.columns
                records = []
                for row in extracted.rows:
                    record = {}
                    for i, col in enumerate(cols):
                        val = row[i] if i < len(row) else ""
                        if val is None:
                            val = ""
                        elif not isinstance(val, str):
                            val = str(val)
                        record[col] = val
                    if any(v for v in record.values()):
                        records.append(record)
                result.records = records
                result.records_count = len(records)
                result.records_confidence = 1.0
                result.records_reason = f"{len(records)} registros extraídos del archivo"
            except Exception as e:
                logger.warning("Records conversion failed: %s", e)
                result.records_reason = f"Error al convertir registros: {e}"

        return result

    def _step_ocr(self, config: PipelineConfig, result: PipelineResult) -> PipelineResult:
        """
        OCR step: solo se ejecuta para imágenes/fotos.
        
        Si el documento extraído contiene imágenes (ImageExtractor) pero
        no tiene texto real, llama a provider.analyze_image() para hacer
        OCR real y reemplaza raw_text con el resultado.
        """
        doc = result.extracted_doc
        if not doc or not doc.images:
            return result  # No es imagen, saltar OCR

        # Solo hacer OCR si el texto extraído es un placeholder
        if doc.raw_text and not doc.raw_text.startswith("[Image:"):
            return result  # Ya tiene texto real

        result.step = "ocr"
        try:
            mime_type, image_data = doc.images[0]
            response = self.provider.analyze_image(
                image_data=image_data,
                mime_type=mime_type,
                system_instruction=(
                    "Extrae TODO el texto de esta imagen con la máxima precisión. "
                    "Si contiene una tabla, devuelve los datos estructurados. "
                    "Responde ÚNICAMENTE con JSON válido."
                ),
                use_cache=config.use_cache,
            )

            if response.success and response.text:
                doc.raw_text = response.text
                if len(response.text.strip()) > 50:
                    doc.confidence = max(doc.confidence, 0.75)
                logger.info("OCR completado para %s: %d caracteres",
                           config.file_name, len(response.text))

                # Intentar extraer JSON estructurado del OCR
                from apps.platform.ai.utils import safe_json_parse
                parsed = safe_json_parse(response.text)
                if parsed and isinstance(parsed, dict):
                    # Si el OCR devolvió JSON con tabla, actualizar columns/rows
                    headers = parsed.get("headers", parsed.get("columns", []))
                    rows = parsed.get("rows", parsed.get("data", []))
                    if headers and rows:
                        doc.columns = headers
                        doc.rows = rows
                        logger.info("OCR: %d columnas, %d filas detectadas",
                                   len(headers), len(rows))
            else:
                logger.warning("OCR falló para %s: %s",
                              config.file_name, response.error or "sin texto")
                result.warnings.append(f"OCR no produjo resultados: {response.error or 'desconocido'}")

        except Exception as e:
            logger.warning("OCR step error (non-fatal): %s", e)
            result.warnings.append(f"OCR error: {e}")
            # No marcar como fallo — continuar con lo que se tenga

        return result

    def _step_classify(self, config: PipelineConfig, result: PipelineResult) -> PipelineResult:
        result.step = "classify"
        classification = self.structure_detector.classify(
            result.extracted_doc,
            use_cache=config.use_cache,
        )
        result.classification = classification
        result.warnings.extend(classification.warnings)
        return result

    def _step_create_form(self, config: PipelineConfig, result: PipelineResult) -> PipelineResult:
        result.step = "create_form"
        proposal = self.form_creator.create_proposal(
            extracted_doc=result.extracted_doc,
            classification=result.classification,
            use_cache=config.use_cache,
        )
        result.form_proposal = proposal

        # Copy records from proposal (populated by AutoFormCreator for unstructured docs).
        # For structured docs, records already set in _step_extract — skip.
        if not result.records and proposal.records:
            result.records = proposal.records
            result.records_count = len(proposal.records)
            result.records_confidence = proposal.records_confidence
            result.records_reason = proposal.records_reason

        return result

    def _step_detect_relationships(self, config: PipelineConfig, result: PipelineResult) -> PipelineResult:
        result.step = "detect_relationships"
        proposal = self.relation_detector.detect(
            extracted_doc=result.extracted_doc,
            classification=result.classification,
            form_proposal=result.form_proposal,
            use_cache=config.use_cache,
        )
        result.relationship_proposal = proposal
        return result

    def _step_score_quality(self, result: PipelineResult) -> PipelineResult:
        result.step = "score_quality"
        score = self.quality_scorer.score(
            extracted_doc=result.extracted_doc,
            classification=result.classification,
            form_proposal=result.form_proposal,
        )
        result.quality_score = score
        return result

    def _step_audit(self, result: PipelineResult) -> PipelineResult:
        """Log the analysis to AIAnalysisLog."""
        result.step = "audit"
        try:
            log_entry = AIAnalysisLog.log(
                provider=self.provider.config.provider_type.value,
                model=self.provider.config.model,
                service="document_intelligence_pipeline",
                document_type=result.extracted_doc.document_type if result.extracted_doc else "",
                document_name=result.extracted_doc.title if result.extracted_doc else "",
                processing_time_ms=(time.perf_counter() - self._t0) * 1000,
                success=True,
                confidence=result.quality_score.overall if result.quality_score else 0.0,
                result_summary=json.dumps({
                    "classification": result.classification.document_type if result.classification else "",
                    "form_name": result.form_proposal.form_name if result.form_proposal else "",
                    "total_fields": len(result.form_proposal.fields) if result.form_proposal else 0,
                    "quality_stars": result.quality_score.stars if result.quality_score else 0,
                }, ensure_ascii=False),
            )
            result.analysis_log_id = log_entry.id
        except Exception as e:
            logger.warning("Audit log error: %s", e)
        return result

    def _finalize(self, result: PipelineResult) -> PipelineResult:
        result.processing_time_ms = (time.perf_counter() - self._t0) * 1000
        return result
