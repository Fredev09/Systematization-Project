"""
base.py — Base types for the Tool Registry.

Every tool in the system implements BaseTool and provides a ToolSpec.
The AgentOrchestrator uses ExecutionContext to pass state between tools.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from apps.platform.ai.types import AIResponse, ProviderConfig


# ======================================================================
# Tool Specification — metadata descriptor for each tool
# ======================================================================

@dataclass
class ToolSpec:
    """
    Metadata descriptor for a tool.
    
    The AgentOrchestrator uses this to decide which tools to use
    for a given task without knowing the implementation.
    """
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    expected_output: str = ""
    estimated_cost: float = 0.0
    estimated_time_ms: int = 1000
    category: str = "general"
    requires_provider: bool = True
    requires_file: bool = False
    requires_db: bool = False
    version: str = "1.0.0"


# ======================================================================
# Tool Result — standard output from every tool
# ======================================================================

@dataclass
class ToolResult:
    """
    Standard result from any tool execution.
    
    Every tool returns this — never raises.
    The ConfidenceEngine uses the confidence score to decide
    if the result needs human review or retry.
    """
    success: bool
    data: Any = None
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    processing_time_ms: float = 0.0
    tool_name: str = ""
    next_actions: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_reliable(self) -> bool:
        """Result is reliable enough to use without review."""
        return self.success and self.confidence >= 0.7


# ======================================================================
# Execution Context — state passed between tools
# ======================================================================

@dataclass
class ExecutionContext:
    """
    Execution context passed through the entire pipeline.
    
    Tools read from and write to this context.
    The AgentOrchestrator manages the lifecycle.
    """
    task: str = ""
    task_type: str = ""
    file_path: Optional[str] = None
    file_name: str = ""
    user_id: Optional[int] = None
    form_id: Optional[int] = None

    # AI Provider
    provider: Any = None
    provider_config: Optional[ProviderConfig] = None

    # Data
    raw_text: str = ""
    extracted_data: dict[str, Any] = field(default_factory=dict)
    fields: list[dict[str, Any]] = field(default_factory=list)
    form_proposal: Optional[dict[str, Any]] = None
    similar_forms: list[dict[str, Any]] = field(default_factory=list)

    # Results from previous tools
    previous_results: list[ToolResult] = field(default_factory=list)

    # Configuration
    use_cache: bool = True
    auto_create: bool = True
    auto_import: bool = False
    config: dict[str, Any] = field(default_factory=dict)

    # Memory
    memory_data: dict[str, Any] = field(default_factory=dict)

    # Session store for cross-request state
    session_store: dict[str, Any] = field(default_factory=dict)


# ======================================================================
# Base Tool — abstract interface for all tools
# ======================================================================

class BaseTool(ABC):
    """
    Abstract base for all AI tools.
    
    Subclasses MUST define:
      - spec: ToolSpec class attribute
    
    Subclasses MUST implement:
      - execute(context) -> ToolResult
    """

    spec: ToolSpec = ToolSpec(name="base", description="Base tool")

    @abstractmethod
    def execute(self, context: ExecutionContext) -> ToolResult:
        """
        Execute the tool with given context.
        
        NEVER raises — always returns ToolResult.
        Use result.success to check for errors.
        """
        ...

    def _measure(self, context: ExecutionContext) -> tuple[float, ToolResult]:
        """
        Execute with timing measurement.
        Returns (start_time, result).
        """
        t0 = time.perf_counter()
        try:
            result = self.execute(context)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return t0, ToolResult(
                success=False,
                data=None,
                confidence=0.0,
                errors=[f"Tool '{self.spec.name}' failed: {e}"],
                processing_time_ms=elapsed,
                tool_name=self.spec.name,
            )
        elapsed = (time.perf_counter() - t0) * 1000
        result.tool_name = self.spec.name
        result.processing_time_ms = elapsed
        return t0, result

    def __repr__(self) -> str:
        return f"<{self.spec.name} v{self.spec.version}>"
