"""
services — Document Intelligence services.

All services are provider-agnostic and use apps.platform.ai internally.
"""

from __future__ import annotations

from apps.platform.document_intelligence.services.pipeline import DocumentIntelligencePipeline
from apps.platform.document_intelligence.services.structure_detector import StructureDetector
from apps.platform.document_intelligence.services.auto_form_creator import AutoFormCreator
from apps.platform.document_intelligence.services.relationship_detector import RelationshipDetector
from apps.platform.document_intelligence.services.memory_learner import MemoryLearner
from apps.platform.document_intelligence.services.quality_scorer import QualityScorer

__all__ = [
    "DocumentIntelligencePipeline",
    "StructureDetector",
    "AutoFormCreator",
    "RelationshipDetector",
    "MemoryLearner",
    "QualityScorer",
]
