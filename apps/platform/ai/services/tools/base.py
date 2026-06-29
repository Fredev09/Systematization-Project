from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from apps.platform.ai.services.tools.result import ToolContext, ToolResult


class BaseTool(ABC):
    """
    Abstract base for all executable tools.

    Every tool defines:
      - name: unique identifier  (e.g. "search_forms")
      - description: human-readable purpose
      - requires_confirmation: whether destructive operations need confirmation
      - dry_run_supported: whether preview is supported

    Subclasses implement:
      - can_execute(intent): check if this tool matches the given intent
      - execute(ctx, params): perform the operation and return ToolResult
    """

    name: str = ""
    description: str = ""
    requires_confirmation: bool = False
    dry_run_supported: bool = False

    def can_execute(self, intent: Any) -> bool:
        """
        Determine if this tool can handle the given ChatIntent.

        Override in subclass. Default returns False.
        """
        return False

    def execute(self, ctx: ToolContext, params: dict[str, Any]) -> ToolResult:
        """
        Execute the tool.

        Override in subclass.

        Args:
            ctx: ToolContext with user, request, session, intent.
            params: Tool-specific parameters.

        Returns:
            ToolResult — never raises.
        """
        raise NotImplementedError

    def dry_run(self, ctx: ToolContext, params: dict[str, Any]) -> ToolResult:
        """
        Preview execution without side effects.

        Override if the tool supports dry_run_supported=True.
        Default calls execute() and marks the result as dry_run.
        """
        t0 = time.perf_counter()
        result = self.execute(ctx, params)
        result.execution_time_ms = (time.perf_counter() - t0) * 1000
        result.dry_run = True
        result.dry_run_summary = result.summary
        return result
