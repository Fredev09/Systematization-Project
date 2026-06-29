"""
decision_engine.py — AI Decision Engine (FASE 3, v4.0 FREE-FIRST).

Antes de llamar a cualquier IA, analiza:

  ¿Realmente hace falta IA?

Ejemplos de cuándo NO usar IA:
  - Excel con encabezados claros → heurísticas
  - CSV simple → matching clásico
  - Factura perfectamente estructurada → extracción directa
  - Columnas con nombres estándar → tipos predecibles

Cuándo SÍ usar IA:
  - Imagen/escaneo/foto (necesita OCR)
  - PDF sin estructura clara
  - Documento con formato ambiguo
  - Datos no estructurados

FREE-FIRST priority: NO usar IA a menos que sea realmente necesario.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from apps.platform.ai.types import FieldType

logger = logging.getLogger(__name__)


# ======================================================================
# Palabras clave de encabezados de columna que indican que NO se necesita IA
# ======================================================================

_STANDARD_HEADERS: set[str] = {
    # Español
    "nombre", "descripción", "descripcion", "precio", "valor", "costo",
    "cantidad", "stock", "existencia", "unidad", "medida",
    "código", "codigo", "id", "identificador", "sku", "referencia",
    "fecha", "hora", "fecha_hora", "fechahora",
    "categoría", "categoria", "tipo", "clase", "grupo",
    "estado", "activo", "activo?", "habilitado",
    "email", "correo", "teléfono", "telefono", "celular",
    "dirección", "direccion", "ciudad", "departamento", "país", "pais",
    "notas", "observaciones", "comentarios",
    "total", "subtotal", "iva", "descuento",
    # Inglés
    "name", "description", "price", "value", "cost", "quantity",
    "code", "identifier", "sku", "reference",
    "date", "time", "datetime", "category", "type",
    "status", "active", "enabled", "email", "phone",
    "address", "city", "country", "notes", "comments",
    "total", "subtotal", "tax", "discount",
}

# Encabezados que indican datos financieros (no necesitan IA para detectar tipo)
_FINANCIAL_HEADERS: set[str] = {
    "precio", "price", "valor", "value", "costo", "cost",
    "total", "subtotal", "iva", "tax", "descuento", "discount",
    "salario", "salary", "ingreso", "income", "gasto", "expense",
}

# Extensiones que TÍPICAMENTE necesitan IA
_AI_REQUIRED_EXTS: set[str] = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff",
}

# Extensiones que NUNCA necesitan IA
_NO_AI_EXTS: set[str] = {".csv", ".json", ".xml", ".yaml", ".yml", ".tsv"}


@dataclass
class DecisionResult:
    """Resultado de la decisión: ¿usar IA o no?"""
    use_ai: bool
    reason: str = ""
    confidence: float = 1.0
    suggested_provider: str = ""
    suggested_task_type: str = ""
    estimated_tokens: int = 0
    alternatives: list[str] = field(default_factory=list)


class AIDecisionEngine:
    """
    Decide si una tarea necesita IA o puede resolverse con heurísticas.

    Reglas FREE-FIRST:
      1. Si se puede resolver sin IA → hacerlo sin IA
      2. Si hay duda → intentar sin IA primero, validar después
      3. Solo usar IA cuando sea estrictamente necesario

    Usage:
        engine = AIDecisionEngine()
        decision = engine.decide(
            file_name="productos.xlsx",
            headers=["Nombre", "Precio", "Stock"],
            sample_rows=[["Laptop", "1500000", "10"]],
        )
        if decision.use_ai:
            # llamar IA
        else:
            # usar heurísticas locales
    """

    def decide(
        self,
        file_name: str = "",
        headers: Optional[list[str]] = None,
        sample_rows: Optional[list[list[str]]] = None,
        raw_text: str = "",
        task: str = "",
        detected_type: str = "",
    ) -> DecisionResult:
        """
        Decide si se necesita IA para esta tarea.

        Args:
            file_name: Nombre del archivo.
            headers: Encabezados de columna (si aplica).
            sample_rows: Filas de ejemplo (si aplica).
            raw_text: Texto extraído del documento.
            task: Descripción de la tarea.
            detected_type: Tipo de documento ya detectado.

        Returns:
            DecisionResult con recomendación.
        """
        ext = Path(file_name).suffix.lower() if file_name else ""

        # ── REGLA 1: Extensiones que REQUIEREN IA (imágenes, fotos) ──
        if ext in _AI_REQUIRED_EXTS:
            return DecisionResult(
                use_ai=True,
                reason=f"Imagen ({ext}) — requiere OCR/IA para extraer texto",
                suggested_provider="gemini",
                suggested_task_type="ocr",
                confidence=0.95,
            )

        # ── REGLA 2: Tipos ya detectados que REQUIEREN IA ──
        if detected_type == "image":
            return DecisionResult(
                use_ai=True,
                reason="Documento tipo imagen — requiere IA para análisis visual",
                suggested_task_type="ocr",
                confidence=0.95,
            )

        # ── REGLA 3: Extensiones que NUNCA necesitan IA ──
        if ext in _NO_AI_EXTS:
            return DecisionResult(
                use_ai=False,
                reason=f"Formato estructurado ({ext}) — se puede procesar con heurísticas",
                confidence=0.95,
            )

        # ── REGLA 4: Encabezados claros → NO IA ──
        if headers and len(headers) >= 2:
            result = self._evaluate_headers(headers, sample_rows)
            if not result.use_ai:
                return result

        # ── REGLA 5: Texto estructurado (CSV-like, tablas) → NO IA ──
        if raw_text:
            result = self._evaluate_text(raw_text)
            if not result.use_ai:
                return result

        # ── REGLA 6: Tarea específica del usuario ──
        if task:
            result = self._evaluate_task(task)
            return result

        # ── DEFAULT: Usar IA (seguro) ──
        return DecisionResult(
            use_ai=True,
            reason="No se pudo determinar si es procesable sin IA. Usando IA por seguridad.",
            confidence=0.5,
            suggested_task_type="general",
        )

    def _evaluate_headers(
        self,
        headers: list[str],
        sample_rows: Optional[list[list[str]]],
    ) -> DecisionResult:
        """Evalúa si los encabezados son suficientemente claros para NO usar IA."""
        clean_headers = [h.lower().strip() for h in headers]

        # Contar cuántos encabezados son "estándar" (conocidos)
        standard_count = sum(1 for h in clean_headers if h in _STANDARD_HEADERS)
        ratio = standard_count / len(headers) if headers else 0

        # Si ≥70% son estándar → NO necesitamos IA
        if ratio >= 0.7:
            # Detectar tipo de datos automáticamente
            financial = any(h in _FINANCIAL_HEADERS for h in clean_headers)
            return DecisionResult(
                use_ai=False,
                reason=f"{standard_count}/{len(headers)} encabezados son estándar ({ratio:.0%}). "
                       "Se puede inferir tipos con heurísticas.",
                confidence=0.85 + (ratio - 0.7) * 0.3,
                alternatives=["Usar FieldDetector.heuristic_detect()"],
            )

        # Si ≥50% son estándar → probablemente no necesitamos IA
        if ratio >= 0.5:
            return DecisionResult(
                use_ai=False,
                reason=f"{standard_count}/{len(headers)} encabezados son estándar. "
                       "Intento con heurísticas primero, IA como fallback.",
                confidence=0.65,
                alternatives=[
                    "Usar FieldDetector.heuristic_detect() primero",
                    "Si confianza < 0.5, llamar IA",
                ],
            )

        # Muchos encabezados no estándar → podría necesitar IA
        return DecisionResult(
            use_ai=True,
            reason=f"Solo {standard_count}/{len(headers)} encabezados son estándar. "
                   "Los nombres no estándar requieren análisis semántico.",
            confidence=0.6,
            suggested_task_type="field_detection",
            estimated_tokens=max(500, len(headers) * 100),
        )

    def _evaluate_text(self, raw_text: str) -> DecisionResult:
        """Evalúa si el texto estructurado necesita IA."""
        lines = raw_text.strip().split("\n")

        # Si tiene menos de 3 líneas, probablemente no es tabla
        if len(lines) < 3:
            return DecisionResult(
                use_ai=True,
                reason="Texto muy corto — podría necesitar IA para interpretar",
                confidence=0.4,
                suggested_task_type="general",
            )

        # Si tiene delimitadores consistentes (|, ;, \t), probablemente es tabla
        first_line = lines[0].strip() if lines else ""
        delimiters = ["|", ";", "\t", ","]
        delim_count = sum(1 for d in delimiters if d in first_line)

        if delim_count >= 1:
            return DecisionResult(
                use_ai=False,
                reason="Texto con estructura tabular detectada. Procesable con heurísticas.",
                confidence=0.8,
                alternatives=["Parsear con split por delimitador"],
            )

        # Texto largo sin estructura clara → probablemente necesita IA
        return DecisionResult(
            use_ai=True,
            reason="Texto sin estructura tabular clara — requiere análisis semántico.",
            confidence=0.5,
            suggested_task_type="general",
        )

    def _evaluate_task(self, task: str) -> DecisionResult:
        """Evalúa si la tarea del usuario necesita IA."""
        task_lower = task.lower()

        # Tareas que definitivamente necesitan IA
        ai_keywords = [
            "analiza", "analizar", "interpreta", "interpretar",
            "resume", "resumen", "sintetiza", "describe",
            "recomienda", "sugiere", "compara", "compara",
            "genera", "crea", "propón", "propon",
            "qué opinas", "qué piensas", "cómo ves",
        ]
        if any(kw in task_lower for kw in ai_keywords):
            return DecisionResult(
                use_ai=True,
                reason="La tarea requiere análisis semántico/IA",
                confidence=0.9,
                suggested_task_type="general",
            )

        # Tareas que NO necesitan IA
        no_ai_keywords = [
            "extraer", "exportar", "importar", "listar",
            "ordenar", "filtrar", "buscar", "contar",
            "mostrar", "calcular", "sumar", "promedio",
        ]
        if any(kw in task_lower for kw in no_ai_keywords):
            return DecisionResult(
                use_ai=False,
                reason="La tarea es procedimental — no requiere IA",
                confidence=0.85,
            )

        # Indeterminado
        return DecisionResult(
            use_ai=True,
            reason="No se pudo clasificar la tarea. Usando IA por seguridad.",
            confidence=0.5,
            suggested_task_type="general",
        )


# Singleton
_default_decision: Optional[AIDecisionEngine] = None


def get_decision_engine() -> AIDecisionEngine:
    """Return the default AIDecisionEngine instance (singleton)."""
    global _default_decision
    if _default_decision is None:
        _default_decision = AIDecisionEngine()
    return _default_decision
