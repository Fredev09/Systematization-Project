from __future__ import annotations

import logging
from typing import Any, Optional

from apps.platform.ai.services.tools.base import BaseTool
from apps.platform.ai.services.tools.registry import ToolRegistry
from apps.platform.ai.services.tools.result import ToolContext, ToolResult

logger = logging.getLogger(__name__)


class ToolResolver:
    """
    Resolves a ChatIntent to the best matching tool.

    Flow:
      1. If intent already specifies a tool_name, use it directly.
      2. Otherwise, iterate registry and call can_execute(intent).
      3. Return the first match.

    Usage:
        resolver = ToolResolver()
        tool, params = resolver.resolve(intent)
    """

    def __init__(self):
        self.registry = ToolRegistry.get_instance()
        self.registry.discover()

    def resolve(self, intent: Any) -> tuple[Optional[BaseTool], dict[str, Any]]:
        """
        Resolve a ChatIntent to the best tool + extracted params.

        Returns:
            (BaseTool | None, params_dict)
        """
        tool = None
        params: dict[str, Any] = {}

        # 1. Direct tool name from intent
        if hasattr(intent, "tool_name") and intent.tool_name:
            tool = self.registry.get_tool(intent.tool_name)
            if tool:
                params["intent"] = intent
                return tool, params

        # 2. Try alias from intent
        if hasattr(intent, "form_alias") and intent.form_alias:
            params["form_alias"] = intent.form_alias
            params["form_filter"] = intent.form_alias

        # 3. Pass sub_intent and other params
        if hasattr(intent, "sub_intent") and intent.sub_intent:
            params["sub_intent"] = intent.sub_intent
        if hasattr(intent, "target_model") and intent.target_model:
            params["target_model"] = intent.target_model
        if hasattr(intent, "params"):
            for k, v in intent.params.items():
                params[k] = v

        # 4. Find by can_execute
        tool = self.registry.find_tool(intent)

        return tool, params
