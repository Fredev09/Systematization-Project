"""
field_detector.py — AI-powered field detection service.

Receives structured or unstructured data (Excel, CSV, table, JSON, image, invoice)
and returns suggested fields with types, validations, and confidence scores.

Uses the AI provider for semantic analysis and falls back to heuristic
type guessing for simple cases.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from apps.platform.ai.exceptions import AnalysisError
from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.ai.services.prompt_manager import get_prompt_manager
from apps.platform.ai.types import (
    AIResponse,
    DetectedField,
    FieldType,
)
from apps.platform.ai.utils import guess_field_type_from_value, safe_json_parse

logger = logging.getLogger(__name__)


class FieldDetector:
    """
    Detects fields and their types from documents or raw data.

    Two modes:
      1. analyze_data(headers, sample_rows) — from structured data (Excel, CSV, table)
      2. analyze_text(description) — from natural language or unstructured text

    Usage:
        detector = FieldDetector(provider=gemini_provider)
        fields = detector.analyze_data(
            headers=["Nombre", "Precio", "Stock"],
            sample_rows=[["Laptop", "1500000", "10"]],
        )
    """

    def __init__(
        self,
        provider: BaseAIProvider,
        prompt_manager: Optional[Any] = None,
    ):
        self.provider = provider
        self.pm = prompt_manager or get_prompt_manager()

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    def analyze_data(
        self,
        headers: list[str],
        sample_rows: Optional[list[list[str]]] = None,
        existing_fields: Optional[list[str]] = None,
        field_count_hint: Optional[int] = None,
        use_cache: bool = True,
    ) -> list[DetectedField]:
        """
        Analyze headers and sample data to detect field types.

        Args:
            headers: Column headers from the document.
            sample_rows: Optional sample data (first N rows).
            existing_fields: Optional list of already-known field names.
            field_count_hint: Optional expected number of fields.
            use_cache: Whether to use cached results.

        Returns:
            List of DetectedField with suggested types and confidence.
        """
        if not headers:
            return []

        # For simple cases with few headers, use heuristic first
        if len(headers) <= 5 and sample_rows:
            heuristic_fields = self._heuristic_detect(headers, sample_rows)
            # If all heuristic confidence is high, return early
            if all(f.confidence >= 0.85 for f in heuristic_fields):
                return heuristic_fields

        # Build prompt for AI analysis
        context = {
            "field_names": ", ".join(headers),
            "sample_rows": self._format_sample_rows(headers, sample_rows),
            "existing_fields": ", ".join(existing_fields) if existing_fields else "ninguno",
        }

        prompt = self.pm.render("detect_fields", **context)

        response = self.provider.generate_json(
            prompt=prompt,
            system_instruction=(
                "Eres un experto en análisis de datos colombiano. "
                "Detecta los tipos de campo más apropiados para cada columna. "
                "Responde ÚNICAMENTE con JSON válido."
            ),
            use_cache=use_cache,
        )

        if not response.success or not response.json_data:
            # Fallback to heuristic
            logger.warning("AI field detection failed. Using heuristic fallback.")
            return self._heuristic_detect(headers, sample_rows)

        return self._parse_fields(response.json_data, headers, sample_rows)

    def analyze_text(
        self,
        description: str,
        use_cache: bool = True,
    ) -> list[DetectedField]:
        """
        Detect fields from a natural language description.
        Useful for generating forms from user descriptions.
        """
        prompt = self.pm.render(
            "detect_form",
            user_description=description,
        )

        response = self.provider.generate_json(
            prompt=prompt,
            system_instruction=(
                "Eres un experto en diseño de formularios. "
                "A partir de la descripción del usuario, genera los campos "
                "más apropiados. Responde ÚNICAMENTE con JSON válido."
            ),
            use_cache=use_cache,
        )

        if not response.success or not response.json_data:
            return []

        return self._parse_fields(response.json_data, [])

    def analyze_image(
        self,
        image_base64: str,
        mime_type: str = "image/jpeg",
        description: str = "",
        use_cache: bool = True,
    ) -> list[DetectedField]:
        """
        Detect fields from an image (photo, scan, screenshot).
        Useful for invoice photos or document scans.
        """
        prompt = description or (
            "Analiza esta imagen y extrae todos los campos de datos "
            "que puedas identificar. Para cada campo proporciona: "
            "nombre, tipo sugerido, si es obligatorio, si es único, "
            "y un nivel de confianza (0-1)."
        )

        response = self.provider.analyze_image(
            image_data=image_base64,
            mime_type=mime_type,
            system_instruction=(
                "Eres un experto en reconocimiento de documentos. "
                "Extrae todos los campos de datos visibles en la imagen. "
                "Responde ÚNICAMENTE con JSON."
            ),
            use_cache=use_cache,
        )

        parsed = safe_json_parse(response.text) if response.text else None
        if parsed:
            return self._parse_fields(parsed, [])

        return []

    # ──────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────

    def _heuristic_detect(
        self,
        headers: list[str],
        sample_rows: Optional[list[list[str]]],
    ) -> list[DetectedField]:
        """
        Fast heuristic detection without AI call.
        Used for simple cases or as fallback.
        """
        fields: list[DetectedField] = []
        for idx, header in enumerate(headers):
            sample_value = ""
            if sample_rows and idx < len(sample_rows[0]):
                sample_value = sample_rows[0][idx]

            guessed_type = guess_field_type_from_value(sample_value) if sample_value else "texto"

            # Heuristic confidence based on header keywords and sample
            confidence = 0.6
            if sample_value and guessed_type != "texto":
                confidence = 0.85

            # Common field name heuristics
            header_lower = header.lower().strip()

            # Identifier patterns (FASE 5)
            if any(kw in header_lower for kw in ["código", "codigo", "id", "identificador", "cód", "sku"]):
                confidence = 0.9
                guessed_type = "codigo"
            elif any(kw in header_lower for kw in ["precio", "valor", "costo", "total", "subtotal", "monto"]):
                confidence = 0.9
                guessed_type = "moneda"
            elif any(kw in header_lower for kw in ["cantidad", "stock", "existencia", "número", "numero", "unidades"]):
                confidence = 0.9
                guessed_type = "numero"
            elif any(kw in header_lower for kw in ["porcentaje", "%", "tasa", "tarifa", "interés", "interes", "iva"]):
                confidence = 0.9
                guessed_type = "porcentaje"
            elif any(kw in header_lower for kw in ["fecha", "date"]):
                if any(kw2 in header_lower for kw2 in ["hora", "time", "datetime"]):
                    confidence = 0.9
                    guessed_type = "fecha_hora"
                else:
                    confidence = 0.9
                    guessed_type = "fecha"
            elif any(kw in header_lower for kw in ["hora", "time", "horario"]):
                if not any(kw2 in header_lower for kw2 in ["fecha", "date"]):
                    confidence = 0.9
                    guessed_type = "hora"
            elif any(kw in header_lower for kw in ["email", "correo", "e-mail"]):
                confidence = 0.95
                guessed_type = "email"
            elif any(kw in header_lower for kw in ["teléfono", "telefono", "celular", "móvil", "movil"]):
                confidence = 0.95
                guessed_type = "telefono"
            elif any(kw in header_lower for kw in ["cédula", "cedula", "documento", "nit", "cc", "identificación"]):
                confidence = 0.9
                guessed_type = "documento"
            elif any(kw in header_lower for kw in ["activo", "activo?", "estado", "habilitado", "activo/inactivo"]):
                confidence = 0.9
                guessed_type = "booleano"
            elif any(kw in header_lower for kw in ["url", "enlace", "link", "web", "sitio", "página", "pagina"]):
                confidence = 0.9
                guessed_type = "url"
            elif any(kw in header_lower for kw in ["color", "rgb", "hex"]):
                confidence = 0.85
                guessed_type = "color"
            elif any(kw in header_lower for kw in ["ip", "dirección ip", "direccion ip"]):
                confidence = 0.9
                guessed_type = "ip"
            elif any(kw in header_lower for kw in ["uuid", "uid", "guid"]):
                confidence = 0.9
                guessed_type = "uuid"
            elif any(kw in header_lower for kw in ["latitud", "longitud", "lat", "lng", "coordinates", "geolocalización", "geolocalizacion", "ubicación", "ubicacion"]):
                confidence = 0.9
                guessed_type = "geolocalizacion"
            elif any(kw in header_lower for kw in ["duración", "duracion", "tiempo", "horas", "minutos"]):
                confidence = 0.85
                guessed_type = "duracion"
            elif any(kw in header_lower for kw in ["código barras", "codigo barras", "barcode", "ean", "upc"]):
                confidence = 0.9
                guessed_type = "codigo_barras"
            elif any(kw in header_lower for kw in ["qr", "código qr", "codigo qr"]):
                confidence = 0.9
                guessed_type = "qr"
            elif any(kw in header_lower for kw in ["estado", "status", "situación", "situacion"]):
                confidence = 0.85
                guessed_type = "estado"
            elif any(kw in header_lower for kw in ["categoría", "categoria", "tipo", "clase", "grupo"]):
                confidence = 0.85
                guessed_type = "categoria"
            elif any(kw in header_lower for kw in ["tags", "etiquetas", "palabras clave"]):
                confidence = 0.85
                guessed_type = "tags"

            fields.append(DetectedField(
                name=header,
                suggested_type=guessed_type,
                confidence=confidence,
                explanation=f"Heuristic detection based on header '{header}'",
                order=idx,
            ))

        return fields

    def _format_sample_rows(
        self,
        headers: list[str],
        sample_rows: Optional[list[list[str]]],
    ) -> str:
        """Format sample rows for the prompt."""
        if not sample_rows:
            return "(sin datos de ejemplo)"
        lines = []
        for row in sample_rows[:5]:  # Max 5 rows
            pairs = []
            for idx, val in enumerate(row):
                if idx < len(headers):
                    pairs.append(f"{headers[idx]}: {val}")
            lines.append(" | ".join(pairs))
        return "\n".join(lines)

    def _parse_fields(
        self,
        data: dict[str, Any],
        headers: list[str],
        sample_rows: Optional[list[list[str]]] = None,
    ) -> list[DetectedField]:
        """Parse AI response into DetectedField list."""
        fields: list[DetectedField] = []

        raw_fields = data.get("fields", data.get("campos", []))

        if isinstance(raw_fields, dict):
            # Handle { "nombre": {...}, "precio": {...} } format
            raw_fields = [
                {"name": k, **v} for k, v in raw_fields.items()
            ]

        if not isinstance(raw_fields, list):
            return self._heuristic_detect(headers, sample_rows)

        for idx, f_data in enumerate(raw_fields):
            if isinstance(f_data, str):
                # Simple list of field names
                fields.append(DetectedField(
                    name=f_data,
                    suggested_type="texto",
                    confidence=0.5,
                    order=idx,
                ))
            elif isinstance(f_data, dict):
                fields.append(DetectedField(
                    name=f_data.get("name", f_data.get("nombre", f"campo_{idx}")),
                    suggested_type=f_data.get("type", f_data.get("tipo", "texto")),
                    required=f_data.get("required", f_data.get("obligatorio", False)),
                    unique=f_data.get("unique", f_data.get("unico", False)),
                    is_identifier=f_data.get("is_identifier", f_data.get("identificador", False)),
                    confidence=f_data.get("confidence", f_data.get("confianza", 0.0)),
                    explanation=f_data.get("explanation", f_data.get("explicacion", "")),
                    alternatives=f_data.get("alternatives", f_data.get("alternativas", [])),
                    order=idx,
                    options=f_data.get("options", f_data.get("opciones")),
                    related_form=f_data.get("related_form", f_data.get("formulario_relacionado")),
                    formula=f_data.get("formula", None),
                ))

        return fields
