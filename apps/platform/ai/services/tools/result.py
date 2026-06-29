from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """
    Structured result from a tool execution.

    Every tool must return this. No raw dicts, no exceptions propagated to UI.
    """
    success: bool = True
    tool: str = ""
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    error_code: str = ""

    # Confirmation workflow
    requires_confirmation: bool = False
    confirmation_token: str = ""
    confirmation_message: str = ""

    # Dry run
    dry_run: bool = False
    dry_run_summary: str = ""

    # Follow-ups the AI can suggest
    followups: list[str] = field(default_factory=list)

    # Metrics
    execution_time_ms: float = 0.0

    # Execution plan support
    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    current_step: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "tool": self.tool,
            "summary": self.summary,
            "details": self.details,
            "error": self.error,
            "error_code": self.error_code,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_token": self.confirmation_token,
            "confirmation_message": self.confirmation_message,
            "dry_run": self.dry_run,
            "dry_run_summary": self.dry_run_summary,
            "followups": self.followups,
            "execution_time_ms": round(self.execution_time_ms, 1),
            "plan_steps": self.plan_steps,
            "current_step": self.current_step,
        }


@dataclass
class ToolContext:
    """
    Context passed to every tool execution.

    Carries user, request, session, and system references.
    """
    user: Any = None
    request: Any = None
    session: dict[str, Any] = field(default_factory=dict)
    intent: Any = None
    execution_plan: list[dict[str, Any]] = field(default_factory=list)
    dry_run: bool = False
    confirmation_token: str = ""

    def make_confirmation_token(self) -> str:
        token = uuid.uuid4().hex[:16]
        self.confirmation_token = token
        if self.session is not None:
            self.session[f"tool_confirmation_{token}"] = {
                "tool": "",
                "params": {},
                "dry_run_result": None,
                "confirmed": False,
            }
        return token

    def confirm_action(self, token: str) -> bool:
        if self.session is None:
            return False
        key = f"tool_confirmation_{token}"
        entry = self.session.get(key)
        if entry is None:
            return False
        entry["confirmed"] = True
        self.session[key] = entry
        return True

    def is_confirmed(self, token: str) -> bool:
        if self.session is None:
            return False
        entry = self.session.get(f"tool_confirmation_{token}")
        return entry is not None and entry.get("confirmed", False)

    def store_dry_run_result(self, token: str, tool_name: str, params: dict, result: ToolResult):
        if self.session is None:
            return
        key = f"tool_confirmation_{token}"
        entry = self.session.get(key)
        if entry is not None:
            entry["tool"] = tool_name
            entry["params"] = params
            entry["dry_run_result"] = result.to_dict()
            self.session[key] = entry
