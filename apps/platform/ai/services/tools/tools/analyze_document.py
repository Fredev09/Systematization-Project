from __future__ import annotations

import logging
from typing import Any

from apps.platform.ai.services.tools.base import BaseTool
from apps.platform.ai.services.tools.registry import ToolRegistry
from apps.platform.ai.services.tools.result import ToolContext, ToolResult

logger = logging.getLogger(__name__)


class AnalyzeDocumentTool(BaseTool):
    name = "analyze_document"
    description = "Analizar documentos subidos (Excel, PDF, imagenes, texto)"
    dry_run_supported = False
    requires_confirmation = False

    def can_execute(self, intent: Any) -> bool:
        from apps.platform.ai.services.decision_engine import ChatIntent
        if not isinstance(intent, ChatIntent):
            return False
        if intent.intent_type == "document_question":
            return True
        q = (getattr(intent, "explanation", "") or "").lower()
        doc_kw = ["analizar", "documento", "analiza", "subir", "analisis", "resumen"]
        if any(k in q for k in doc_kw):
            return True
        return False

    def execute(self, ctx: ToolContext, params: dict[str, Any]) -> ToolResult:
        from apps.platform.ai.models import AIAnalysisLog

        user = ctx.user
        recent = AIAnalysisLog.objects.none()
        if user and user.is_authenticated:
            recent = AIAnalysisLog.objects.filter(usuario=user).order_by("-created_at")[:5]

        if recent.exists():
            lines = [f"**Ultimos {len(recent)} analisis:**"]
            for r in recent:
                status = "OK" if r.success else "FALLO"
                lines.append(f"  • {r.created_at.strftime('%Y-%m-%d %H:%M')} — {r.document_type or 'documento'} [{status}]")
            text = "\n".join(lines)
        else:
            text = "No hay analisis recientes. Sube un documento para comenzar."

        return ToolResult(
            summary=text,
            details={
                "recent_analyses": [
                    {"id": r.id, "type": r.document_type, "success": r.success, "created": str(r.created_at)}
                    for r in recent
                ] if recent.exists() else [],
            },
            followups=[
                "Sube un nuevo documento",
                "Cuantos documentos se han analizado",
                "Que proveedor IA uso",
            ],
        )


ToolRegistry.get_instance().register(AnalyzeDocumentTool())
