"""
prompt_composer.py — Intelligent prompt composer (FASE 5).

Unifies prompts from multiple sources:
  - PromptManager templates (.md files)
  - ContextBuilder context
  - System rules
  - Examples from memory
  - Task-specific instructions

Validates size and splits automatically if exceeds token limits.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from apps.platform.ai.exceptions import InvalidPromptError
from apps.platform.ai.services.context_builder import AIContext
from apps.platform.ai.services.prompt_manager import PromptManager, get_prompt_manager

logger = logging.getLogger(__name__)


class PromptComposer:
    """
    Composes complete prompts from templates, context, and rules.
    
    Pipeline:
      1. Load base prompt template
      2. Add system rules
      3. Add context (from ContextBuilder)
      4. Add examples (from memory)
      5. Add task-specific instructions
      6. Validate total size
      7. Split if exceeds token limit
    """

    # Approximate: 1 token ≈ 4 chars (conservative for Spanish)
    CHARS_PER_TOKEN = 3
    MAX_TOKENS = 12000
    MAX_TOKENS_PER_CHUNK = 6000

    def __init__(self, prompt_manager: Optional[PromptManager] = None):
        self.pm = prompt_manager or get_prompt_manager()

    def compose(
        self,
        task: str,
        context: AIContext,
        prompt_name: str = "",
        system_rules: Optional[list[str]] = None,
        examples: Optional[list[dict[str, Any]]] = None,
        additional_text: str = "",
    ) -> str:
        """
        Compose a complete prompt from components.
        
        Args:
            task: The task description.
            context: Prepared AI context.
            prompt_name: Optional prompt template name.
            system_rules: Optional list of system rules.
            examples: Optional few-shot examples.
            additional_text: Any additional text to append.
            
        Returns:
            Complete prompt string.
            
        Raises:
            InvalidPromptError: If prompt exceeds max size and cannot be split.
        """
        parts: list[str] = []

        # 1. Base prompt template
        if prompt_name:
            try:
                template = self.pm.render(prompt_name, task=task)
                parts.append(template)
            except InvalidPromptError:
                logger.warning("Prompt '%s' not found, using fallback", prompt_name)

        # 2. Task description
        parts.append(f"## Tarea\n{task}")

        # 3. System rules
        if system_rules:
            rules_text = "\n".join(f"- {rule}" for rule in system_rules)
            parts.append(f"## Reglas\n{rules_text}")

        # 4. Context
        context_text = self._format_context(context)
        if context_text:
            parts.append(f"## Contexto\n{context_text}")

        # 5. Examples
        if examples:
            examples_text = self._format_examples(examples)
            parts.append(f"## Ejemplos\n{examples_text}")

        # 6. Additional text
        if additional_text:
            parts.append(additional_text)

        # Combine and validate
        prompt = "\n\n".join(parts)
        estimated_tokens = len(prompt) // self.CHARS_PER_TOKEN

        if estimated_tokens > self.MAX_TOKENS:
            logger.warning(
                "Prompt too large: ~%d tokens (max %d). Truncating context.",
                estimated_tokens, self.MAX_TOKENS,
            )
            prompt = self._truncate(prompt)

        return prompt

    def compose_for_tool(
        self,
        tool_name: str,
        context: AIContext,
        task_specific: str = "",
    ) -> str:
        """
        Compose a prompt specifically for a tool.
        
        Uses tool-specific rules and smaller context.
        """
        system_rules = self._get_tool_rules(tool_name)
        return self.compose(
            task=task_specific or f"Ejecutar {tool_name}",
            context=context,
            prompt_name=tool_name,
            system_rules=system_rules,
        )

    def _format_context(self, context: AIContext) -> str:
        """Format AI context as readable text."""
        lines = []

        if context.document_info:
            doc = context.document_info
            lines.append(f"📄 Documento: {doc.get('file_name', 'desconocido')}")
            lines.append(f"   Tipo: {doc.get('type', 'desconocido')}")
            lines.append(f"   Filas: {doc.get('rows', 0)}, Columnas: {doc.get('columns', 0)}")
            if doc.get("sample"):
                lines.append(f"   Muestra:\n{doc['sample'][:1000]}")

        if context.form_info:
            form = context.form_info
            lines.append(f"📋 Formulario: {form.get('name', 'nuevo')}")
            lines.append(f"   Campos: {form.get('total_fields', 0)}")

        if context.catalogs:
            for cat in context.catalogs[:3]:
                opts = cat.get("options", [])[:5]
                lines.append(f"📑 Catálogo '{cat.get('column', '')}': {', '.join(opts)}")

        if context.memory:
            lines.append(f"🧠 Memoria aplicada: {list(context.memory.keys())[:5]}")

        return "\n".join(lines)

    def _format_examples(self, examples: list[dict[str, Any]]) -> str:
        """Format few-shot examples."""
        lines = []
        for i, example in enumerate(examples[:3]):
            lines.append(f"--- Ejemplo {i + 1} ---")
            for k, v in example.items():
                lines.append(f"{k}: {str(v)[:200]}")
        return "\n".join(lines)

    def _get_tool_rules(self, tool_name: str) -> list[str]:
        """Get system rules for a specific tool."""
        rules_map = {
            "ocr": [
                "Extrae TODO el texto visible en la imagen",
                "Preserva la estructura de tablas si existe",
                "Responde en español colombiano",
            ],
            "field_detector": [
                "Detecta el tipo más específico posible",
                "Prioriza tipos numéricos sobre texto genérico",
                "Marca como identificador campos que parecen únicos",
            ],
            "form_generator": [
                "Genera nombres descriptivos en español",
                "Agrupa campos relacionados",
                "Sugiere identificador principal si hay un campo candidato",
            ],
            "report": [
                "Sé conciso y ejecutivo",
                "Destaca anomalías y riesgos",
                "Incluye KPIs medibles",
            ],
        }
        return rules_map.get(tool_name, [])

    def _truncate(self, prompt: str, max_chars: Optional[int] = None) -> str:
        """Truncate prompt intelligently, keeping beginning and end."""
        max_c = max_chars or (self.MAX_TOKENS * self.CHARS_PER_TOKEN)
        if len(prompt) <= max_c:
            return prompt

        # Keep first 60% and last 40%
        first_len = int(max_c * 0.6)
        last_len = max_c - first_len - 100
        return prompt[:first_len] + "\n\n...[context truncated]...\n\n" + prompt[-last_len:]
