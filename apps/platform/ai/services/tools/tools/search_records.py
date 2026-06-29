from __future__ import annotations

import logging
from typing import Any

from apps.platform.ai.services.tools.base import BaseTool
from apps.platform.ai.services.tools.registry import ToolRegistry
from apps.platform.ai.services.tools.result import ToolContext, ToolResult

logger = logging.getLogger(__name__)


class SearchRecordsTool(BaseTool):
    name = "search_records"
    description = "Buscar, contar y listar registros en formularios"
    dry_run_supported = False
    requires_confirmation = False

    def can_execute(self, intent: Any) -> bool:
        from apps.platform.ai.services.decision_engine import ChatIntent
        if not isinstance(intent, ChatIntent):
            return False
        if intent.intent_type == "data_query":
            return True
        return False

    def execute(self, ctx: ToolContext, params: dict[str, Any]) -> ToolResult:
        from apps.platform.document_intelligence.views import _execute_safe_query

        sub = params.get("sub_intent", "list")
        model_key = params.get("target_model", "registro")

        answer = _execute_safe_query(sub, model_key, params)

        return ToolResult(
            summary=answer,
            details={
                "sub_intent": sub,
                "model_key": model_key,
                "params": {k: v for k, v in params.items() if k not in ("intent",)},
            },
            followups=[
                "¿Cuantos hay en total?",
                "Filtra por estado",
                "Exportame los resultados",
            ],
        )


ToolRegistry.get_instance().register(SearchRecordsTool())
