"""
relationship_detector.py — Detects entity relationships in documents.

Analyzes columns and data to discover parent-child relationships
between entities. Example: Factura → Detalle Factura → Productos.

Always asks for user confirmation before creating relationships.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.document_intelligence.extractors.base import (
    ExtractedDocument,
)
from apps.platform.document_intelligence.services.auto_form_creator import (
    FormCreationProposal,
)
from apps.platform.document_intelligence.services.structure_detector import (
    DocumentClassification,
)

logger = logging.getLogger(__name__)


@dataclass
class RelationshipProposal:
    """A proposed relationship between forms."""
    parent_form: str = ""
    child_form: str = ""
    relationship_type: str = ""  # "one_to_many", "many_to_many"
    parent_field: str = ""
    child_field: str = ""
    confidence: float = 0.0
    explanation: str = ""
    requires_user_action: bool = True


class RelationshipDetector:
    """
    Detects relationships between entities in documents.

    Heuristic-based: looks for common foreign key patterns
    (e.g., "cliente_id" in a sales table → "Clientes" form).
    """

    def __init__(self, provider: Optional[BaseAIProvider] = None):
        self.provider = provider

    def detect(
        self,
        extracted_doc: ExtractedDocument,
        classification: Optional[DocumentClassification] = None,
        form_proposal: Optional[FormCreationProposal] = None,
        use_cache: bool = True,
    ) -> RelationshipProposal:
        """
        Detect potential relationships.

        Args:
            extracted_doc: Extracted document.
            classification: Document type classification.
            form_proposal: Form creation proposal (if any).
            use_cache: Whether to use cached AI results.

        Returns:
            RelationshipProposal or None if no relationship detected.
        """
        if not extracted_doc.columns:
            return RelationshipProposal()

        # Look for foreign key patterns in column names
        columns_lower = [h.lower().strip() for h in extracted_doc.columns]

        # Known entity relationships
        known_entities = {
            "cliente": ("Clientes", "id"),
            "producto": ("Productos", "id"),
            "proveedor": ("Proveedores", "id"),
            "vendedor": ("Vendedores", "id"),
            "categoria": ("Categorías", "id"),
            "usuario": ("Usuarios", "id"),
        }

        for col_lower in columns_lower:
            for key, (form_name, field) in known_entities.items():
                if key in col_lower or col_lower.startswith(key) or col_lower.endswith(key):
                    return RelationshipProposal(
                        parent_form=form_name,
                        child_form=form_proposal.form_name if form_proposal else "",
                        relationship_type="many_to_one",
                        parent_field=field,
                        child_field=extracted_doc.columns[columns_lower.index(col_lower)],
                        confidence=0.8,
                        explanation=f"'{col_lower}' likely references '{form_name}'",
                        requires_user_action=True,
                    )

        # Look for ID fields that suggest relationships
        for col in extracted_doc.columns:
            col_lower = col.lower().strip()
            if col_lower.endswith("_id") or col_lower.endswith(" id"):
                base_name = col_lower.replace("_id", "").replace(" id", "").strip()
                if base_name:
                    suggested_form = base_name.capitalize()
                    return RelationshipProposal(
                        parent_form=suggested_form,
                        child_form=form_proposal.form_name if form_proposal else "",
                        relationship_type="many_to_one",
                        parent_field="id",
                        child_field=col,
                        confidence=0.6,
                        explanation=f"Field '{col}' suggests a relationship to '{suggested_form}'",
                        requires_user_action=True,
                    )

        return RelationshipProposal()
