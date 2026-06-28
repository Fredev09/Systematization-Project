"""
apps.platform.ai — AI Infrastructure Module for ERP.

Enterprise-grade, multi-provider AI orchestration layer.

Design:
  - Clean Architecture / SOLID
  - Provider-agnostic interface (BaseAIProvider)
  - Strategy pattern for multi-provider switching
  - Template pattern for document analysis pipeline
  - Decoupled from Dynamic Forms; reusable from any app

A quick example of usage:

    from apps.platform.ai.services.document_analyzer import DocumentAnalyzer
    from apps.platform.ai.providers.gemini import GeminiProvider

    provider = GeminiProvider()
    analyzer = DocumentAnalyzer(provider=provider)
    result = await analyzer.analyze("factura.pdf")
    print(result)
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = []
