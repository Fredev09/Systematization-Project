"""
smart_learner.py — SmartLearner: MemoryLearner v2 (FASE 9).

Evolves MemoryLearner from only remembering field mappings to
remembering EVERYTHING that improves future AI analysis:

  - Types corrected
  - Names corrected
  - Identifiers
  - Catalogs (options)
  - Relationships
  - Validations
  - Hidden fields
  - Preferred order
  - Similar forms
  - Prompts that worked best
  - AI provider that got best results

All this feeds future executions to be progressively better.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from django.conf import settings

logger = logging.getLogger(__name__)


# ======================================================================
# Data Classes
# ======================================================================

@dataclass
class ProviderPerformance:
    """Performance record for an AI provider on a specific task type."""
    provider: str
    task_type: str
    runs: int = 0
    avg_confidence: float = 0.0
    avg_time_ms: float = 0.0
    last_used: str = ""
    success_rate: float = 1.0

    def record(self, confidence: float, time_ms: float, success: bool) -> None:
        """Record a new execution result."""
        self.runs += 1
        self.avg_confidence = (
            (self.avg_confidence * (self.runs - 1) + confidence) / self.runs
        )
        self.avg_time_ms = (
            (self.avg_time_ms * (self.runs - 1) + time_ms) / self.runs
        )
        self.last_used = datetime.now().isoformat()
        if not success:
            self.success_rate = (
                (self.success_rate * (self.runs - 1)) / self.runs
            )


@dataclass
class PromptPerformance:
    """Performance record for a prompt template / strategy."""
    prompt_name: str
    task_type: str
    runs: int = 0
    avg_confidence: float = 0.0
    avg_tokens: int = 0
    improvements: list[str] = field(default_factory=list)


@dataclass
class FieldPreference:
    """
    User preferences for a specific field.
    
    Accumulated over multiple imports/analyses.
    """
    name: str
    display_name: str = ""
    field_type: str = ""
    is_identifier: bool = False
    is_hidden: bool = False
    order: int = 0
    required: bool = False
    unique: bool = False
    catalog_options: list[str] = field(default_factory=list)
    validation_pattern: str = ""
    related_form: str = ""
    formula: str = ""


@dataclass
class FormTemplate:
    """
    Complete template for a form type.
    
    Built from user history — represents the "ideal" version
    of a form after all corrections.
    """
    name: str
    description: str = ""
    fields: list[FieldPreference] = field(default_factory=list)
    identifier_field: str = ""
    similar_to: list[str] = field(default_factory=list)
    preferred_provider: str = ""
    times_created: int = 0
    last_created: str = ""


# ======================================================================
# SmartLearner
# ======================================================================

class SmartLearner:
    """
    Comprehensive learning system for AI improvement (FASE 9).
    
    Wraps MemoryLearner and adds:
      - Provider performance tracking
      - Prompt performance tracking
      - Form templates (accumulated preferences)
      - Relationship learning
      - Validation learning
    
    Usage:
        learner = SmartLearner()
        
        # Record everything
        learner.record_provider_run("gemini", "ocr", 0.92, 1500, True)
        learner.record_field_preference("Productos", "Precio", field_type="moneda")
        
        # Get recommendations
        best = learner.get_best_provider_for("ocr")
        template = learner.get_form_template("Productos")
    """

    def __init__(self):
        from apps.platform.document_intelligence.services.memory_learner import MemoryLearner
        self.memory_learner = MemoryLearner()
        self.memory_dir = self.memory_learner.memory_dir
        
        # Extended memories
        self._provider_performance: dict[str, ProviderPerformance] = {}
        self._prompt_performance: dict[str, PromptPerformance] = {}
        self._form_templates: dict[str, FormTemplate] = {}
        self._relationship_memory: dict[str, list[str]] = {}
        self._validation_memory: dict[str, str] = {}
        self._hidden_fields: dict[str, list[str]] = {}
        
        self._load_extended()

    # ── Persistence ──

    def _load_extended(self) -> None:
        """Load extended memories from disk."""
        for fname, attr in [
            ("provider_performance.json", "_provider_performance"),
            ("prompt_performance.json", "_prompt_performance"),
            ("form_templates.json", "_form_templates"),
            ("relationship_memory.json", "_relationship_memory"),
            ("validation_memory.json", "_validation_memory"),
            ("hidden_fields.json", "_hidden_fields"),
        ]:
            path = self.memory_dir / fname
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    setattr(self, attr, data)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("SmartLearner: failed to load %s: %s", fname, e)

    def _save_all(self) -> None:
        """Save all extended memories to disk."""
        for fname, attr in [
            ("provider_performance.json", "_provider_performance"),
            ("prompt_performance.json", "_prompt_performance"),
            ("form_templates.json", "_form_templates"),
            ("relationship_memory.json", "_relationship_memory"),
            ("validation_memory.json", "_validation_memory"),
            ("hidden_fields.json", "_hidden_fields"),
        ]:
            path = self.memory_dir / fname
            try:
                data = getattr(self, attr)
                # Convert dataclasses to dicts for serialization
                if isinstance(data, dict) and data:
                    sample = next(iter(data.values()))
                    if hasattr(sample, '__dataclass_fields__'):
                        data = {k: v.__dict__ for k, v in data.items()}
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
            except OSError as e:
                logger.warning("SmartLearner: failed to save %s: %s", fname, e)

    # ── Provider Performance (FASE 11 integration) ──

    def record_provider_run(
        self,
        provider: str,
        task_type: str,
        confidence: float,
        time_ms: float,
        success: bool,
    ) -> None:
        """Record an AI provider execution for learning."""
        key = f"{provider}:{task_type}"
        if key not in self._provider_performance:
            self._provider_performance[key] = ProviderPerformance(
                provider=provider,
                task_type=task_type,
            ).__dict__
        
        perf = self._provider_performance[key]
        perf["runs"] += 1
        perf["avg_confidence"] = (
            (perf["avg_confidence"] * (perf["runs"] - 1) + confidence) / perf["runs"]
        )
        perf["avg_time_ms"] = (
            (perf["avg_time_ms"] * (perf["runs"] - 1) + time_ms) / perf["runs"]
        )
        perf["last_used"] = datetime.now().isoformat()
        if not success:
            perf["success_rate"] = (
                (perf["success_rate"] * (perf["runs"] - 1)) / perf["runs"]
            )
        
        self._save_all()
        logger.info(
            "SmartLearner: provider '%s' en '%s': %.0f%% confianza (%d runs)",
            provider, task_type, perf["avg_confidence"] * 100, perf["runs"],
        )

    def get_best_provider_for(self, task_type: str) -> str:
        """
        Get the best-performing provider for a task type.
        
        Returns provider name, or empty string if no data.
        """
        candidates = {
            k: v for k, v in self._provider_performance.items()
            if k.endswith(f":{task_type}")
        }
        if not candidates:
            return ""
        best_key = max(
            candidates,
            key=lambda k: candidates[k]["avg_confidence"],
        )
        return best_key.split(":")[0]

    def get_all_provider_stats(self) -> dict[str, dict[str, Any]]:
        """Get performance stats for all providers."""
        return dict(self._provider_performance)

    # ── Prompt Performance ──

    def record_prompt_run(
        self,
        prompt_name: str,
        task_type: str,
        confidence: float,
        tokens: int = 0,
        improvements: Optional[list[str]] = None,
    ) -> None:
        """Record a prompt execution for learning."""
        key = f"{prompt_name}:{task_type}"
        if key not in self._prompt_performance:
            self._prompt_performance[key] = PromptPerformance(
                prompt_name=prompt_name,
                task_type=task_type,
            ).__dict__
        
        perf = self._prompt_performance[key]
        perf["runs"] += 1
        perf["avg_confidence"] = (
            (perf["avg_confidence"] * (perf["runs"] - 1) + confidence) / perf["runs"]
        )
        if tokens:
            perf["avg_tokens"] = (
                (perf["avg_tokens"] * (perf["runs"] - 1) + tokens) / perf["runs"]
            )
        if improvements:
            perf["improvements"].extend(improvements)
        
        self._save_all()

    def get_best_prompt_for(self, task_type: str) -> str:
        """Get the best-performing prompt name for a task type."""
        candidates = {
            k: v for k, v in self._prompt_performance.items()
            if k.endswith(f":{task_type}")
        }
        if not candidates:
            return ""
        best_key = max(
            candidates,
            key=lambda k: candidates[k]["avg_confidence"],
        )
        return best_key.split(":")[0]

    # ── Field Preferences ──

    def record_field_preference(
        self,
        form_name: str,
        field_name: str,
        display_name: str = "",
        field_type: str = "",
        is_identifier: bool = False,
        is_hidden: bool = False,
        order: int = 0,
        required: bool = False,
        unique: bool = False,
        catalog_options: Optional[list[str]] = None,
        validation_pattern: str = "",
        related_form: str = "",
        formula: str = "",
    ) -> None:
        """Record a user's preference for a field within a form."""
        template = self._get_or_create_template(form_name)
        
        # Find or create field preference
        field = None
        for f in template.fields:
            if f.name.lower() == field_name.lower():
                field = f
                break
        
        if field is None:
            field = FieldPreference(name=field_name)
            template.fields.append(field)
        
        # Update with provided values (only if non-empty/non-default)
        if display_name:
            field.display_name = display_name
        if field_type:
            field.field_type = field_type
        if is_identifier:
            field.is_identifier = True
            template.identifier_field = field_name
        if is_hidden:
            field.is_hidden = True
        if order:
            field.order = order
        if required:
            field.required = True
        if unique:
            field.unique = True
        if catalog_options:
            field.catalog_options = list(set(field.catalog_options + catalog_options))
        if validation_pattern:
            field.validation_pattern = validation_pattern
        if related_form:
            field.related_form = related_form
        if formula:
            field.formula = formula
        
        self._save_extended()
        
        # Also record in MemoryLearner for backwards compatibility
        if field_type:
            self.memory_learner.learn_type_correction(field_name, field_type)
        if is_identifier:
            self.memory_learner.learn_identifier(form_name, field_name)
        if catalog_options:
            self.memory_learner.learn_catalog_options(field_name, catalog_options)

    def get_field_preference(
        self,
        form_name: str,
        field_name: str,
    ) -> Optional[FieldPreference]:
        """Get accumulated preferences for a field."""
        template = self._form_templates.get(form_name.lower().strip())
        if not template:
            return None
        for f in template.fields:
            if f.name.lower() == field_name.lower():
                return f
        return None

    def get_all_field_preferences(self, form_name: str) -> list[FieldPreference]:
        """Get all field preferences for a form."""
        template = self._get_or_create_template(form_name)
        if not template.fields:
            return []
        return sorted(template.fields, key=lambda f: f.order)

    # ── Form Templates ──

    def record_form_creation(
        self,
        form_name: str,
        description: str = "",
        fields: Optional[list[dict[str, Any]]] = None,
        similar_to: Optional[list[str]] = None,
        preferred_provider: str = "",
    ) -> None:
        """Record that a form was created with specific characteristics."""
        template = self._get_or_create_template(form_name)
        
        if description:
            template.description = description
        template.times_created += 1
        template.last_created = datetime.now().isoformat()
        
        if preferred_provider:
            template.preferred_provider = preferred_provider
        
        if similar_to:
            template.similar_to = list(set(template.similar_to + similar_to))
        
        # Record field preferences from the fields used
        if fields:
            for idx, f_data in enumerate(fields):
                fname = f_data.get("name", f_data.get("nombre", f"campo_{idx}"))
                ftype = f_data.get("suggested_type", f_data.get("tipo", "texto"))
                is_id = f_data.get("is_identifier", f_data.get("identificador", False))
                frequired = f_data.get("required", f_data.get("obligatorio", False))
                funique = f_data.get("unique", f_data.get("unico", False))
                
                self.record_field_preference(
                    form_name=form_name,
                    field_name=fname,
                    field_type=ftype,
                    is_identifier=is_id,
                    order=idx,
                    required=frequired,
                    unique=funique,
                )
        
        self._save_extended()

    def get_form_template(self, form_name: str) -> Optional[FormTemplate]:
        """Get the accumulated template for a form."""
        return self._form_templates.get(form_name.lower().strip())

    def suggest_form_from_source(self, source_type: str) -> Optional[str]:
        """Suggest a form name based on source document type."""
        # Try MemoryLearner first
        name = self.memory_learner.suggest_form_name(source_type)
        if name:
            return name
        
        # Try from templates
        ext = source_type.lower().strip()
        for tname, template in self._form_templates.items():
            if ext in template.similar_to:
                return tname
        
        return None

    # ── Relationship Memory ──

    def record_relationship(
        self,
        source_form: str,
        target_form: str,
    ) -> None:
        """Record a relationship between two forms."""
        key = source_form.lower().strip()
        if key not in self._relationship_memory:
            self._relationship_memory[key] = []
        target = target_form.lower().strip()
        if target not in self._relationship_memory[key]:
            self._relationship_memory[key].append(target)
        self._save_all()
        logger.info(
            "SmartLearner: relationship '%s' → '%s'",
            source_form, target_form,
        )

    def get_related_forms(self, form_name: str) -> list[str]:
        """Get forms related to a given form."""
        key = form_name.lower().strip()
        return self._relationship_memory.get(key, [])

    # ── Validation Memory ──

    def record_validation(
        self,
        field_name: str,
        validation_type: str,
    ) -> None:
        """Record that a field needs a specific validation."""
        self._validation_memory[field_name.lower().strip()] = validation_type
        self._save_all()
        self.memory_learner.learn_validation_pattern(field_name, validation_type)

    def suggest_validation(self, field_name: str) -> str:
        """Suggest a validation type for a field."""
        return self._validation_memory.get(field_name.lower().strip(), "")

    # ── Hidden Fields ──

    def record_hidden_field(
        self,
        form_name: str,
        field_name: str,
    ) -> None:
        """Record that a user hid a field in a form."""
        key = form_name.lower().strip()
        if key not in self._hidden_fields:
            self._hidden_fields[key] = []
        if field_name not in self._hidden_fields[key]:
            self._hidden_fields[key].append(field_name)
        self._save_all()

    def get_hidden_fields(self, form_name: str) -> list[str]:
        """Get fields the user has hidden in this form type."""
        key = form_name.lower().strip()
        return self._hidden_fields.get(key, [])

    # ── Apply to Suggestions ──

    def apply_to_fields(
        self,
        form_name: str,
        fields: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Apply ALL learned preferences to a list of fields.
        
        This is the main integration point — call this before
        showing the field editor to pre-apply all accumulated knowledge.
        """
        # Get preferences for this form
        prefs = self.get_all_field_preferences(form_name)
        pref_map = {p.name.lower(): p for p in prefs}
        
        if not pref_map:
            # Try MemoryLearner suggestions
            return self._apply_memory_learner(fields)
        
        result = []
        for field in fields:
            fname = field.get("name", field.get("nombre", ""))
            pref = pref_map.get(fname.lower())
            
            if pref:
                # Apply all accumulated preferences
                if pref.field_type:
                    field["suggested_type"] = pref.field_type
                if pref.is_identifier:
                    field["is_identifier"] = True
                if pref.is_hidden:
                    field["hidden"] = True
                if pref.required:
                    field["required"] = True
                if pref.unique:
                    field["unique"] = True
                if pref.catalog_options:
                    field["options"] = pref.catalog_options
                if pref.validation_pattern:
                    field["validation"] = pref.validation_pattern
                if pref.related_form:
                    field["related_form"] = pref.related_form
                if pref.formula:
                    field["formula"] = pref.formula
                if pref.display_name:
                    field["name"] = pref.display_name
            
            result.append(field)
        
        # Apply MemoryLearner suggestions as fallback
        result = self._apply_memory_learner(result)
        
        # Sort by preference order
        result.sort(key=lambda f: pref_map.get(f.get("name", "").lower(), FieldPreference(name="")).order)
        
        return result

    def _apply_memory_learner(
        self,
        fields: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Apply MemoryLearner suggestions as fallback."""
        result = []
        for field in fields:
            fname = field.get("name", "")
            
            # Check for renames
            suggested = self.memory_learner.suggest_rename(fname)
            if suggested:
                field["name"] = suggested
            
            # Check for type corrections
            type_suggested = self.memory_learner.suggest_type(field.get("name", fname))
            if type_suggested:
                field["suggested_type"] = type_suggested
            
            result.append(field)
        return result

    # ── Internals ──

    def _get_or_create_template(self, form_name: str) -> FormTemplate:
        """Get or create a form template."""
        key = form_name.lower().strip()
        if key not in self._form_templates:
            template_data = {
                "name": form_name,
                "description": "",
                "fields": [],
                "identifier_field": "",
                "similar_to": [],
                "preferred_provider": "",
                "times_created": 0,
                "last_created": "",
            }
            self._form_templates[key] = template_data
        
        template_data = self._form_templates[key]
        # Convert dict to FormTemplate if needed
        if isinstance(template_data, dict):
            template = FormTemplate(**template_data)
            self._form_templates[key] = template
            # Convert fields
            template.fields = [
                FieldPreference(**f) if isinstance(f, dict) else f
                for f in template.fields
            ]
        
        return self._form_templates[key]

    def _save_extended(self) -> None:
        """Save all extended memories to disk."""
        self._save_all()
