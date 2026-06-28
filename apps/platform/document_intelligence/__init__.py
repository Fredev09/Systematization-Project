"""
apps.platform.document_intelligence — Document Intelligence Platform v1.0.

Enterprise-grade, universal document analysis pipeline.

Architecture:
  - Extractors: Strategy pattern per document type (Excel, CSV, PDF, Image, Text)
  - Pipeline: Universal orchestrator (Extract → Normalize → Detect → AI → Validate → Propose → Review → Create → Import → Audit)
  - StructureDetector: Heuristic + AI document type classification
  - AutoFormCreator: AI-powered form generation from any document
  - RelationshipDetector: Entity relationship discovery
  - MemoryLearner: Learns from user decisions over time
  - QualityScorer: ★★★★★ scoring with recommendations

Design:
  - Clean Architecture / SOLID / DRY
  - Provider-agnostic (uses apps.platform.ai module)
  - Independent from Dynamic Forms (but integrates via services)
  - Backward compatible: existing import flow unchanged
"""

from __future__ import annotations

__version__ = "1.0.0"
