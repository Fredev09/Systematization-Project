"""
prompt_versioning.py — Smart Prompt Optimizer (F7) + Prompt Versioning (F8), v4.0 FREE-FIRST.

F7 — Smart Prompt Optimizer:
  - Elimina contexto innecesario
  - Comprime ejemplos largos
  - Reutiliza contexto compartido
  - Reduce tokens al mínimo necesario

F8 — Prompt Versioning:
  - Cada prompt tiene: versión, fecha, rendimiento
  - Métricas: accuracy, tokens promedio, success rate
  - Permite rollback a versiones anteriores
  - Persistencia en disco

FREE-FIRST: Menos tokens = menos llamadas = menos consumo de API gratuita.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from django.conf import settings

from apps.platform.ai.services.context_builder import AIContext
from apps.platform.ai.services.prompt_manager import PromptManager, get_prompt_manager

logger = logging.getLogger(__name__)


# ======================================================================
# Prompt Version Record (FASE 8)
# ======================================================================

@dataclass
class PromptVersion:
    """Registro de una versión de prompt con métricas."""
    name: str
    version: str
    content: str
    tokens_avg: int = 0
    success_rate: float = 0.0
    accuracy: float = 0.0
    runs: int = 0
    author: str = ""
    created_at: str = ""
    parent_version: str = ""
    notes: str = ""


# ======================================================================
# Prompt Optimizer (FASE 7)
# ======================================================================

class PromptOptimizer:
    """
    Optimizador automático de prompts.

    Reduce tokens eliminando:
      - Contexto irrelevante
      - Ejemplos demasiado largos
      - Instrucciones redundantes
      - Whitespace innecesario

    Usage:
        optimizer = PromptOptimizer()
        optimized = optimizer.optimize(prompt, max_tokens=2000)
    """

    CHARS_PER_TOKEN = 3

    def optimize(
        self,
        prompt: str,
        max_tokens: int = 4000,
    ) -> str:
        """
        Optimiza un prompt para reducir tokens.

        Args:
            prompt: Prompt original.
            max_tokens: Máximo de tokens permitido.

        Returns:
            Prompt optimizado.
        """
        if not prompt:
            return prompt

        original_tokens = len(prompt) // self.CHARS_PER_TOKEN
        if original_tokens <= max_tokens:
            return prompt  # Ya está dentro del límite

        result = prompt

        # 1. Eliminar whitespace excesivo
        result = self._compress_whitespace(result)

        # 2. Comprimir ejemplos (dejar solo 2 en vez de 5+)
        result = self._compress_examples(result)

        # 3. Eliminar instrucciones redundantes
        result = self._remove_redundant_instructions(result)

        # 4. Acortar contexto de documento
        result = self._shorten_context(result)

        # 5. Truncar si aún excede
        estimated = len(result) // self.CHARS_PER_TOKEN
        if estimated > max_tokens:
            result = self._truncate_intelligently(result, max_tokens)

        saved = original_tokens - (len(result) // self.CHARS_PER_TOKEN)
        if saved > 0:
            logger.info("PromptOptimizer: ahorró ~%d tokens (%d → %d)", saved, original_tokens, original_tokens - saved)

        return result

    def _compress_whitespace(self, text: str) -> str:
        """Comprime whitespace excesivo."""
        # Múltiples saltos de línea → máximo 2
        text = re.sub(r'\n{3,}', '\n\n', text)
        # Espacios múltiples → 1
        text = re.sub(r'[ \t]{2,}', ' ', text)
        # Espacios al final de línea
        text = re.sub(r' +\n', '\n', text)
        return text.strip()

    def _compress_examples(self, text: str) -> str:
        """Reduce número de ejemplos a máximo 2."""
        # Detectar secciones de ejemplo
        example_patterns = [
            (r'(---\s*Ejemplo\s*\d+\s*---)', 2),
            (r'(#\s*Ejemplo\s*\d+)', 2),
            (r'(##\s*Example\s*\d+)', 2),
        ]

        for pattern, max_examples in example_patterns:
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            if len(matches) > max_examples:
                # Mantener solo primeros N ejemplos
                keep_until = matches[max_examples - 1].end()
                # Encontrar el siguiente match o fin del texto
                if max_examples < len(matches):
                    remove_from = matches[max_examples].start()
                    # Buscar el final de la sección de ejemplos
                    text = text[:keep_until] + "\n\n[Ejemplos adicionales omitidos para ahorrar tokens]\n" + text[remove_from:]

        return text

    def _remove_redundant_instructions(self, text: str) -> str:
        """Elimina instrucciones redundantes."""
        redundancies = [
            r'Responde ÚNICAMENTE con JSON válido\.?',
            r'Responde en español colombiano\.?',
            r'Responde en español\.?',
            r'Sé conciso y ejecutivo\.?',
        ]
        for pattern in redundancies:
            # Solo eliminar si aparece más de una vez
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            if len(matches) > 1:
                for m in reversed(matches[1:]):
                    text = text[:m.start()] + text[m.end():]
        return text

    def _shorten_context(self, text: str) -> str:
        """Acorta secciones de contexto de documento."""
        # Detectar secciones grandes de contenido
        content_match = re.search(
            r'(?:---\s*(?:CONTENIDO|CONTENT|DATA|TEXTO)\s*---)\n(.+?)(?:\n(?:---|##|\Z))',
            text, re.DOTALL | re.IGNORECASE,
        )
        if content_match:
            content = content_match.group(1)
            if len(content) > 3000:
                shortened = content[:1500] + "\n\n...[contenido truncado para ahorrar tokens]...\n\n" + content[-500:]
                text = text[:content_match.start(1)] + shortened + text[content_match.end(1):]
        return text

    def _truncate_intelligently(self, text: str, max_tokens: int) -> str:
        """Truncamiento inteligente: mantiene inicio y final."""
        max_chars = max_tokens * self.CHARS_PER_TOKEN
        if len(text) <= max_chars:
            return text
        first = int(max_chars * 0.6)
        last = max_chars - first - 100
        return text[:first] + "\n\n...[truncado por límite de tokens]...\n\n" + text[-last:]


# ======================================================================
# Prompt Version Manager (FASE 8)
# ======================================================================

class PromptVersionManager:
    """
    Gestiona versiones de prompts con métricas de rendimiento.

    Cada prompt tiene:
      - Versión (semver)
      - Contenido completo
      - Métricas: accuracy, tokens promedio, success rate
      - Historial de cambios

    Usage:
        pvm = PromptVersionManager()
        version = pvm.save_version("ocr", "v1.0", "Extrae todo el texto...")
        pvm.record_run("ocr", "v1.0", success=True, tokens=500, confidence=0.9)
        best = pvm.get_best_version("ocr")
    """

    def __init__(self):
        self.prompt_manager = get_prompt_manager()
        self._versions_dir = self._get_versions_dir()
        self._versions: dict[str, list[PromptVersion]] = {}
        self._load_all()

    def _get_versions_dir(self) -> Path:
        base = getattr(settings, "BASE_DIR", Path.cwd())
        vdir = Path(base) / "apps" / "platform" / "ai" / "prompts" / "versions"
        vdir.mkdir(parents=True, exist_ok=True)
        return vdir

    def _load_all(self) -> None:
        """Carga todas las versiones desde disco."""
        for path in self._versions_dir.glob("*.json"):
            try:
                name = path.stem
                data = json.loads(path.read_text(encoding="utf-8"))
                self._versions[name] = [PromptVersion(**v) for v in data]
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("PromptVersioning: error loading %s: %s", path.name, e)

    def _save_version_file(self, name: str) -> None:
        """Guarda versiones de un prompt a disco."""
        path = self._versions_dir / f"{name}.json"
        versions = self._versions.get(name, [])
        try:
            path.write_text(
                json.dumps([v.__dict__ for v in versions], ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("PromptVersioning: error saving %s: %s", name, e)

    def save_version(
        self,
        name: str,
        version: str,
        content: str,
        author: str = "",
        notes: str = "",
        parent_version: str = "",
    ) -> PromptVersion:
        """
        Guarda una nueva versión de un prompt.

        Args:
            name: Nombre del prompt.
            version: Versión (ej: "v1.0", "v2.1").
            content: Contenido del prompt.
            author: Autor del cambio.
            notes: Notas del cambio.
            parent_version: Versión anterior (para rollback).

        Returns:
            PromptVersion creada.
        """
        if name not in self._versions:
            self._versions[name] = []

        pv = PromptVersion(
            name=name,
            version=version,
            content=content,
            author=author,
            created_at=datetime.now().isoformat(),
            parent_version=parent_version or (self._versions[name][-1].version if self._versions[name] else ""),
            notes=notes,
        )
        self._versions[name].append(pv)
        self._save_version_file(name)
        logger.info("PromptVersioning: '%s' v%s guardada", name, version)
        return pv

    def get_version(self, name: str, version: str) -> Optional[PromptVersion]:
        """Obtiene una versión específica de un prompt."""
        for v in self._versions.get(name, []):
            if v.version == version:
                return v
        return None

    def get_latest_version(self, name: str) -> Optional[PromptVersion]:
        """Obtiene la última versión de un prompt."""
        versions = self._versions.get(name, [])
        return versions[-1] if versions else None

    def get_all_versions(self, name: str) -> list[PromptVersion]:
        """Obtiene todas las versiones de un prompt."""
        return list(self._versions.get(name, []))

    def record_run(
        self,
        name: str,
        version: str,
        success: bool,
        tokens: int = 0,
        confidence: float = 0.0,
    ) -> None:
        """
        Registra una ejecución de un prompt para acumular métricas.

        Args:
            name: Nombre del prompt.
            version: Versión usada.
            success: Si la ejecución fue exitosa.
            tokens: Tokens consumidos.
            confidence: Confianza del resultado.
        """
        pv = self.get_version(name, version)
        if not pv:
            return

        pv.runs += 1
        pv.tokens_avg = int((pv.tokens_avg * (pv.runs - 1) + tokens) / pv.runs) if tokens else pv.tokens_avg
        if success:
            pv.success_rate = ((pv.success_rate * (pv.runs - 1)) + 1) / pv.runs
        else:
            pv.success_rate = (pv.success_rate * (pv.runs - 1)) / pv.runs
        pv.accuracy = (pv.accuracy * (pv.runs - 1) + confidence) / pv.runs if confidence else pv.accuracy

        self._save_version_file(name)

    def get_best_version(self, name: str) -> Optional[PromptVersion]:
        """Obtiene la versión con mejor rendimiento."""
        versions = self._versions.get(name, [])
        if not versions:
            return None
        return max(versions, key=lambda v: (v.success_rate * 0.5 + v.accuracy * 0.3 - (v.tokens_avg / 10000) * 0.2))

    def rollback(self, name: str, version: str) -> Optional[PromptVersion]:
        """
        Revierte a una versión anterior.

        Crea una NUEVA versión con el contenido de la versión solicitada.

        Args:
            name: Nombre del prompt.
            version: Versión a la que revertir.

        Returns:
            Nueva versión creada (contenido = versión anterior).
        """
        target = self.get_version(name, version)
        if not target:
            return None

        latest = self.get_latest_version(name)
        new_version = f"{version}-rollback"
        if latest:
            # Incrementar versión: v1.0 → v1.1-rollback
            parts = latest.version.split(".")
            if len(parts) == 2:
                new_version = f"{parts[0]}.{int(parts[1]) + 1}-rollback"

        return self.save_version(
            name=name,
            version=new_version,
            content=target.content,
            author="system",
            notes=f"Rollback a {version}",
            parent_version=version,
        )

    def compare_versions(self, name: str, v1: str, v2: str) -> dict[str, Any]:
        """Compara métricas entre dos versiones."""
        pv1 = self.get_version(name, v1)
        pv2 = self.get_version(name, v2)
        if not pv1 or not pv2:
            return {"error": "Version not found"}

        return {
            "name": name,
            "v1": v1,
            "v2": v2,
            "tokens_diff": pv2.tokens_avg - pv1.tokens_avg,
            "success_rate_diff": round(pv2.success_rate - pv1.success_rate, 3),
            "accuracy_diff": round(pv2.accuracy - pv1.accuracy, 3),
            "better": (
                "v2" if (pv2.success_rate + pv2.accuracy) > (pv1.success_rate + pv1.accuracy)
                else "v1" if (pv1.success_rate + pv1.accuracy) > (pv2.success_rate + pv2.accuracy)
                else "equal"
            ),
        }


# ======================================================================
# Singletons
# ======================================================================

_default_optimizer: Optional[PromptOptimizer] = None
_default_version_manager: Optional[PromptVersionManager] = None


def get_prompt_optimizer() -> PromptOptimizer:
    global _default_optimizer
    if _default_optimizer is None:
        _default_optimizer = PromptOptimizer()
    return _default_optimizer


def get_prompt_version_manager() -> PromptVersionManager:
    global _default_version_manager
    if _default_version_manager is None:
        _default_version_manager = PromptVersionManager()
    return _default_version_manager
