"""
context_builder.py — Intelligent context builder (FASE 4).

Builds the minimal, relevant context for AI calls.
Only includes information that is actually needed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from apps.platform.ai.tools.base import ExecutionContext
from apps.platform.ai.types import FieldType

logger = logging.getLogger(__name__)


@dataclass
class AIContext:
    """
    Prepared context ready for AI consumption.
    
    Built by ContextBuilder from the ExecutionContext.
    Contains ONLY what is relevant for the current task.
    """
    document_info: dict[str, Any] = field(default_factory=dict)
    form_info: Optional[dict[str, Any]] = None
    field_types: list[dict[str, Any]] = field(default_factory=list)
    existing_records: Optional[list[dict[str, Any]]] = None
    catalogs: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    corrections: list[dict[str, Any]] = field(default_factory=list)
    total_chars: int = 0


class ContextBuilder:
    """
    Builds minimal, relevant AI context from the execution environment.
    
    Rules:
      - Only include what's needed for the current task
      - Truncate large texts to configurable limits
      - Exclude sensitive/irrelevant data
      - Optimize for token usage
    """

    MAX_RAW_TEXT_CHARS = 15000
    MAX_FIELD_DESCRIPTIONS = 5000
    MAX_EXAMPLE_ROWS = 5
    MAX_CATALOG_OPTIONS = 20

    def build(self, context: ExecutionContext) -> AIContext:
        """Build context from execution context."""
        ai_ctx = AIContext()

        # Document info (minimal)
        ai_ctx.document_info = self._build_document_info(context)

        # Form info if available
        if context.form_proposal:
            ai_ctx.form_info = self._build_form_info(context)

        # Field types (always useful)
        ai_ctx.field_types = self._build_field_types(context)

        # Existing records (only if querying)
        if context.config.get("include_records"):
            ai_ctx.existing_records = self._build_existing_records(context)

        # Catalogs from session
        ai_ctx.catalogs = context.session_store.get("di_catalog_suggestions", [])

        # Memory context
        ai_ctx.memory = context.memory_data

        ai_ctx.total_chars = sum(
            len(str(v)) for v in ai_ctx.__dict__.values() if isinstance(v, (str, dict, list))
        )

        return ai_ctx

    def _build_document_info(self, context: ExecutionContext) -> dict[str, Any]:
        """Build minimal document info."""
        info = {
            "file_name": context.file_name or "",
            "type": Path(context.file_name or "").suffix.lower() if context.file_name else "",
            "rows": len(context.extracted_data.get("rows", [])),
            "columns": len(context.extracted_data.get("columns", [])),
        }
        raw = context.raw_text or ""
        if raw:
            info["sample"] = raw[:self.MAX_RAW_TEXT_CHARS]
            info["total_chars"] = len(raw)
        return info

    def _build_form_info(self, context: ExecutionContext) -> dict[str, Any]:
        """Build form proposal info."""
        proposal = context.form_proposal or {}
        return {
            "name": proposal.get("form_name", ""),
            "description": proposal.get("form_description", "")[:500],
            "total_fields": len(proposal.get("fields", [])),
        }

    def _build_field_types(self, context: ExecutionContext) -> list[dict[str, Any]]:
        """Build field type reference."""
        return [
            {"code": ft.value, "label": ft.name}
            for ft in FieldType
        ]

    def _build_existing_records(self, context: ExecutionContext) -> Optional[list[dict[str, Any]]]:
        """Build sample of existing records for context."""
        if not context.form_id:
            return None
        try:
            from apps.platform.dynamic_forms.models import Registro, ValorCampo
            recent = Registro.objects.filter(
                formulario_id=context.form_id
            ).order_by("-fecha_creacion")[:5]
            records = []
            for r in recent:
                vals = {
                    vc.campo.nombre: vc.valor
                    for vc in r.valores.select_related("campo").all()
                }
                records.append(vals)
            return records
        except Exception:
            return None
