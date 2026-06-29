"""
prompt_manager.py — Prompt loading and rendering system.

All AI prompts live in apps/platform/ai/prompts/ as .md files.
Services never embed prompt strings; they always use PromptManager.

Placeholders use {{variable_name}} syntax and are substituted
at render time.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

from django.conf import settings

from apps.platform.ai.exceptions import InvalidPromptError

logger = logging.getLogger(__name__)


class PromptManager:
    """
    Loads, caches, and renders prompt templates from the prompts/ directory.

    Usage:
        pm = PromptManager()
        prompt = pm.render("detect_fields", field_names="nombre, precio")
        prompt = pm.render("detect_invoice", document_type="factura")
    """

    def __init__(self, prompt_dir: Optional[Path] = None):
        self.prompt_dir = prompt_dir or self._default_prompt_dir()
        self._cache: dict[str, str] = {}

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    def render(self, prompt_name: str, **kwargs: Any) -> str:
        """
        Load a prompt template and substitute placeholders.

        Args:
            prompt_name: Name of the prompt file (without .md extension).
            **kwargs: Placeholder values to substitute.

        Returns:
            The rendered prompt string.

        Raises:
            InvalidPromptError: If the prompt file is missing or invalid.
        """
        template = self.load(prompt_name)
        try:
            return self._substitute(template, kwargs)
        except KeyError as e:
            raise InvalidPromptError(
                prompt_name,
                f"Missing placeholder: {e}",
            )

    def load(self, prompt_name: str) -> str:
        """
        Load a prompt template from disk or cache.

        Args:
            prompt_name: Name of the prompt file (without .md extension).

        Returns:
            The raw template string with {{placeholders}}.

        Raises:
            InvalidPromptError: If the file is not found.
        """
        if prompt_name in self._cache:
            return self._cache[prompt_name]

        path = self.prompt_dir / f"{prompt_name}.md"
        if not path.exists():
            raise InvalidPromptError(
                prompt_name,
                f"Prompt file not found: {path}",
            )

        try:
            template = path.read_text(encoding="utf-8")
            self._cache[prompt_name] = template
            logger.debug("Loaded prompt: %s (%d chars)", prompt_name, len(template))
            return template
        except OSError as e:
            raise InvalidPromptError(prompt_name, str(e))

    def list_prompts(self) -> list[str]:
        """List all available prompt names."""
        if not self.prompt_dir.exists():
            return []
        return sorted(
            p.stem for p in self.prompt_dir.glob("*.md")
        )

    def clear_cache(self) -> None:
        """Clear the prompt template cache (useful for tests)."""
        self._cache.clear()

    def exists(self, prompt_name: str) -> bool:
        """Check if a prompt file exists."""
        return (self.prompt_dir / f"{prompt_name}.md").exists()

    # ──────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────

    def _default_prompt_dir(self) -> Path:
        """Get the prompts/ directory path."""
        base = getattr(settings, "BASE_DIR", Path.cwd())
        return Path(base) / "apps" / "platform" / "ai" / "prompts"

    @staticmethod
    def _substitute(template: str, variables: dict[str, Any]) -> str:
        """
        Replace {{placeholders}} with values from variables dict.
        Raises KeyError if a placeholder is not found in variables.
        """

        def _replacer(match: re.Match) -> str:
            key = match.group(1).strip()
            if key not in variables:
                raise KeyError(key)
            return str(variables[key])

        return re.sub(r"\{{(\w+)}}", _replacer, template)


# Singleton
_default_pm: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    """Return the default PromptManager instance (singleton)."""
    global _default_pm
    if _default_pm is None:
        _default_pm = PromptManager()
    return _default_pm
