"""
reasoning_engine.py — Internal reasoning engine (FASE 3).

Before calling any AI provider, the ReasoningEngine analyzes:
  1. What type of document/task is this?
  2. What tools are needed?
  3. What context is relevant?
  4. What provider should handle it?
  5. What confidence threshold to expect?

This produces a ReasoningPath that guides the entire execution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from apps.platform.ai.tools.base import ExecutionContext

logger = logging.getLogger(__name__)


@dataclass
class ReasoningStep:
    """A single reasoning step in the decision chain."""
    question: str
    answer: str
    confidence: float = 1.0
    alternatives: list[str] = field(default_factory=list)


@dataclass
class ReasoningPath:
    """
    Complete reasoning path for a task.
    
    Every decision is recorded for audit and learning.
    """
    task: str
    task_type: str = ""
    document_type: str = "unknown"
    needs_ocr: bool = False
    needs_classification: bool = True
    needs_field_detection: bool = True
    needs_form_generation: bool = True
    needs_relationship_detection: bool = False
    needs_catalog_detection: bool = False
    needs_similarity_search: bool = True
    needs_import: bool = False
    needs_report: bool = False

    selected_tools: list[str] = field(default_factory=list)
    rejected_tools: list[str] = field(default_factory=list)
    suggested_provider: str = ""
    estimated_cost: float = 0.0
    estimated_time_ms: int = 0

    steps: list[ReasoningStep] = field(default_factory=list)
    confidence: float = 0.5
    warnings: list[str] = field(default_factory=list)


class ReasoningEngine:
    """
    Analyzes the task and decides what tools, context, and provider to use.
    
    No AI calls — purely heuristic + rule-based reasoning.
    AI is called AFTER the reasoning path is established.
    """

    def reason(self, context: ExecutionContext) -> ReasoningPath:
        """Produce a reasoning path for the given context."""
        path = ReasoningPath(task=context.task)

        # Step 1: Determine task type
        path.steps.append(self._step_task_type(context, path))

        # Step 2: Determine if OCR is needed
        path.steps.append(self._step_needs_ocr(context, path))

        # Step 3: Select tools
        path.steps.append(self._step_select_tools(context, path))

        # Step 4: Estimate costs
        path.steps.append(self._step_estimate_costs(context, path))

        # Step 5: Overall confidence
        path.steps.append(self._step_confidence(context, path))

        return path

    def _step_task_type(self, context: ExecutionContext, path: ReasoningPath) -> ReasoningStep:
        """Determine the type of task."""
        file_name = context.file_name or ""
        ext = Path(file_name).suffix.lower() if file_name else ""

        if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"):
            doc_type = "image"
            path.needs_ocr = True
        elif ext == ".pdf":
            doc_type = "pdf"
            path.needs_ocr = True  # PDF may need image-based OCR
        elif ext in (".xlsx", ".xls"):
            doc_type = "excel"
        elif ext == ".csv":
            doc_type = "csv"
        elif ext in (".txt", ".md", ".json", ".xml"):
            doc_type = "text"
        else:
            doc_type = "unknown"

        path.task_type = f"analyze_{doc_type}"
        path.document_type = doc_type

        return ReasoningStep(
            question="¿Qué tipo de documento es?",
            answer=f"{doc_type} (detectado por extensión {ext})",
            confidence=0.9 if doc_type != "unknown" else 0.3,
        )

    def _step_needs_ocr(self, context: ExecutionContext, path: ReasoningPath) -> ReasoningStep:
        """Determine if OCR is needed."""
        needs_ocr = path.needs_ocr
        if not needs_ocr and path.document_type in ("image", "pdf"):
            needs_ocr = True

        return ReasoningStep(
            question="¿Necesita OCR?",
            answer="Sí" if needs_ocr else "No",
            confidence=0.95,
        )

    def _step_select_tools(self, context: ExecutionContext, path: ReasoningPath) -> ReasoningStep:
        """Select the appropriate tools for this task."""
        tools = []
        rejected = []

        # Always classify
        if path.needs_classification:
            tools.append("document_classifier")
        else:
            rejected.append("document_classifier")

        # OCR if needed
        if path.needs_ocr:
            tools.append("ocr")
        else:
            rejected.append("ocr")

        # Field detection
        if path.needs_field_detection:
            tools.append("field_detector")
        else:
            rejected.append("field_detector")

        # Form generation
        if path.needs_form_generation:
            tools.append("form_generator")
        else:
            rejected.append("form_generator")

        # Memory (always apply if available)
        tools.append("memory")

        # Similarity search
        if path.needs_similarity_search:
            tools.append("similarity_finder")

        # Relationship detection (if enough fields)
        if path.needs_relationship_detection and len(context.fields) >= 3:
            tools.append("relationship_detector")

        # Catalog detection (if structured data)
        if path.needs_catalog_detection:
            tools.append("catalog_detector")

        # Import
        if path.needs_import:
            tools.append("import")

        path.selected_tools = tools
        path.rejected_tools = rejected

        return ReasoningStep(
            question="¿Qué herramientas se necesitan?",
            answer=f"{len(tools)} herramientas: {', '.join(tools)}",
            confidence=0.85,
            alternatives=[f"Sin {t}" for t in tools] if len(tools) > 3 else [],
        )

    def _step_estimate_costs(self, context: ExecutionContext, path: ReasoningPath) -> ReasoningStep:
        """Estimate costs for the selected tools."""
        from apps.platform.ai.tools import get_registry
        registry = get_registry()
        path.estimated_cost = registry.estimate_cost(path.selected_tools)
        path.estimated_time_ms = registry.estimate_time(path.selected_tools)

        return ReasoningStep(
            question="¿Cuánto costará?",
            answer=f"~${path.estimated_cost:.4f} USD, ~{path.estimated_time_ms}ms",
            confidence=0.7,
        )

    def _step_confidence(self, context: ExecutionContext, path: ReasoningPath) -> ReasoningStep:
        """Estimate overall confidence based on available data."""
        score = 0.5

        if context.file_path:
            score += 0.1
        if context.provider:
            score += 0.1
        if context.raw_text:
            score += 0.1
        if context.fields:
            score += 0.1
        if path.document_type != "unknown":
            score += 0.1

        path.confidence = min(score, 1.0)

        return ReasoningStep(
            question="¿Qué confianza tengo?",
            answer=f"{path.confidence:.0%}",
            confidence=path.confidence,
        )
