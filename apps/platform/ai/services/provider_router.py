"""
provider_router.py — Provider Router Inteligente (FASE 2, v4.0 FREE-FIRST).

Router automático que decide qué proveedor gratuito usar según:
  1. Tipo de tarea (OCR → Gemini, matching → DeepSeek, etc.)
  2. Disponibilidad de presupuesto (BudgetManager)
  3. Rendimiento histórico (SmartLearner)
  4. Complejidad del documento
  5. Fallback en cadena

El usuario NUNCA escoge proveedor. El sistema decide solo.

FREE-FIRST: Siempre prioriza modelos gratuitos.
Si todos los proveedores fallan, usa heurísticas locales.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from apps.platform.ai.services.budget_manager import BudgetManager, get_budget_manager
from apps.platform.ai.services.smart_learner import SmartLearner
from apps.platform.ai.types import ProviderType

logger = logging.getLogger(__name__)


# ======================================================================
# Rutas de proveedor por tipo de tarea
# ======================================================================

_TASK_ROUTES: dict[str, list[str]] = {
    # OCR complejo (imágenes, fotos, escaneos) → Gemini (mejor visión gratuita)
    "ocr": ["gemini", "openrouter", "qwen", "heuristic"],
    
    # Clasificación de documentos → DeepSeek (rápido, barato)
    "classify": ["deepseek", "qwen", "gemini", "heuristic"],
    
    # Detección de campos → DeepSeek o Qwen
    "field_detection": ["deepseek", "qwen", "gemini", "heuristic"],
    
    # Generación de formularios → Gemini (mejor para tareas complejas)
    "form_generation": ["gemini", "openrouter", "deepseek", "heuristic"],
    
    # Matching de columnas → DeepSeek (suficiente para esta tarea)
    "column_matching": ["deepseek", "qwen", "gemini", "heuristic"],
    
    # Resúmenes → Qwen (más barato, suficiente calidad)
    "summary": ["qwen", "deepseek", "gemini", "heuristic"],
    
    # Análisis de facturas → Gemini (necesita visión)
    "invoice": ["gemini", "openrouter", "deepseek", "heuristic"],
    
    # Reportes ejecutivos → DeepSeek
    "report": ["deepseek", "gemini", "qwen", "heuristic"],
    
    # Chat / preguntas → Qwen (suficiente)
    "chat": ["qwen", "deepseek", "gemini", "heuristic"],
    
    # Detección de relaciones → Gemini
    "relationship": ["gemini", "openrouter", "deepseek", "heuristic"],
    
    # Tarea genérica → probar orden por rendimiento
    "general": ["deepseek", "qwen", "gemini", "openrouter", "heuristic"],
}

# Mapa de extensiones a tipo de tarea
_EXT_TO_TASK: dict[str, str] = {
    ".jpg": "ocr", ".jpeg": "ocr", ".png": "ocr",
    ".webp": "ocr", ".gif": "ocr", ".bmp": "ocr", ".tiff": "ocr",
    ".pdf": "ocr",
    ".xlsx": "field_detection", ".xls": "field_detection",
    ".csv": "field_detection",
    ".txt": "summary", ".md": "summary",
}


@dataclass
class RouteDecision:
    """Decisión completa de ruteo de proveedor."""
    task_type: str
    selected_provider: str = ""
    fallback_chain: list[str] = field(default_factory=list)
    reason: str = ""
    used_budget: bool = False
    used_history: bool = False
    is_heuristic: bool = False
    confidence: float = 1.0


class ProviderRouter:
    """
    Router inteligente de proveedores AI.

    Decisión:
      1. Determinar tipo de tarea (OCR, classify, field_detection, etc.)
      2. Obtener ruta preferida para esa tarea
      3. Verificar presupuesto para cada proveedor en la ruta
      4. Seleccionar el primer proveedor disponible
      5. Si ninguno disponible → heurísticas locales

    Usage:
        router = ProviderRouter()
        decision = router.route(file_name="factura.pdf", task="Extraer texto")
        if not decision.is_heuristic:
            provider = get_provider(decision.selected_provider)
            result = provider.analyze_image(...)
    """

    def __init__(self):
        self.budget: BudgetManager = get_budget_manager()
        self.smart_learner = SmartLearner()

    @staticmethod
    def _check_api_key_exists(provider_name: str) -> bool:
        """
        Verifica si la API Key de un proveedor está realmente configurada.
        
        No solo verifica rate limits — verifica que la API Key existe
        en settings antes de intentar usar el proveedor.
        
        Args:
            provider_name: Nombre del proveedor (gemini, deepseek, etc).
        
        Returns:
            True si la API Key está configurada y no es vacía.
        """
        from django.conf import settings
        key_attrs = {
            "gemini": "GEMINI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "qwen": "QWEN_API_KEY",
        }
        attr = key_attrs.get(provider_name)
        if not attr:
            return False
        return bool(getattr(settings, attr, ""))

    def route(
        self,
        file_name: str = "",
        task: str = "",
        task_type: str = "",
        estimated_tokens: int = 0,
        prefer_cost: bool = True,
    ) -> RouteDecision:
        """
        Decide qué proveedor usar para una tarea.

        Args:
            file_name: Nombre del archivo (para detectar tipo por extensión).
            task: Descripción de la tarea.
            task_type: Tipo de tarea (opcional, override).
            estimated_tokens: Tokens estimados para la llamada.
            prefer_cost: Si True, prioriza proveedores más baratos.

        Returns:
            RouteDecision con proveedor seleccionado y razón.
        """
        # 1. Determinar tipo de tarea
        resolved_type = task_type or self._detect_task_type(file_name, task)

        # 2. Obtener ruta preferida + mejor histórico
        base_route = _TASK_ROUTES.get(resolved_type, _TASK_ROUTES["general"])
        best_historical = self.smart_learner.get_best_provider_for(resolved_type)

        # 3. Construir ruta: mejor histórico primero (si tiene presupuesto), luego ruta base
        route = list(base_route)
        if best_historical and best_historical in route:
            route.remove(best_historical)
            route.insert(0, best_historical)
        # Asegurar que "heuristic" está al final
        if "heuristic" in route:
            route.remove("heuristic")
        route.append("heuristic")

        decision = RouteDecision(
            task_type=resolved_type,
            fallback_chain=list(route),
        )

        # 4. Filtrar proveedores sin API Key
        route = [
            p for p in route
            if p == "heuristic" or self._check_api_key_exists(p)
        ]
        decision.fallback_chain = list(route)

        # 5. Recorrer ruta verificando presupuesto
        for candidate in route:
            if candidate == "heuristic":
                decision.selected_provider = "heuristic"
                decision.is_heuristic = True
                decision.reason = "Todos los proveedores AI no disponibles. Usando heurísticas locales."
                decision.confidence = 0.6
                break

            if self.budget.can_call(candidate, estimated_tokens):
                decision.selected_provider = candidate
                decision.used_budget = True
                if best_historical and candidate == best_historical:
                    decision.used_history = True
                    decision.reason = f"Ruteado a {candidate} para {resolved_type} (mejor histórico + presupuesto)"
                else:
                    decision.reason = f"Ruteado a {candidate} para {resolved_type} (presupuesto disponible)"
                logger.info(
                    "Router: %s → %s para '%s'",
                    resolved_type, candidate, file_name or task[:50],
                )
                break

        return decision

    def _detect_task_type(self, file_name: str, task: str) -> str:
        """Detecta tipo de tarea desde nombre de archivo y descripción."""
        ext = Path(file_name).suffix.lower() if file_name else ""

        # 1. Por extensión
        if ext in _EXT_TO_TASK:
            return _EXT_TO_TASK[ext]

        # 2. Por palabras clave en la tarea
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["ocr", "extraer texto", "imagen", "foto", "scan"]):
            return "ocr"
        if any(kw in task_lower for kw in ["clasifica", "clasificar", "tipo de documento"]):
            return "classify"
        if any(kw in task_lower for kw in ["campo", "columna", "encabezado", "detectar"]):
            return "field_detection"
        if any(kw in task_lower for kw in ["formulario", "crear formulario", "generar"]):
            return "form_generation"
        if any(kw in task_lower for kw in ["match", "mapear", "correspondencia", "columna"]):
            return "column_matching"
        if any(kw in task_lower for kw in ["resume", "resumen", "síntesis", "sintetiza"]):
            return "summary"
        if any(kw in task_lower for kw in ["factura", "invoice", "recibo"]):
            return "invoice"
        if any(kw in task_lower for kw in ["reporte", "informe", "dashboard"]):
            return "report"
        if any(kw in task_lower for kw in ["pregunta", "consulta", "chat", "conversación"]):
            return "chat"
        if any(kw in task_lower for kw in ["relación", "relacionar", "vínculo"]):
            return "relationship"

        return "general"

    def _apply_historical_performance(
        self,
        route: list[str],
        task_type: str,
    ) -> list[str]:
        """Reordena la ruta según rendimiento histórico."""
        best = self.smart_learner.get_best_provider_for(task_type)
        if not best:
            return route

        # Mover el mejor proveedor al inicio de la ruta (si está en la lista)
        new_route = [p for p in route if p != best and p != "heuristic"]
        if best in route:
            new_route.insert(0, best)
        new_route.append("heuristic")
        return new_route

    def get_route_for_extension(self, ext: str) -> list[str]:
        """Obtiene la ruta de proveedores para una extensión de archivo."""
        task = _EXT_TO_TASK.get(ext.lower(), "general")
        return _TASK_ROUTES.get(task, _TASK_ROUTES["general"])


# Singleton
_default_router: Optional[ProviderRouter] = None
_singleton_lock: Lock = Lock()


def get_provider_router() -> ProviderRouter:
    """Return the default ProviderRouter instance (thread-safe singleton)."""
    global _default_router
    if _default_router is None:
        with _singleton_lock:
            if _default_router is None:
                _default_router = ProviderRouter()
    return _default_router
