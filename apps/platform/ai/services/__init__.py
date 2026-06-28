"""
services — AI-powered analysis services (AI Platform v3.0).

All services are provider-agnostic. They receive a BaseAIProvider
instance and use it without knowing which model/provider is behind it.

Services organized by FASE:

  Core Services:
    - PromptManager:          Loads and renders prompt templates from prompts/
    - DocumentAnalyzer:       Analyzes any document type (Excel, CSV, PDF, image, text)
    - FieldDetector:          Detects fields and types from structured/unstructured data
    - InvoiceAnalyzer:        Extracts invoice data from images, PDFs, or text
    - FormGenerator:          Generates complete form proposals from analysis

  Agent Layer (F1-F6):
    - AgentOrchestrator:      Intelligent agent — single entry point for ALL processes
    - ReasoningEngine:        Internal reasoning before calling any AI
    - ContextBuilder:         Builds minimal, relevant AI context
    - PromptComposer:         Composes prompts from templates, context, rules
    - ConfidenceEngine:       Structured confidence scoring for every AI result

  Smart Services (F7-F11):
    - AIReportGenerator:      Reusable AI-powered reports for ANY form
    - ConversationalDocuments: Document Q&A backend (no chat UI yet)
    - SmartLearner:           MemoryLearner v2 — learns everything from user corrections
    - MultiDocumentPipeline:  Processes multiple documents and finds relationships
    - ProviderIntelligence:   Auto-selects best AI provider based on task
"""

from __future__ import annotations

# Re-export key services for convenient imports
from .agent_orchestrator import AgentOrchestrator, OrchestratorResult, get_orchestrator
from .ai_report_generator import AIReportGenerator, AIReport
from .confidence_engine import ConfidenceEngine, ConfidenceScore
from .context_builder import ContextBuilder, AIContext
from .conversational_documents import (
    ConversationalDocuments,
    DocumentContext,
    DocumentContextBuilder,
    DocumentConversation,
    QuestionClassifier,
    QuestionResult,
    QuestionType,
)
from .document_analyzer import DocumentAnalyzer
from .field_detector import FieldDetector
from .form_generator import FormGenerator
from .invoice_analyzer import InvoiceAnalyzer
from .multi_document_pipeline import (
    CrossDocumentAnalyzer,
    CrossDocumentRelationship,
    DocumentInput,
    MultiDocumentPipeline,
    MultiDocumentResult,
)
from .prompt_composer import PromptComposer
from .prompt_manager import PromptManager, get_prompt_manager
from .provider_intelligence import ProviderIntelligence, ProviderPolicy
from .reasoning_engine import ReasoningEngine, ReasoningPath, ReasoningStep
from .smart_learner import FieldPreference, FormTemplate, SmartLearner

__all__ = [
    # Orchestrator
    "AgentOrchestrator",
    "OrchestratorResult",
    "get_orchestrator",
    # Reports
    "AIReportGenerator",
    "AIReport",
    # Confidence
    "ConfidenceEngine",
    "ConfidenceScore",
    # Context
    "ContextBuilder",
    "AIContext",
    # Conversational
    "ConversationalDocuments",
    "DocumentContext",
    "DocumentContextBuilder",
    "DocumentConversation",
    "QuestionClassifier",
    "QuestionResult",
    "QuestionType",
    # Core analysis
    "DocumentAnalyzer",
    "FieldDetector",
    "FormGenerator",
    "InvoiceAnalyzer",
    # Multi-document
    "CrossDocumentAnalyzer",
    "CrossDocumentRelationship",
    "DocumentInput",
    "MultiDocumentPipeline",
    "MultiDocumentResult",
    # Prompt
    "PromptComposer",
    "PromptManager",
    "get_prompt_manager",
    # Provider
    "ProviderIntelligence",
    "ProviderPolicy",
    # Reasoning
    "ReasoningEngine",
    "ReasoningPath",
    "ReasoningStep",
    # Learning
    "FieldPreference",
    "FormTemplate",
    "SmartLearner",
]
