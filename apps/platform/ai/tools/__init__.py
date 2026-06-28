"""
tools — Intelligent Tool Registry for AI Agent.

Every tool implements BaseTool with a ToolSpec descriptor.
The AgentOrchestrator uses ToolRegistry to discover, select,
and execute tools without knowing their implementations.

Usage:
    from apps.platform.ai.tools import ToolRegistry, BaseTool

    registry = ToolRegistry()
    ocr = registry.get("ocr")
    result = ocr.execute(context)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from apps.platform.ai.tools.base import BaseTool, ExecutionContext, ToolResult, ToolSpec

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Central registry for all AI tools.

    Tools register themselves via register() or the @tool decorator.
    The AgentOrchestrator queries this registry to find tools by
    capability, name, or category.
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    # ── Registration ──

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        name = tool.spec.name
        if name in self._tools:
            logger.warning("Tool '%s' already registered. Overwriting.", name)
        self._tools[name] = tool
        logger.info("Tool registered: %s — %s", name, tool.spec.description[:60])

    def register_many(self, *tools: BaseTool) -> None:
        """Register multiple tools at once."""
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry."""
        self._tools.pop(name, None)

    # ── Query ──

    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolSpec]:
        """List all registered tool specs."""
        return [t.spec for t in self._tools.values()]

    def find_by_capability(self, keyword: str) -> list[BaseTool]:
        """Find tools whose name or description contains keyword."""
        keyword = keyword.lower()
        return [
            t for t in self._tools.values()
            if keyword in t.spec.name.lower()
            or keyword in t.spec.description.lower()
        ]

    def find_by_category(self, category: str) -> list[BaseTool]:
        """Find tools by category string."""
        return [
            t for t in self._tools.values()
            if t.spec.parameters.get("category", "") == category
        ]

    def estimate_cost(self, tool_names: list[str]) -> float:
        """Estimate total cost for executing a set of tools."""
        total = 0.0
        for name in tool_names:
            tool = self._tools.get(name)
            if tool:
                total += tool.spec.estimated_cost
        return total

    def estimate_time(self, tool_names: list[str]) -> int:
        """Estimate total processing time for a set of tools."""
        total = 0
        for name in tool_names:
            tool = self._tools.get(name)
            if tool:
                total += tool.spec.estimated_time_ms
        return total

    # ── Execute ──

    def execute(self, tool_name: str, context: ExecutionContext) -> ToolResult:
        """Execute a tool by name with given context."""
        tool = self.get(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                data=None,
                confidence=0.0,
                warnings=[f"Tool '{tool_name}' not found in registry."],
                processing_time_ms=0.0,
            )
        return tool.execute(context)

    def execute_chain(
        self,
        tool_names: list[str],
        context: ExecutionContext,
    ) -> list[ToolResult]:
        """Execute tools in sequence, passing context through."""
        results = []
        for name in tool_names:
            result = self.execute(name, context)
            results.append(result)
            if not result.success:
                break
            # Update context with last result data
            context.previous_results = results
        return results


# Global registry singleton
_default_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """Return the default ToolRegistry instance (singleton)."""
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry()
        _register_default_tools(_default_registry)
    return _default_registry


def _register_default_tools(registry: ToolRegistry) -> None:
    """Register all built-in tools."""
    from apps.platform.ai.tools.ocr_tool import OCRTool
    from apps.platform.ai.tools.document_classifier_tool import DocumentClassifierTool
    from apps.platform.ai.tools.field_detector_tool import FieldDetectorTool
    from apps.platform.ai.tools.form_generator_tool import FormGeneratorTool
    from apps.platform.ai.tools.relationship_detector_tool import RelationshipDetectorTool
    from apps.platform.ai.tools.catalog_detector_tool import CatalogDetectorTool
    from apps.platform.ai.tools.similarity_finder_tool import SimilarityFinderTool
    from apps.platform.ai.tools.import_tool import ImportTool
    from apps.platform.ai.tools.memory_tool import MemoryTool
    from apps.platform.ai.tools.report_tool import ReportTool

    registry.register_many(
        OCRTool(),
        DocumentClassifierTool(),
        FieldDetectorTool(),
        FormGeneratorTool(),
        RelationshipDetectorTool(),
        CatalogDetectorTool(),
        SimilarityFinderTool(),
        ImportTool(),
        MemoryTool(),
        ReportTool(),
    )


__all__ = [
    "BaseTool",
    "ToolRegistry",
    "ToolSpec",
    "ToolResult",
    "ExecutionContext",
    "get_registry",
]
