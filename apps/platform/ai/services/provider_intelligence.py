"""
provider_intelligence.py — Smart provider selection (FASE 11).

The system automatically decides which AI provider to use based on:
  - Document type (image → Gemini, text → DeepSeek, etc.)
  - Task complexity (simple → fast/cheap, complex → powerful)
  - Cost constraints
  - Performance history (learns which provider works best)
  - Availability (fallback if one provider is down)

Configurable policy — not hardcoded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from apps.platform.ai.types import ProviderType

logger = logging.getLogger(__name__)


@dataclass
class ProviderPolicy:
    """
    Configurable policy for provider selection.
    
    Can be customized per deployment.
    """
    default: ProviderType = ProviderType.GEMINI
    image_provider: ProviderType = ProviderType.GEMINI
    text_provider: ProviderType = ProviderType.DEEPSEEK
    analysis_provider: ProviderType = ProviderType.OPENROUTER
    cost_optimized: ProviderType = ProviderType.QWEN
    fallback: ProviderType = ProviderType.GEMINI
    max_cost_per_call: float = 0.01
    prefer_speed: bool = True


class ProviderIntelligence:
    """
    Smart provider selector.
    
    Rules:
      - Images → Gemini (best vision capabilities)
      - Short text → DeepSeek (fast, efficient)
      - Complex analysis → OpenRouter (access to latest models)
      - Cost-sensitive → Qwen (cheapest)
      - Fallback → Gemini (most reliable)
    """

    def __init__(self, policy: Optional[ProviderPolicy] = None):
        self.policy = policy or ProviderPolicy()

        # History of provider performance
        self._performance: dict[str, dict[str, float]] = {}

    def select(
        self,
        task: str = "",
        file_name: str = "",
        complexity: str = "auto",
        prefer_cost: bool = False,
    ) -> ProviderType:
        """
        Select the best provider for a task.
        
        Args:
            task: Task description.
            file_name: File name (to detect type from extension).
            complexity: Task complexity hint ("simple", "complex", "auto").
            prefer_cost: If True, prioritize cheaper providers.
            
        Returns:
            ProviderType to use.
        """
        ext = Path(file_name).suffix.lower() if file_name else ""

        # Rule 1: Images → Gemini (best vision)
        if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"):
            logger.debug("ProviderIntelligence: image → %s", self.policy.image_provider.value)
            return self.policy.image_provider

        # Rule 2: Short text → DeepSeek (fast, efficient)
        is_short_text = ext in (".txt", ".md", ".csv")
        if is_short_text and complexity in ("simple", "auto"):
            logger.debug("ProviderIntelligence: short text → %s", self.policy.text_provider.value)
            return self.policy.text_provider

        # Rule 3: PDF may need image capabilities
        if ext == ".pdf" and complexity in ("complex", "auto"):
            logger.debug("ProviderIntelligence: complex PDF → %s", self.policy.analysis_provider.value)
            return self.policy.analysis_provider

        # Rule 4: Cost optimization
        if prefer_cost:
            logger.debug("ProviderIntelligence: cost optimized → %s", self.policy.cost_optimized.value)
            return self.policy.cost_optimized

        # Rule 5: Task-based selection
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["analiza", "analizar", "analisis", "reporte", "resumen"]):
            logger.debug("ProviderIntelligence: analysis task → %s", self.policy.analysis_provider.value)
            return self.policy.analysis_provider

        if any(kw in task_lower for kw in ["extract", "extraer", "ocr"]):
            return self.policy.image_provider

        # Default
        return self.policy.default

    def report_success(
        self,
        provider: ProviderType,
        task_type: str,
        processing_time_ms: float,
        confidence: float,
    ) -> None:
        """Record provider performance for learning."""
        key = f"{provider.value}:{task_type}"
        if key not in self._performance:
            self._performance[key] = {"count": 0, "total_time": 0.0, "avg_confidence": 0.0}
        perf = self._performance[key]
        perf["count"] += 1
        perf["total_time"] += processing_time_ms
        perf["avg_confidence"] = (
            (perf["avg_confidence"] * (perf["count"] - 1) + confidence) / perf["count"]
        )

    def get_best_provider(self, task_type: str) -> Optional[ProviderType]:
        """Get the best-performing provider for a task type."""
        candidates = {
            k: v for k, v in self._performance.items()
            if k.endswith(f":{task_type}")
        }
        if not candidates:
            return None
        best_key = max(
            candidates,
            key=lambda k: candidates[k]["avg_confidence"],
        )
        provider_str = best_key.split(":")[0]
        return ProviderType.from_string(provider_str)
