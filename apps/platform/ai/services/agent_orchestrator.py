"""
agent_orchestrator.py — Intelligent Agent Orchestrator (FASE 1).

THE single entry point for ALL intelligent processes in the platform.

Pipeline:
  1. Receive task
  2. Understand objective (ReasoningEngine)
  3. Build context (ContextBuilder)
  4. Select tools (ToolRegistry)
  5. Execute tools in sequence
  6. Validate results (ConfidenceEngine)
  7. If low confidence → retry with different strategy
  8. Learn from results (SmartLearner)
  9. Audit (AIAnalysisLog)
  10. Return final result

Completely decoupled — knows nothing about Dynamic Forms, Invoices, etc.
Only knows about tools.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from django.conf import settings

from apps.platform.ai.exceptions import AIError
from apps.platform.ai.models import AIAnalysisLog
from apps.platform.ai.providers import get_provider
from apps.platform.ai.services.context_builder import ContextBuilder, AIContext
from apps.platform.ai.services.prompt_composer import PromptComposer
from apps.platform.ai.services.reasoning_engine import ReasoningEngine, ReasoningPath
from apps.platform.ai.tools import ToolRegistry, get_registry
from apps.platform.ai.tools.base import ExecutionContext, ToolResult
from apps.platform.ai.types import ProviderConfig, ProviderType

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


@dataclass
class OrchestratorResult:
    """Complete result from the AgentOrchestrator."""
    success: bool
    reasoning: Optional[ReasoningPath] = None
    tool_results: list[ToolResult] = field(default_factory=list)
    final_data: Any = None
    confidence: float = 0.0
    processing_time_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    retries: int = 0
    audit_log_id: Optional[int] = None
    suggested_provider: str = ""


class AgentOrchestrator:
    """
    Central orchestrator for all AI-powered processes.

    Usage:
        orchestrator = AgentOrchestrator()
        result = orchestrator.execute(
            task="Analyze this document and create a form",
            file_path="/tmp/factura.pdf",
            user_id=1,
        )
        if result.success:
            print(result.final_data)
    """

    def __init__(
        self,
        provider: Optional[Any] = None,
        registry: Optional[ToolRegistry] = None,
    ):
        self.provider = provider
        self.registry = registry or get_registry()
        self.reasoning = ReasoningEngine()
        self.context_builder = ContextBuilder()
        self.prompt_composer = PromptComposer()

    def execute(
        self,
        task: str,
        file_path: Optional[str] = None,
        file_name: str = "",
        user_id: Optional[int] = None,
        form_id: Optional[int] = None,
        fields: Optional[list[dict]] = None,
        form_proposal: Optional[dict] = None,
        raw_text: str = "",
        extracted_data: Optional[dict] = None,
        config: Optional[dict] = None,
        auto_provider: bool = True,
    ) -> OrchestratorResult:
        """
        Execute a task through the complete AI pipeline.

        Args:
            task: Natural language task description.
            file_path: Path to the file to process.
            file_name: Original file name.
            user_id: User executing the task.
            form_id: Existing form ID (if any).
            fields: Pre-detected fields (if any).
            form_proposal: Pre-built form proposal (if any).
            raw_text: Pre-extracted text (if any).
            extracted_data: Pre-extracted structured data.
            config: Additional configuration.
            auto_provider: Auto-select provider based on task.

        Returns:
            OrchestratorResult with final data and metadata.
        """
        t0 = time.perf_counter()

        # ── 1. Build execution context ──
        exec_ctx = ExecutionContext(
            task=task,
            file_path=file_path,
            file_name=file_name,
            user_id=user_id,
            form_id=form_id,
            fields=fields or [],
            form_proposal=form_proposal,
            raw_text=raw_text,
            extracted_data=extracted_data or {},
            config=config or {},
            session_store={},
        )

        # ── 2. Select provider ──
        if auto_provider and not self.provider:
            exec_ctx.provider = self._select_provider(task, file_name)
        elif self.provider:
            exec_ctx.provider = self.provider

        # ── 3. Reason about the task ──
        reasoning = self.reasoning.reason(exec_ctx)
        exec_ctx.use_cache = config.get("use_cache", True) if config else True

        # ── 4. Build context ──
        ai_context = self.context_builder.build(exec_ctx)

        # ── 5. Execute tools ──
        tool_results: list[ToolResult] = []
        retries = 0
        last_result = OrchestratorResult(
            success=False,
            reasoning=reasoning,
            suggested_provider=reasoning.suggested_provider,
        )

        for attempt in range(MAX_RETRIES + 1):
            if attempt > 0:
                retries += 1
                logger.info("Retry %d for task: %s", attempt, task[:80])

            for tool_name in reasoning.selected_tools:
                try:
                    tool_result = self.registry.execute(tool_name, exec_ctx)
                except Exception as e:
                    logger.exception("Tool '%s' raised unhandled exception", tool_name)
                    tool_result = ToolResult(
                        success=False,
                        errors=[str(e)],
                        data={},
                    )
                tool_results.append(tool_result)

                if tool_result.success and tool_result.data:
                    self._update_context_from_result(exec_ctx, tool_name, tool_result)

                if not tool_result.success:
                    logger.warning(
                        "Tool '%s' failed: %s",
                        tool_name, tool_result.errors,
                    )

            # ── 6. Validate ──
            from apps.platform.ai.services.confidence_engine import ConfidenceEngine
            ce = ConfidenceEngine()
            validation = ce.validate(tool_results, reasoning)

            if validation.is_reliable:
                break

            if attempt < MAX_RETRIES:
                logger.info("Confidence too low (%s). Retrying...", validation)
                tool_results = []

        # ── 7. Build final result ──
        total_elapsed = (time.perf_counter() - t0) * 1000

        # Build last validation
        try:
            from apps.platform.ai.services.confidence_engine import ConfidenceEngine
            ce = ConfidenceEngine()
            final_validation = ce.validate(tool_results, reasoning)
            final_confidence = final_validation.overall
        except Exception:
            final_confidence = 0.5

        final_data = self._merge_results(tool_results, reasoning)

        last_result = OrchestratorResult(
            success=any(r.success for r in tool_results),
            reasoning=reasoning,
            tool_results=tool_results,
            final_data=final_data,
            confidence=final_confidence,
            processing_time_ms=total_elapsed,
            warnings=[w for r in tool_results for w in r.warnings],
            errors=[e for r in tool_results for e in r.errors],
            retries=retries,
            suggested_provider=reasoning.suggested_provider,
        )

        # ── 8. Audit ──
        try:
            log = AIAnalysisLog.log(
                provider=getattr(exec_ctx.provider, 'config', None)
                    .provider_type.value if hasattr(getattr(exec_ctx.provider, 'config', None), 'provider_type') else "unknown",
                model=getattr(exec_ctx.provider, 'config', None).model if hasattr(getattr(exec_ctx.provider, 'config', None), 'model') else "",
                service="agent_orchestrator",
                document_type=reasoning.document_type,
                document_name=file_name,
                processing_time_ms=total_elapsed,
                success=last_result.success,
                confidence=last_result.confidence,
                result_summary=f"Tools: {', '.join(reasoning.selected_tools)} | "
                              f"Confidence: {last_result.confidence:.0%}",
            )
            last_result.audit_log_id = log.id
        except Exception as e:
            logger.warning("Audit log error: %s", e)

        return last_result

    def _select_provider(
        self,
        task: str,
        file_name: str,
    ) -> Any:
        """
        Select the best provider for the task.
        
        Uses ProviderIntelligence when available, or falls back
        to the default provider from settings.
        """
        try:
            from apps.platform.ai.services.provider_intelligence import ProviderIntelligence
            selector = ProviderIntelligence()
            provider_type = selector.select(task, file_name)
        except Exception:
            provider_type = None

        return get_provider(provider_type=provider_type)

    def _update_context_from_result(
        self,
        ctx: ExecutionContext,
        tool_name: str,
        result: ToolResult,
    ) -> None:
        """Update execution context with tool results."""
        if not result.data:
            return

        if tool_name == "ocr":
            ctx.raw_text = result.data.get("raw_text", ctx.raw_text)
            ctx.extracted_data["ocr_text"] = result.data.get("raw_text", "")

        elif tool_name == "field_detector":
            ctx.fields = result.data.get("fields", ctx.fields)

        elif tool_name == "form_generator":
            ctx.form_proposal = result.data

        elif tool_name == "similarity_finder":
            ctx.similar_forms = result.data.get("similar_forms", [])

        elif tool_name == "memory":
            ctx.fields = result.data.get("fields", ctx.fields)

    def _merge_results(
        self,
        results: list[ToolResult],
        reasoning: ReasoningPath,
    ) -> dict[str, Any]:
        """Merge all tool results into a single output dict."""
        merged: dict[str, Any] = {
            "task_type": reasoning.task_type,
            "document_type": reasoning.document_type,
            "selected_tools": reasoning.selected_tools,
            "estimated_cost": reasoning.estimated_cost,
            "estimated_time_ms": reasoning.estimated_time_ms,
            "confidence": reasoning.confidence,
        }

        for r in results:
            if r.success and r.data:
                if isinstance(r.data, dict):
                    merged.update(r.data)
                else:
                    merged[r.tool_name] = r.data

        return merged


# Singleton
_default_orchestrator: Optional[AgentOrchestrator] = None


def get_orchestrator() -> AgentOrchestrator:
    """Return the default AgentOrchestrator instance (singleton)."""
    global _default_orchestrator
    if _default_orchestrator is None:
        _default_orchestrator = AgentOrchestrator()
    return _default_orchestrator
