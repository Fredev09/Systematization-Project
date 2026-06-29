"""
ai_dashboard.py — AI Dashboard Service (FASE 11, v4.0 FREE-FIRST).

Servicio que consolida estadísticas de:
  - Proveedores (requests, errores, fallbacks)
  - Cache (hit/miss rate, ahorro de tokens)
  - Budget (consumo por proveedor, tokens)
  - Documentos (analizados, OCRs realizados)
  - SmartLearner (proveedor más usado, rendimiento)

Sin dependencias de UI — consume cualquier frontend.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.platform.ai.models import AIAnalysisLog
from apps.platform.ai.services.budget_manager import get_budget_manager
from apps.platform.ai.services.multi_level_cache import MultiLevelCache, get_multi_level_cache
from apps.platform.ai.services.smart_learner import SmartLearner

logger = logging.getLogger(__name__)


@dataclass
class AIDashboardData:
    """Datos completos del dashboard AI."""
    period_days: int = 30

    # Proveedores
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    cached_calls: int = 0
    avg_time_ms: float = 0.0
    by_provider: dict[str, int] = field(default_factory=dict)

    # Tokens
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    estimated_cost_usd: float = 0.0

    # Cache
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_rate: float = 0.0
    cache_by_level: dict[str, dict] = field(default_factory=dict)

    # Budget
    budget_status: dict[str, Any] = field(default_factory=dict)

    # SmartLearner
    best_providers: dict[str, str] = field(default_factory=dict)
    top_services: list[tuple[str, int]] = field(default_factory=list)

    # Tendencias
    daily_trend: list[dict[str, Any]] = field(default_factory=list)
    errors_trend: list[dict[str, Any]] = field(default_factory=list)

    # Resumen
    documents_analyzed: int = 0
    ocr_performed: int = 0
    most_used_provider: str = ""
    estimated_savings_usd: float = 0.0


class AIDashboardService:
    """
    Servicio que recolecta y consolida estadísticas de toda la plataforma AI.

    Usage:
        dashboard = AIDashboardService()
        data = dashboard.get_data(days=30)
        print(data.total_calls, data.cache_hit_rate)
    """

    def __init__(self):
        self.budget = get_budget_manager()
        self.cache = get_multi_level_cache()
        self.smart_learner = SmartLearner()

    def get_data(self, days: int = 30) -> AIDashboardData:
        """
        Obtiene datos consolidados del dashboard.

        Args:
            days: Período en días hacia atrás.

        Returns:
            AIDashboardData con todas las estadísticas.
        """
        data = AIDashboardData(period_days=days)
        since = timezone.now() - timedelta(days=days)

        # 1. Estadísticas de AIAnalysisLog
        self._load_analysis_stats(data, since)

        # 2. Estadísticas de caché
        self._load_cache_stats(data)

        # 3. Estado del budget
        self._load_budget_stats(data)

        # 4. SmartLearner
        self._load_learner_stats(data)

        # 5. Tendencias diarias
        self._load_trends(data, since)

        # 6. Resumen
        self._build_summary(data)

        return data

    def _load_analysis_stats(self, data: AIDashboardData, since: datetime) -> None:
        """Carga estadísticas desde AIAnalysisLog."""
        qs = AIAnalysisLog.objects.filter(created_at__gte=since)
        total = qs.count()

        data.total_calls = total
        data.successful_calls = qs.filter(success=True).count()
        data.failed_calls = total - data.successful_calls
        data.cached_calls = qs.filter(cached=True).count()
        data.avg_time_ms = qs.aggregate(avg=Avg("processing_time_ms"))["avg"] or 0.0

        # Tokens
        tokens = qs.aggregate(
            prompt=Sum("prompt_tokens"),
            completion=Sum("completion_tokens"),
            cost=Sum("estimated_cost_usd"),
        )
        data.total_prompt_tokens = tokens["prompt"] or 0
        data.total_completion_tokens = tokens["completion"] or 0
        data.estimated_cost_usd = float(tokens["cost"] or 0.0)

        # Por proveedor
        by_prov = qs.values_list("provider").annotate(count=Count("id"))
        data.by_provider = dict(by_prov)

        # Por servicio
        by_service = qs.values_list("service").annotate(count=Count("id")).order_by("-count")[:10]
        data.top_services = [(s, c) for s, c in by_service if s]

        # Documentos únicos
        data.documents_analyzed = qs.values("document_name").distinct().count()

        # OCRs
        data.ocr_performed = qs.filter(service="ocr").count()

    def _load_cache_stats(self, data: AIDashboardData) -> None:
        """Carga estadísticas del multi-level cache."""
        stats = self.cache.get_stats()
        data.cache_hits = stats["total_hits"]
        data.cache_misses = stats["total_misses"]
        data.cache_hit_rate = stats["hit_rate"]
        data.cache_by_level = stats["by_level"]

    def _load_budget_stats(self, data: AIDashboardData) -> None:
        """Carga estado del budget manager."""
        data.budget_status = self.budget.get_status()

    def _load_learner_stats(self, data: AIDashboardData) -> None:
        """Carga estadísticas del SmartLearner."""
        provider_stats = self.smart_learner.get_all_provider_stats()
        best = {}
        for key, stat in provider_stats.items():
            provider, task_type = key.split(":", 1)
            if task_type not in best or stat["avg_confidence"] > best[task_type][1]:
                best[task_type] = (provider, stat["avg_confidence"])
        data.best_providers = {k: v[0] for k, v in best.items()}

    def _load_trends(self, data: AIDashboardData, since: datetime) -> None:
        """Carga tendencias diarias."""
        qs = AIAnalysisLog.objects.filter(created_at__gte=since)

        # Diario: total calls (usando TruncDate para portabilidad entre BD)
        daily = (
            qs.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(
                total=Count("id"),
                failed=Count("id", filter=Q(success=False)),
            )
            .order_by("day")
        )
        data.daily_trend = [
            {"date": str(d["day"]), "total": d["total"], "failed": d["failed"]}
            for d in daily
        ]

        # Errores por proveedor
        errors = (
            qs.filter(success=False)
            .values("provider", "error_message")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )
        data.errors_trend = [
            {"provider": e["provider"], "error": (e["error_message"] or "")[:100], "count": e["count"]}
            for e in errors
        ]

    def _build_summary(self, data: AIDashboardData) -> None:
        """Construye resumen ejecutivo."""
        # Proveedor más usado
        if data.by_provider:
            data.most_used_provider = max(data.by_provider, key=data.by_provider.get)

        # Ahorro estimado por caché
        if data.cache_hits > 0:
            # Asumiendo ~$0.0001 por llamada AI ahorrada
            data.estimated_savings_usd = round(data.cache_hits * 0.0001, 4)

    def get_json(self, days: int = 30) -> dict[str, Any]:
        """Obtiene datos del dashboard como dict (para API JSON)."""
        data = self.get_data(days)
        return {
            "period_days": data.period_days,
            "total_calls": data.total_calls,
            "successful_calls": data.successful_calls,
            "failed_calls": data.failed_calls,
            "cached_calls": data.cached_calls,
            "avg_time_ms": round(data.avg_time_ms, 1),
            "total_prompt_tokens": data.total_prompt_tokens,
            "total_completion_tokens": data.total_completion_tokens,
            "estimated_cost_usd": data.estimated_cost_usd,
            "cache_hit_rate": data.cache_hit_rate,
            "documents_analyzed": data.documents_analyzed,
            "ocr_performed": data.ocr_performed,
            "most_used_provider": data.most_used_provider,
            "estimated_savings_usd": data.estimated_savings_usd,
            "by_provider": data.by_provider,
            "top_services": data.top_services,
            "best_providers": data.best_providers,
            "cache_by_level": {
                k: {"hits": v["hits"], "misses": v["misses"], "ttl": v["ttl_seconds"]}
                for k, v in data.cache_by_level.items()
            },
            "budget_status": {
                k: {"enabled": v.get("enabled", False), "total_requests": v.get("total_requests", 0)}
                for k, v in data.budget_status.items()
            },
        }


_default_dashboard: Optional[AIDashboardService] = None


def get_ai_dashboard() -> AIDashboardService:
    global _default_dashboard
    if _default_dashboard is None:
        _default_dashboard = AIDashboardService()
    return _default_dashboard
