"""
multi_document_pipeline.py — Multi-document Intelligence (FASE 10).

Prepares the pipeline to receive MULTIPLE documents at once:

  Invoice + Purchase Order + Dispatch + Inventory

The AI must be able to:
  - Relate documents to each other
  - Detect inconsistencies between them
  - Find differences
  - Suggest actions
  - Propose automations

Even though there's no UI yet — the infrastructure is ready.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from apps.platform.ai.models import AIAnalysisLog
from apps.platform.ai.providers import get_provider
from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.ai.services.smart_learner import SmartLearner

logger = logging.getLogger(__name__)


# ======================================================================
# Type aliases for lazy imports (avoid circular imports at module level)
# ======================================================================

_PipelineResultType = Any  # Resolved at runtime via lazy import


def _get_pipeline_classes():
    """Lazy import to avoid circular dependency with document_intelligence."""
    from apps.platform.document_intelligence.services.pipeline import (
        DocumentIntelligencePipeline as DIP,
        PipelineConfig as PC,
        PipelineResult as PR,
    )
    return DIP, PC, PR


# ======================================================================
# Data Classes
# ======================================================================

@dataclass
class DocumentInput:
    """A single document input for multi-document analysis."""
    file_path: str | Path
    file_name: str = ""
    document_type: str = ""
    user_id: Optional[int] = None


@dataclass
class CrossDocumentField:
    """A field matched across multiple documents."""
    name: str
    values: dict[str, str]  # doc_key → value
    match: bool = True
    difference: str = ""


@dataclass
class CrossDocumentRelationship:
    """A relationship detected across documents."""
    source_doc: str
    target_doc: str
    relationship_type: str  # "contains", "references", "matches", "summarizes"
    confidence: float
    matched_fields: list[CrossDocumentField] = field(default_factory=list)
    inconsistencies: list[str] = field(default_factory=list)
    explanation: str = ""


@dataclass
class MultiDocumentResult:
    """
    Complete result of multi-document analysis.

    Combines individual pipeline results + cross-document analysis.
    """
    success: bool
    documents: dict[str, Any] = field(default_factory=dict)
    relationships: list[CrossDocumentRelationship] = field(default_factory=list)
    inconsistencies: list[str] = field(default_factory=list)
    summary: str = ""
    suggested_actions: list[str] = field(default_factory=list)
    suggested_automations: list[str] = field(default_factory=list)
    quality_score: float = 0.0
    warnings: list[str] = field(default_factory=list)
    processing_time_ms: float = 0.0
    analysis_log_ids: list[int] = field(default_factory=list)

    def get_doc(self, key: str) -> Any:
        """Get a single document result by key."""
        return self.documents.get(key)


# ======================================================================
# CrossDocumentAnalyzer
# ======================================================================

class CrossDocumentAnalyzer:
    """
    Analyzes relationships and inconsistencies across multiple documents.

    This is the core intelligence of multi-document processing.
    Uses AI to find connections that heuristic analysis would miss.
    """

    def __init__(self, provider: Optional[BaseAIProvider] = None):
        self.provider = provider or get_provider()
        self.smart_learner = SmartLearner()

    def analyze(
        self,
        documents: dict[str, Any],
        use_cache: bool = True,
    ) -> MultiDocumentResult:
        """
        Analyze relationships across multiple documents.

        Args:
            documents: Dict of {document_key: PipelineResult}.
            use_cache: Whether to use cached results.

        Returns:
            MultiDocumentResult with cross-document analysis.
        """
        import time
        t0 = time.perf_counter()

        result = MultiDocumentResult(success=True, documents=documents)

        if len(documents) < 2:
            result.warnings.append("Se necesitan al menos 2 documentos para análisis cruzado")
            return result

        # 1. Detect field matches
        relationships = self._detect_relationships(documents, use_cache)
        result.relationships = relationships

        # 2. Find inconsistencies
        result.inconsistencies = self._find_inconsistencies(relationships)

        # 3. Generate summary
        result.summary = self._generate_summary(documents, relationships)

        # 4. Suggest actions
        result.suggested_actions = self._suggest_actions(relationships, result.inconsistencies)

        # 5. Suggest automations
        result.suggested_automations = self._suggest_automations(relationships)

        # 6. Quality score
        result.quality_score = self._calculate_quality(documents, relationships)

        result.processing_time_ms = (time.perf_counter() - t0) * 1000
        return result

    def _detect_relationships(
        self,
        documents: dict[str, Any],
        use_cache: bool,
    ) -> list[CrossDocumentRelationship]:
        """Detect relationships across documents."""
        relationships = []
        doc_keys = list(documents.keys())

        # First pass: heuristic matching
        for i in range(len(doc_keys)):
            for j in range(i + 1, len(doc_keys)):
                key_a, key_b = doc_keys[i], doc_keys[j]
                doc_a, doc_b = documents[key_a], documents[key_b]

                rel = self._heuristic_match(key_a, key_b, doc_a, doc_b)
                if rel:
                    relationships.append(rel)

        # Second pass: AI-powered matching
        ai_rels = self._ai_match(documents, use_cache)
        relationships.extend(ai_rels)

        return relationships

    def _heuristic_match(
        self,
        key_a: str,
        key_b: str,
        doc_a: Any,
        doc_b: Any,
    ) -> Optional[CrossDocumentRelationship]:
        """Heuristic field matching between two documents."""
        fields_a = self._get_field_names(doc_a)
        fields_b = self._get_field_names(doc_b)

        if not fields_a or not fields_b:
            return None

        # Find common fields (case-insensitive)
        common = []
        for fa in fields_a:
            for fb in fields_b:
                if fa.lower() == fb.lower():
                    val_a = self._get_field_value(doc_a, fa)
                    val_b = self._get_field_value(doc_b, fb)
                    common.append(CrossDocumentField(
                        name=fa,
                        values={key_a: val_a or "", key_b: val_b or ""},
                        match=val_a == val_b if val_a and val_b else True,
                        difference=f"'{val_a}' vs '{val_b}'" if val_a and val_b and val_a != val_b else "",
                    ))

        if not common:
            return None

        overlap_ratio = len(common) / max(len(set(fields_a + fields_b)), 1)
        rel_type = "matches" if overlap_ratio > 0.5 else "references"

        inconsistencies = [
            f"'{c.name}': {c.difference}" for c in common if c.difference
        ]

        return CrossDocumentRelationship(
            source_doc=key_a,
            target_doc=key_b,
            relationship_type=rel_type,
            confidence=min(0.5 + overlap_ratio * 0.3, 0.95),
            matched_fields=common,
            inconsistencies=inconsistencies,
            explanation=(
                f"{len(common)} campos comunes encontrados "
                f"({overlap_ratio:.0%} superposición)"
            ),
        )

    def _ai_match(
        self,
        documents: dict[str, Any],
        use_cache: bool,
    ) -> list[CrossDocumentRelationship]:
        """AI-powered relationship detection."""
        doc_summaries = {}
        for key, doc in documents.items():
            fields = self._get_field_names(doc)
            form_name = ""
            if hasattr(doc, 'form_proposal') and doc.form_proposal:
                form_name = getattr(doc.form_proposal, 'form_name', '')

            doc_summaries[key] = {
                "key": key,
                "form_name": form_name,
                "fields": fields[:20],
                "total_fields": len(fields),
                "total_rows": self._get_row_count(doc),
                "doc_type": self._get_doc_type(doc),
            }

        prompt = (
            "Analiza la relación entre estos documentos:\n\n"
            f"{json.dumps(doc_summaries, ensure_ascii=False, indent=2)}\n\n"
            "Para cada par de documentos, identifica:\n"
            "1. ¿Están relacionados? (sí/no)\n"
            "2. Tipo de relación (contiene, referencia, coincide, resume)\n"
            "3. Campos que se relacionan entre sí\n"
            "4. Inconsistencias detectadas\n"
            "5. Confianza de la relación (0-1)\n\n"
            "Responde ÚNICAMENTE con JSON con una lista 'relationships'."
        )

        response = self.provider.generate_json(
            prompt=prompt,
            system_instruction=(
                "Eres un analista de documentos experto. "
                "Identifica relaciones entre documentos. "
                "Responde ÚNICAMENTE con JSON."
            ),
            use_cache=use_cache,
        )

        if not response.success or not response.json_data:
            return []

        data = response.json_data
        relationships = []
        raw_rels = data.get("relationships", data.get("relaciones", []))

        for rel_data in raw_rels:
            rel = CrossDocumentRelationship(
                source_doc=rel_data.get("source", rel_data.get("origen", "")),
                target_doc=rel_data.get("target", rel_data.get("destino", "")),
                relationship_type=rel_data.get("type", rel_data.get("tipo", "references")),
                confidence=rel_data.get("confidence", rel_data.get("confianza", 0.5)),
                inconsistencies=rel_data.get("inconsistencies", rel_data.get("inconsistencias", [])),
                explanation=rel_data.get("explanation", rel_data.get("explicacion", "")),
            )
            relationships.append(rel)

        return relationships

    def _find_inconsistencies(
        self,
        relationships: list[CrossDocumentRelationship],
    ) -> list[str]:
        """Extract all inconsistencies from relationships."""
        inconsistencies = []
        for rel in relationships:
            inconsistencies.extend(rel.inconsistencies)
            if rel.inconsistencies:
                inconsistencies.append(
                    f"Entre '{rel.source_doc}' y '{rel.target_doc}': "
                    f"{'; '.join(rel.inconsistencies[:3])}"
                )
        return inconsistencies

    def _generate_summary(
        self,
        documents: dict[str, Any],
        relationships: list[CrossDocumentRelationship],
    ) -> str:
        """Generate a brief summary."""
        parts = [f"Análisis de {len(documents)} documentos"]
        for key, doc in documents.items():
            fields = self._get_field_names(doc)
            form = ""
            if hasattr(doc, 'form_proposal') and doc.form_proposal:
                form = getattr(doc.form_proposal, 'form_name', '')
            parts.append(
                f"- {key}: {form or 'sin nombre'} "
                f"({len(fields)} campos, {self._get_row_count(doc)} registros)"
            )
        parts.append(f"\nRelaciones detectadas: {len(relationships)}")
        for rel in relationships:
            parts.append(
                f"- {rel.source_doc} ↔ {rel.target_doc}: "
                f"{rel.relationship_type} ({rel.confidence:.0%} confianza)"
            )
        return "\n".join(parts)

    def _suggest_actions(
        self,
        relationships: list[CrossDocumentRelationship],
        inconsistencies: list[str],
    ) -> list[str]:
        """Suggest actions based on analysis."""
        actions = []
        if inconsistencies:
            actions.append(f"Revisar {len(inconsistencies)} inconsistencia(s) entre documentos")
            actions.append("Conciliar valores conflictivos antes de continuar")
        if relationships:
            high_conf = [r for r in relationships if r.confidence >= 0.8]
            if high_conf:
                actions.append(
                    f"Automatizar relación entre {len(high_conf)} par(es) de documentos "
                    "con alta confianza"
                )
        actions.append("Crear formularios para los documentos analizados")
        actions.append("Configurar importación automática de datos")
        return actions

    def _suggest_automations(
        self,
        relationships: list[CrossDocumentRelationship],
    ) -> list[str]:
        """Suggest automations."""
        automations = []
        for rel in relationships:
            if rel.relationship_type == "matches" and rel.confidence > 0.8:
                automations.append(
                    f"Auto-relacionar '{rel.source_doc}' con '{rel.target_doc}' "
                    "en futuras importaciones"
                )
            if rel.relationship_type == "references":
                automations.append(
                    f"Crear campo de relación entre '{rel.source_doc}' "
                    f"y '{rel.target_doc}'"
                )
        return automations

    def _calculate_quality(
        self,
        documents: dict[str, Any],
        relationships: list[CrossDocumentRelationship],
    ) -> float:
        """Calculate overall quality score."""
        if not documents:
            return 0.0
        doc_scores = []
        for doc in documents.values():
            score = getattr(doc, 'quality_score', None)
            if score and hasattr(score, 'overall'):
                doc_scores.append(score.overall)
            else:
                doc_scores.append(0.5)
        avg_doc_score = sum(doc_scores) / len(doc_scores) if doc_scores else 0.0
        rel_score = sum(r.confidence for r in relationships) / len(relationships) if relationships else 0.0
        return avg_doc_score * 0.6 + rel_score * 0.4

    def _get_field_names(self, doc: Any) -> list[str]:
        """Get field names from a pipeline result."""
        names = []
        if hasattr(doc, 'form_proposal') and doc.form_proposal and hasattr(doc.form_proposal, 'fields'):
            for f in (doc.form_proposal.fields or []):
                if hasattr(f, 'name'):
                    names.append(f.name)
        if hasattr(doc, 'extracted_doc') and doc.extracted_doc and hasattr(doc.extracted_doc, 'columns'):
            names.extend(doc.extracted_doc.columns or [])
        return list(set(names))

    def _get_field_value(self, doc: Any, field_name: str) -> str:
        """Get a sample value for a field."""
        if hasattr(doc, 'extracted_doc') and doc.extracted_doc and hasattr(doc.extracted_doc, 'rows'):
            rows = doc.extracted_doc.rows or []
            columns = doc.extracted_doc.columns or []
            if rows and columns:
                try:
                    idx = columns.index(field_name)
                    if isinstance(rows[0], (list, tuple)) and idx < len(rows[0]):
                        return str(rows[0][idx])
                except (ValueError, IndexError):
                    pass
                if isinstance(rows[0], dict):
                    return str(rows[0].get(field_name, ''))
        return ""

    def _get_row_count(self, doc: Any) -> int:
        """Get row count."""
        if hasattr(doc, 'extracted_doc') and doc.extracted_doc and hasattr(doc.extracted_doc, 'rows'):
            return len(doc.extracted_doc.rows or [])
        return 0

    def _get_doc_type(self, doc: Any) -> str:
        """Get document type."""
        if hasattr(doc, 'classification') and doc.classification and hasattr(doc.classification, 'document_type'):
            return doc.classification.document_type
        return "unknown"


# ======================================================================
# MultiDocumentPipeline
# ======================================================================

class MultiDocumentPipeline:
    """
    Pipeline for processing MULTIPLE documents together (FASE 10).

    Usage:
        pipeline = MultiDocumentPipeline()
        result = pipeline.run([
            DocumentInput(file_path="/tmp/factura.pdf", file_name="factura.pdf"),
            DocumentInput(file_path="/tmp/orden_compra.xlsx", file_name="orden.xlsx"),
        ])
        print(result.relationships)
        print(result.inconsistencies)

    Architecture:
      - Each document goes through the standard DocumentIntelligencePipeline
      - Then CrossDocumentAnalyzer finds relationships across all documents
      - Results are combined into a single MultiDocumentResult
    """

    def __init__(self, provider: Optional[BaseAIProvider] = None):
        self.provider = provider or get_provider()
        DIP, _, _ = _get_pipeline_classes()
        self.doc_pipeline = DIP(provider=self.provider)
        self.cross_analyzer = CrossDocumentAnalyzer(provider=self.provider)

    def run(
        self,
        documents: list[DocumentInput],
        auto_create_forms: bool = True,
        use_cache: bool = True,
    ) -> MultiDocumentResult:
        """
        Process multiple documents and find cross-document relationships.
        """
        import time
        t0 = time.perf_counter()

        if not documents:
            return MultiDocumentResult(
                success=False,
                warnings=["No se proporcionaron documentos"],
            )

        _, PC, PR = _get_pipeline_classes()

        # Step 1: Process each document individually
        doc_results: dict[str, Any] = {}
        for doc_input in documents:
            key = doc_input.file_name or Path(doc_input.file_path).name
            try:
                config = PC(
                    file_path=doc_input.file_path,
                    file_name=doc_input.file_name or Path(doc_input.file_path).name,
                    user_id=doc_input.user_id,
                    use_cache=use_cache,
                    auto_create_form=auto_create_forms,
                )
                result = self.doc_pipeline.run(config)
                doc_results[key] = result
                logger.info(
                    "Multi-doc: '%s' → %s (%.0fms)",
                    key,
                    "OK" if getattr(result, 'success', False) else "FAIL",
                    getattr(result, 'processing_time_ms', 0),
                )
            except Exception as e:
                logger.warning("Multi-doc: '%s' failed: %s", key, e)
                doc_results[key] = PR(success=False, errors=[str(e)])

        if not doc_results:
            return MultiDocumentResult(
                success=False,
                warnings=["Ningún documento pudo ser procesado"],
                processing_time_ms=(time.perf_counter() - t0) * 1000,
            )

        # Step 2: Cross-document analysis
        multi_result: MultiDocumentResult
        successful = {k: v for k, v in doc_results.items() if getattr(v, 'success', False)}

        if len(successful) >= 2:
            multi_result = self.cross_analyzer.analyze(successful, use_cache=use_cache)
            multi_result.documents = doc_results
        else:
            multi_result = MultiDocumentResult(
                success=True,
                documents=doc_results,
                warnings=["Se necesitan al menos 2 documentos exitosos para análisis cruzado"],
            )

        # Step 3: Audit
        for doc in doc_results.values():
            log_id = getattr(doc, 'analysis_log_id', None)
            if log_id:
                multi_result.analysis_log_ids.append(log_id)

        multi_result.processing_time_ms = (time.perf_counter() - t0) * 1000
        return multi_result

    def run_from_configs(
        self,
        configs: list[Any],
        use_cache: bool = True,
    ) -> MultiDocumentResult:
        """Process multiple documents from PipelineConfig list."""
        doc_inputs = [
            DocumentInput(file_path=cfg.file_path, file_name=cfg.file_name, user_id=cfg.user_id)
            for cfg in configs
        ]
        return self.run(doc_inputs, use_cache=use_cache)
