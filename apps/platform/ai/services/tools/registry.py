from __future__ import annotations

import logging
from typing import Any, Optional

from apps.platform.ai.services.tools.base import BaseTool
from apps.platform.ai.services.tools.result import ToolContext, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Singleton registry for all executable tools.

    Usage:
        registry = ToolRegistry.get_instance()
        registry.discover()              # auto-import all tools
        tool = registry.find_tool(intent)  # best match
        result = tool.execute(ctx, params)
    """

    _instance: Optional["ToolRegistry"] = None
    _tools: dict[str, BaseTool] = {}
    _discovered: bool = False

    def __init__(self):
        self._tools = {}
        self._discovered = False

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, tool: BaseTool) -> None:
        if not tool.name:
            logger.warning("Tool registered without name: %s", type(tool).__name__)
            return
        self._tools[tool.name] = tool
        logger.debug("Tool registered: %s — %s", tool.name, tool.description)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def discover(self) -> None:
        """
        Auto-import all tool modules. Each module registers its tool(s)
        on import via the registry singleton.
        """
        if self._discovered:
            return
        try:
            from apps.platform.ai.services.tools import tools as tools_pkg
            import importlib
            import pkgutil
            for mod_info in pkgutil.iter_modules(tools_pkg.__path__, tools_pkg.__name__ + "."):
                importlib.import_module(mod_info.name)
        except Exception as e:
            logger.warning("Tool discovery error: %s", e)
        self._discovered = True
        logger.info("Tool registry discovered %d tools", len(self._tools))

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def find_tool(self, intent: Any) -> Optional[BaseTool]:
        """
        Find the best matching tool for a given ChatIntent.

        Iterates all registered tools, calls can_execute(intent),
        returns the first match (highest-confidence tools should
        be registered first).
        """
        for tool in self._tools.values():
            try:
                if tool.can_execute(intent):
                    return tool
            except Exception as e:
                logger.warning("Tool.can_execute error for %s: %s", tool.name, e)
        return None

    def find_tools_for_plan(self, intent: Any) -> list[BaseTool]:
        """
        Find ALL matching tools for multi-step execution plans.
        """
        matches = []
        for tool in self._tools.values():
            try:
                if tool.can_execute(intent):
                    matches.append(tool)
            except Exception:
                continue
        return matches
