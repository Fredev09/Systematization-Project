"""
memory_learner.py — Learns from user decisions over time.

When a user renames a field (e.g., "Valor" → "Precio"), the MemoryLearner
remembers this for future analyses. It's a continuous learning system.

Backed by MappingMemory for form mapping persistence and
a lightweight local SQLite/JSON store for field renaming patterns.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from django.conf import settings

from apps.platform.document_intelligence.extractors.base import ExtractedDocument
from apps.platform.document_intelligence.services.auto_form_creator import FormCreationProposal
from apps.platform.document_intelligence.services.structure_detector import DocumentClassification

logger = logging.getLogger(__name__)


class MemoryLearner:
    """
    Learns from user decisions for continuous improvement.

    Stores:
      - Field renames: original_name → user_corrected_name
      - Type corrections: field_name → corrected_type
      - Form naming: source_type → preferred_form_name
    """

    def __init__(self):
        self.memory_dir = Path(getattr(
            settings, "AI_MEMORY_DIR",
            Path(settings.BASE_DIR) / ".ai_memory"
        ))
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._field_renames: dict[str, str] = {}
        self._type_corrections: dict[str, str] = {}
        self._form_names: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """Load memories from disk."""
        renames_file = self.memory_dir / "field_renames.json"
        types_file = self.memory_dir / "type_corrections.json"
        names_file = self.memory_dir / "form_names.json"

        for f, attr in [
            (renames_file, "_field_renames"),
            (types_file, "_type_corrections"),
            (names_file, "_form_names"),
        ]:
            if f.exists():
                try:
                    setattr(self, attr, json.loads(f.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to load %s: %s", f.name, e)

    def _save(self) -> None:
        """Save all memories to disk."""
        for fname, attr in [
            ("field_renames.json", "_field_renames"),
            ("type_corrections.json", "_type_corrections"),
            ("form_names.json", "_form_names"),
        ]:
            path = self.memory_dir / fname
            try:
                path.write_text(
                    json.dumps(getattr(self, attr), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as e:
                logger.warning("Failed to save %s: %s", fname, e)

    # ── Aprendizaje completo (FASE 9) ──

    def learn_field_rename(self, original_name: str, corrected_name: str) -> None:
        """Remember that a user renamed a field."""
        if original_name != corrected_name:
            self._field_renames[original_name.lower().strip()] = corrected_name
            self._save()
            logger.info("MemoryLearner: rename '%s' → '%s'", original_name, corrected_name)

    def learn_type_correction(self, field_name: str, corrected_type: str) -> None:
        """Remember that a user changed a field type.

        NEVER stores 'relacion' — the AI cannot reliably distinguish
        between business codes and Registro IDs. Relations must be
        created manually by the user. 'relacion' is automatically
        converted to 'codigo'.
        """
        if corrected_type == 'relacion':
            logger.warning("MemoryLearner: ignoring 'relacion' correction for '%s' (converted to 'codigo')", field_name)
            corrected_type = 'codigo'
        self._type_corrections[field_name.lower().strip()] = corrected_type
        self._save()
        logger.info("MemoryLearner: type '%s' → '%s'", field_name, corrected_type)

    def learn_form_name(self, source_type: str, form_name: str) -> None:
        """Remember the preferred form name for a document type."""
        self._form_names[source_type.lower().strip()] = form_name
        self._save()
        logger.info("MemoryLearner: form name '%s' → '%s'", source_type, form_name)

    def learn_identifier(
        self,
        form_name: str,
        field_name: str,
    ) -> None:
        """Learn which field is the identifier for a form type."""
        key = f"{form_name.lower().strip()}:identifier"
        self._field_renames[key] = field_name
        self._save()
        logger.info("MemoryLearner: identifier '%s' → %s", form_name, field_name)

    def learn_catalog_options(
        self,
        field_name: str,
        options: list[str],
    ) -> None:
        """Learn catalog options for a field."""
        key = f"catalog:{field_name.lower().strip()}"
        self._type_corrections[key] = ",".join(sorted(options))
        self._save()
        logger.info("MemoryLearner: catalog '%s': %d options", field_name, len(options))

    def learn_field_order(
        self,
        form_name: str,
        field_names: list[str],
    ) -> None:
        """Learn the field order the user chose."""
        key = f"{form_name.lower().strip()}:order"
        self._form_names[key] = "|||".join(field_names)
        self._save()
        logger.info("MemoryLearner: order '%s': %d fields", form_name, len(field_names))

    def learn_validation_pattern(
        self,
        field_name: str,
        validation_type: str,
    ) -> None:
        """Learn that a field needs a specific validation (regex, min, max, etc)."""
        key = f"validation:{field_name.lower().strip()}"
        self._type_corrections[key] = validation_type
        self._save()
        logger.info("MemoryLearner: validation '%s': %s", field_name, validation_type)

    # ── Apply learned knowledge ──

    def suggest_rename(self, original_name: str) -> Optional[str]:
        """Suggest a field rename based on past corrections."""
        return self._field_renames.get(original_name.lower().strip())

    def suggest_type(self, field_name: str) -> Optional[str]:
        """Suggest a field type based on past corrections.

        NEVER returns 'relacion' — the AI cannot reliably distinguish
        between business codes and Registro IDs. Relations must be
        created manually by the user.
        """
        raw = self._type_corrections.get(field_name.lower().strip())
        if raw == 'relacion':
            return 'codigo'
        return raw

    def suggest_form_name(self, source_type: str) -> Optional[str]:
        """Suggest a form name based on past usage."""
        return self._form_names.get(source_type.lower().strip())

    def suggest_identifier(self, form_name: str) -> Optional[str]:
        """Suggest identifier field for a form."""
        key = f"{form_name.lower().strip()}:identifier"
        return self._field_renames.get(key)

    def suggest_catalog_options(self, field_name: str) -> Optional[list[str]]:
        """Suggest catalog options for a field."""
        key = f"catalog:{field_name.lower().strip()}"
        val = self._type_corrections.get(key)
        if val:
            return [o.strip() for o in val.split(",") if o.strip()]
        return None

    def suggest_field_order(self, form_name: str) -> Optional[list[str]]:
        """Suggest field order for a form."""
        key = f"{form_name.lower().strip()}:order"
        val = self._form_names.get(key)
        if val:
            return [f.strip() for f in val.split("|||") if f.strip()]
        return None

    def apply_to_proposal(self, proposal: FormCreationProposal) -> FormCreationProposal:
        """Apply ALL learned corrections to a form proposal."""
        if not proposal.fields:
            return proposal

        has_changes = False
        for field in proposal.fields:
            # Apply rename suggestions
            suggested = self.suggest_rename(field.name)
            if suggested:
                field.name = suggested
                field.explanation += f" (recordado)"
                has_changes = True

            # Apply type suggestions
            type_suggested = self.suggest_type(field.name)
            if type_suggested:
                field.suggested_type = type_suggested
                field.explanation += f" (tipo recordado)"
                has_changes = True

        # Apply form name suggestion
        if proposal.source_document:
            name_suggested = self.suggest_form_name(Path(proposal.source_document).suffix)
            if name_suggested:
                proposal.form_name = name_suggested

        # Suggest identifier
        if proposal.form_name:
            id_suggested = self.suggest_identifier(proposal.form_name)
            if id_suggested:
                proposal.identifier_field = id_suggested
                for f in proposal.fields:
                    if f.name.lower() == id_suggested.lower():
                        f.is_identifier = True

        # Suggest field order
        if proposal.form_name:
            order = self.suggest_field_order(proposal.form_name)
            if order:
                name_to_field = {f.name: f for f in proposal.fields}
                ordered = []
                for name in order:
                    if name in name_to_field:
                        ordered.append(name_to_field[name])
                # Add fields not in remembered order at the end
                existing_names = {f.name for f in ordered}
                for f in proposal.fields:
                    if f.name not in existing_names:
                        ordered.append(f)
                if len(ordered) == len(proposal.fields):
                    proposal.fields = ordered
                    has_changes = True

        if has_changes:
            logger.info("MemoryLearner: applied corrections to proposal")

        return proposal
