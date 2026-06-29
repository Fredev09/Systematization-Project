"""
budget_manager.py — AI Budget Manager (FASE 1, v4.0 FREE-FIRST).

Controla el consumo de APIs de IA por proveedor con límites configurables.

Características:
  - Rate limiting: requests/min, hour, day por proveedor
  - Control de tokens estimados
  - Auto-deshabilitación de proveedores al alcanzar límite
  - Persistencia en disco (JSON)
  - Integración con Provider Router y Decision Engine

Regla FREE-FIRST: los límites por defecto están ajustados para
los tiers gratuitos de Gemini, DeepSeek, OpenRouter y Qwen.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from django.conf import settings

from apps.platform.ai.types import ProviderType

logger = logging.getLogger(__name__)


# ======================================================================
# Límites por defecto para tiers gratuitos (FREE-FIRST)
# ======================================================================

_DEFAULT_LIMITS: dict[str, dict[str, int]] = {
    "gemini": {
        "requests_per_minute": 10,
        "requests_per_hour": 60,
        "requests_per_day": 300,
        "tokens_per_minute": 30000,
        "tokens_per_hour": 200000,
        "tokens_per_day": 1000000,
    },
    "deepseek": {
        "requests_per_minute": 10,
        "requests_per_hour": 100,
        "requests_per_day": 500,
        "tokens_per_minute": 50000,
        "tokens_per_hour": 500000,
        "tokens_per_day": 2000000,
    },
    "openrouter": {
        "requests_per_minute": 5,
        "requests_per_hour": 50,
        "requests_per_day": 200,
        "tokens_per_minute": 20000,
        "tokens_per_hour": 150000,
        "tokens_per_day": 500000,
    },
    "qwen": {
        "requests_per_minute": 15,
        "requests_per_hour": 200,
        "requests_per_day": 1000,
        "tokens_per_minute": 40000,
        "tokens_per_hour": 300000,
        "tokens_per_day": 1500000,
    },
}

_DEFAULT_HEURISTIC_LIMITS = {
    "requests_per_minute": 100,
    "requests_per_hour": 1000,
    "requests_per_day": 5000,
}


@dataclass
class ProviderBudget:
    """Estado del presupuesto para un proveedor en un momento dado."""
    provider: str
    enabled: bool = True
    disabled_reason: str = ""
    minute_window_start: float = 0.0
    hour_window_start: float = 0.0
    day_window_start: float = 0.0
    minute_requests: int = 0
    hour_requests: int = 0
    day_requests: int = 0
    minute_tokens: int = 0
    hour_tokens: int = 0
    day_tokens: int = 0
    total_requests: int = 0
    total_tokens: int = 0
    last_reset_minute: float = 0.0
    last_reset_hour: float = 0.0
    last_reset_day: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "disabled_reason": self.disabled_reason,
            "minute_window_start": self.minute_window_start,
            "hour_window_start": self.hour_window_start,
            "day_window_start": self.day_window_start,
            "minute_requests": self.minute_requests,
            "hour_requests": self.hour_requests,
            "day_requests": self.day_requests,
            "minute_tokens": self.minute_tokens,
            "hour_tokens": self.hour_tokens,
            "day_tokens": self.day_tokens,
            "total_requests": self.total_requests,
            "total_tokens": self.total_tokens,
            "last_reset_minute": self.last_reset_minute,
            "last_reset_hour": self.last_reset_hour,
            "last_reset_day": self.last_reset_day,
        }


class BudgetManager:
    """
    Controla el presupuesto de IA para todos los proveedores.

    Lógica de rate limiting:
      - Ventanas deslizantes por minuto, hora y día
      - Si cualquier ventana excede el límite, el proveedor se deshabilita
      - Los proveedores se re-habilitan automáticamente al reiniciar la ventana
      - Persistencia en disco para sobrevivir reinicios del servidor

    Usage:
        budget = BudgetManager()
        if budget.can_call("gemini", estimated_tokens=500):
            budget.record_call("gemini", prompt_tokens=100, completion_tokens=50)
        else:
            fallback = budget.get_available_provider(["deepseek", "qwen"])
            if fallback:
                # usar fallback
    """

    def __init__(self):
        self._limits: dict[str, dict[str, int]] = self._load_limits()
        self._budgets: dict[str, ProviderBudget] = {}
        self._lock = Lock()
        self._budget_dir = self._get_budget_dir()
        self._load_state()
        
        # Usuarios (para tracking por usuario) — in-memory only
        self._user_usage: dict[str, dict[str, int]] = {}
        
        # Documentos (para tracking por documento) — in-memory only
        self._doc_usage: dict[str, dict[str, int]] = {}

    # ── Configuración ──

    def _load_limits(self) -> dict[str, dict[str, int]]:
        """Carga límites desde settings, con valores por defecto FREE-FIRST."""
        limits = {}
        for provider, default in _DEFAULT_LIMITS.items():
            limits[provider] = dict(getattr(
                settings,
                f"AI_BUDGET_{provider.upper()}",
                default,
            ))
        limits["heuristic"] = dict(getattr(
            settings, "AI_BUDGET_HEURISTIC", _DEFAULT_HEURISTIC_LIMITS
        ))
        return limits

    def _get_budget_dir(self) -> Path:
        budget_dir = Path(getattr(
            settings, "AI_BUDGET_DIR",
            Path(settings.BASE_DIR) / ".ai_budget",
        ))
        budget_dir.mkdir(parents=True, exist_ok=True)
        return budget_dir

    def _load_state(self) -> None:
        """Carga estado persistido desde disco."""
        path = self._budget_dir / "budget_state.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for provider, state in data.items():
                    budget = ProviderBudget(**state)
                    self._budgets[provider] = budget
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("BudgetManager: error loading state: %s", e)

    def _save_state(self) -> None:
        """Persiste estado a disco."""
        path = self._budget_dir / "budget_state.json"
        try:
            data = {
                provider: budget.to_dict()
                for provider, budget in self._budgets.items()
            }
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("BudgetManager: error saving state: %s", e)

    def _get_budget(self, provider: str) -> ProviderBudget:
        """Obtiene o crea el budget para un proveedor."""
        if provider not in self._budgets:
            self._budgets[provider] = ProviderBudget(provider=provider)
        return self._budgets[provider]

    def _reset_windows(self, budget: ProviderBudget) -> None:
        """Resetea ventanas si ha pasado suficiente tiempo."""
        now = time.time()
        disabled_lower = (budget.disabled_reason or "").lower()
        if now - budget.minute_window_start > 60:
            budget.minute_requests = 0
            budget.minute_tokens = 0
            budget.minute_window_start = now
        if now - budget.hour_window_start > 3600:
            budget.hour_requests = 0
            budget.hour_tokens = 0
            budget.hour_window_start = now
        if now - budget.day_window_start > 86400:
            budget.day_requests = 0
            budget.day_tokens = 0
            budget.day_window_start = now
            if not budget.enabled and "diario" in disabled_lower:
                budget.enabled = True
                budget.disabled_reason = ""

    # ── API Pública ──

    def can_call(
        self,
        provider: str,
        estimated_tokens: int = 0,
    ) -> bool:
        """
        Verifica si un proveedor puede recibir una llamada.

        Args:
            provider: Nombre del proveedor (gemini, deepseek, etc).
            estimated_tokens: Tokens estimados para esta llamada.

        Returns:
            True si la llamada está dentro del presupuesto.
        """
        with self._lock:
            budget = self._get_budget(provider)
            self._reset_windows(budget)

            if not budget.enabled:
                logger.debug("Budget: %s disabled (%s)", provider, budget.disabled_reason)
                return False

            limits = self._limits.get(provider, _DEFAULT_LIMITS.get(provider, {}))

            # Verificar requests
            if budget.minute_requests >= limits.get("requests_per_minute", 1000):
                logger.info("Budget: %s reached minute limit", provider)
                return False
            if budget.hour_requests >= limits.get("requests_per_hour", 10000):
                logger.info("Budget: %s reached hour limit", provider)
                return False
            if budget.day_requests >= limits.get("requests_per_day", 50000):
                budget.enabled = False
                budget.disabled_reason = "Límite diario alcanzado"
                self._save_state()
                logger.info("Budget: %s DISABLED — daily limit reached", provider)
                return False

            # Verificar tokens
            if estimated_tokens > 0:
                if (budget.minute_tokens + estimated_tokens) > limits.get("tokens_per_minute", 100000):
                    return False
                if (budget.hour_tokens + estimated_tokens) > limits.get("tokens_per_hour", 1000000):
                    return False
                if (budget.day_tokens + estimated_tokens) > limits.get("tokens_per_day", 5000000):
                    return False

            return True

    def record_call(
        self,
        provider: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        user_id: Optional[int] = None,
        document_name: str = "",
    ) -> None:
        """
        Registra una llamada AI y actualiza el presupuesto.

        Args:
            provider: Proveedor usado.
            prompt_tokens: Tokens de entrada.
            completion_tokens: Tokens de salida.
            user_id: Opcional, para tracking por usuario.
            document_name: Opcional, para tracking por documento.
        """
        total_tokens = prompt_tokens + completion_tokens

        with self._lock:
            budget = self._get_budget(provider)
            budget.minute_requests += 1
            budget.hour_requests += 1
            budget.day_requests += 1
            budget.total_requests += 1
            budget.minute_tokens += total_tokens
            budget.hour_tokens += total_tokens
            budget.day_tokens += total_tokens
            budget.total_tokens += total_tokens
            self._save_state()

        # Tracking por usuario (in-memory)
        if user_id:
            uid = str(user_id)
            if uid not in self._user_usage:
                self._user_usage[uid] = {"requests": 0, "tokens": 0}
            self._user_usage[uid]["requests"] += 1
            self._user_usage[uid]["tokens"] += total_tokens

        # Tracking por documento (in-memory)
        if document_name:
            if document_name not in self._doc_usage:
                self._doc_usage[document_name] = {"requests": 0, "tokens": 0}
            self._doc_usage[document_name]["requests"] += 1
            self._doc_usage[document_name]["tokens"] += total_tokens

    def get_available_provider(
        self,
        preferences: Optional[list[str]] = None,
        estimated_tokens: int = 0,
    ) -> Optional[str]:
        """
        Encuentra un proveedor disponible dentro del presupuesto.

        Args:
            preferences: Lista ordenada de proveedores preferidos.
            estimated_tokens: Tokens estimados.

        Returns:
            Nombre del proveedor disponible, o None si todos excedieron límite.
        """
        candidates = preferences or ["deepseek", "qwen", "gemini", "openrouter"]
        for provider in candidates:
            if self.can_call(provider, estimated_tokens):
                return provider
        logger.warning("Budget: NO providers available — all limits exhausted")
        return None

    def get_status(self) -> dict[str, Any]:
        """
        Obtiene estado completo del presupuesto para dashboard/monitoreo.

        Returns:
            Dict con estado de todos los proveedores.
        """
        with self._lock:
            return {
                provider: budget.to_dict()
                for provider, budget in self._budgets.items()
            }

    def enable_provider(self, provider: str) -> None:
        """Re-habilita manualmente un proveedor."""
        with self._lock:
            budget = self._get_budget(provider)
            budget.enabled = True
            budget.disabled_reason = ""
            # Resetear ventanas
            budget.minute_requests = 0
            budget.hour_requests = 0
            budget.day_requests = 0
            budget.minute_tokens = 0
            budget.hour_tokens = 0
            budget.day_tokens = 0
            self._save_state()
            logger.info("Budget: %s manually enabled", provider)

    def disable_provider(self, provider: str, reason: str = "") -> None:
        """Deshabilita manualmente un proveedor."""
        with self._lock:
            budget = self._get_budget(provider)
            budget.enabled = False
            budget.disabled_reason = reason or "Deshabilitado manualmente"
            self._save_state()
            logger.info("Budget: %s disabled: %s", provider, reason)

    def reset_all(self) -> None:
        """Resetea todos los budgets (útil para tests)."""
        with self._lock:
            self._budgets.clear()
            self._user_usage.clear()
            self._doc_usage.clear()
            self._save_state()
            logger.info("Budget: all budgets reset")


# Singleton with double-checked locking
_default_budget: Optional[BudgetManager] = None
_singleton_lock: Lock = Lock()


def get_budget_manager() -> BudgetManager:
    """Return the default BudgetManager instance (thread-safe singleton)."""
    global _default_budget
    if _default_budget is None:
        with _singleton_lock:
            if _default_budget is None:
                _default_budget = BudgetManager()
    return _default_budget
