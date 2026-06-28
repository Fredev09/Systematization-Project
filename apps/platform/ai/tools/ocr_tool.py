"""
ocr_tool.py — OCR Tool for image text extraction.
"""

from __future__ import annotations

import logging
from pathlib import Path

from apps.platform.ai.tools.base import BaseTool, ExecutionContext, ToolResult, ToolSpec
from apps.platform.ai.utils import file_to_base64

logger = logging.getLogger(__name__)


class OCRTool(BaseTool):
    """Extracts text from images using AI provider's vision capabilities."""

    spec = ToolSpec(
        name="ocr",
        description="Extrae texto de imágenes, fotos y escaneos usando el proveedor AI",
        parameters={
            "file_path": {"type": "string", "description": "Ruta a la imagen"},
            "mime_type": {"type": "string", "description": "Tipo MIME de la imagen"},
        },
        expected_output="Texto extraído de la imagen con estructura detectada",
        estimated_cost=0.001,
        estimated_time_ms=3000,
        category="extraction",
        requires_provider=True,
        requires_file=True,
    )

    def execute(self, context: ExecutionContext) -> ToolResult:
        if not context.provider:
            return ToolResult(
                success=False,
                errors=["No AI provider available for OCR"],
                confidence=0.0,
            )

        if not context.file_path:
            return ToolResult(
                success=False,
                errors=["No file path provided for OCR"],
                confidence=0.0,
            )

        path = Path(context.file_path)
        if not path.exists():
            return ToolResult(
                success=False,
                errors=[f"File not found: {context.file_path}"],
                confidence=0.0,
            )

        try:
            mime, b64 = file_to_base64(path)
            response = context.provider.analyze_image(
                image_data=b64,
                mime_type=mime,
                system_instruction=(
                    "Extrae TODO el texto de esta imagen con la máxima precisión. "
                    "Si contiene una tabla, devuelve los datos estructurados en formato JSON. "
                    "Responde ÚNICAMENTE con JSON válido."
                ),
                use_cache=context.use_cache,
            )

            if not response.success:
                return ToolResult(
                    success=False,
                    errors=[response.error or "OCR failed"],
                    confidence=0.0,
                )

            # Try to extract structured data from JSON response
            from apps.platform.ai.utils import safe_json_parse
            parsed = safe_json_parse(response.text)
            extracted_text = response.text
            structured_data = {}

            if parsed and isinstance(parsed, dict):
                structured_data = parsed
                extracted_text = parsed.get("text", parsed.get("content", response.text))

            return ToolResult(
                success=True,
                data={
                    "raw_text": extracted_text,
                    "structured": structured_data,
                    "char_count": len(extracted_text),
                    "mime_type": mime,
                },
                confidence=0.9 if response.success else 0.3,
                metadata={
                    "provider": response.provider,
                    "model": response.model,
                    "cached": response.cached,
                },
            )

        except Exception as e:
            logger.exception("OCR failed")
            return ToolResult(
                success=False,
                errors=[f"OCR error: {e}"],
                confidence=0.0,
            )
