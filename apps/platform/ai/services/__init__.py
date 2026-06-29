"""
services — AI-powered analysis services (AI Platform v4.0 FREE-FIRST).

All services are provider-agnostic. They receive a BaseAIProvider
instance and use it without knowing which model/provider is behind it.

Services organized by módulo:

  Core Services:
    - PromptManager:          Loads and renders prompt templates from prompts/
    - DocumentAnalyzer:       Analyzes any document type (Excel, CSV, PDF, image, text)
    - FieldDetector:          Detects fields and types from structured/unstructured data
    - InvoiceAnalyzer:        Extracts invoice data from images, PDFs, or text
    - FormGenerator:          Generates complete form proposals from analysis

  Agent Layer:
    - AgentOrchestrator:      Intelligent agent — single entry point for ALL processes
    - ReasoningEngine:        Internal reasoning before calling any AI
    - ContextBuilder:         Builds minimal, relevant AI context
    - PromptComposer:         Composes prompts from templates, context, rules
    - ConfidenceEngine:       Structured confidence scoring for every AI result

  Smart Services:
    - AIReportGenerator:      Reusable AI-powered reports for ANY form
    - ConversationalDocuments: Document Q&A backend
    - SmartLearner:           MemoryLearner v2 — learns everything from user corrections
    - MultiDocumentPipeline:  Processes multiple documents and finds relationships
    - ProviderIntelligence:   Auto-selects best AI provider based on task

  FREE-FIRST Autonomous Layer (v4.0):
    - BudgetManager:          Rate limiting, token tracking, auto-disable providers
    - ProviderRouter:         Routes tasks to best free provider (budget + history aware)
    - AIDecisionEngine:       Decides if AI is really needed (avoids unnecessary calls)
    - ConsensusEngine:        Queries 2 free models, compares, tiebreaker heuristic
    - AutoEvaluator:          Evaluates every AI response for quality
    - PromptOptimizer:        Compresses prompts, reduces tokens
    - PromptVersionManager:   Versioned prompts with performance metrics
    - OfflineFirstEngine:     Graceful degradation without internet
    - MultiLevelCache:        SHA-based cache per document, image, OCR, prompt, form
    - AIDashboardService:     Consolidated admin stats from all modules
"""

from __future__ import annotations

# ── Core Services ──
from .agent_orchestrator import AgentOrchestrator, OrchestratorResult, get_orchestrator
from .ai_report_generator import AIReportGenerator, AIReport
from .confidence_engine import ConfidenceEngine, ConfidenceScore
from .context_builder import ContextBuilder, AIContext
from .document_analyzer import DocumentAnalyzer
from .field_detector import FieldDetector
from .form_generator import FormGenerator
from .invoice_analyzer import InvoiceAnalyzer
from .prompt_composer import PromptComposer
from .prompt_manager import PromptManager, get_prompt_manager
from .provider_intelligence import ProviderIntelligence, ProviderPolicy
from .reasoning_engine import ReasoningEngine, ReasoningPath, ReasoningStep

# ── Smart Services (v3.0) ──
from .conversational_documents import (
    ConversationalDocuments,
    DocumentContext,
    DocumentContextBuilder,
    DocumentConversation,
    QuestionClassifier,
    QuestionResult,
    QuestionType,
)
from .multi_document_pipeline import (
    CrossDocumentAnalyzer,
    CrossDocumentRelationship,
    DocumentInput,
    MultiDocumentPipeline,
    MultiDocumentResult,
)
from .smart_learner import FieldPreference, FormTemplate, SmartLearner

# ── FREE-FIRST Autonomous Layer (v4.0) ──
from .auto_evaluation import AutoEvaluator, EvaluationResult, get_auto_evaluator
from .budget_manager import BudgetManager, ProviderBudget, get_budget_manager
from .consensus_engine import ConsensusEngine, ConsensusResult, get_consensus_engine
from .decision_engine import AIDecisionEngine, DecisionResult, get_decision_engine
from .multi_level_cache import CacheEntry, MultiLevelCache, get_multi_level_cache
from .ai_dashboard import AIDashboardData, AIDashboardService, get_ai_dashboard
from .offline_first import (
    ConnectionMonitor,
    ConnectionStatus,
    OfflineFirstEngine,
    OperationMode,
    get_offline_first_engine,
)
from .planner import Plan, PlanStep, StepStatus, TaskPlanner
from .prompt_versioning import (
    PromptOptimizer,
    PromptVersion,
    PromptVersionManager,
    get_prompt_optimizer,
    get_prompt_version_manager,
)
from .provider_router import ProviderRouter, RouteDecision, get_provider_router


__all__ = [
    # Core
    "AgentOrchestrator",
    "OrchestratorResult",
    "get_orchestrator",
    "AIReportGenerator",
    "AIReport",
    "ConfidenceEngine",
    "ConfidenceScore",
    "ContextBuilder",
    "AIContext",
    "DocumentAnalyzer",
    "FieldDetector",
    "FormGenerator",
    "InvoiceAnalyzer",
    "PromptComposer",
    "PromptManager",
    "get_prompt_manager",
    "ProviderIntelligence",
    "ProviderPolicy",
    "ReasoningEngine",
    "ReasoningPath",
    "ReasoningStep",

    # Smart Services (v3.0)
    "ConversationalDocuments",
    "DocumentContext",
    "DocumentContextBuilder",
    "DocumentConversation",
    "QuestionClassifier",
    "QuestionResult",
    "QuestionType",
    "CrossDocumentAnalyzer",
    "CrossDocumentRelationship",
    "DocumentInput",
    "MultiDocumentPipeline",
    "MultiDocumentResult",
    "FieldPreference",
    "FormTemplate",
    "SmartLearner",

    # FREE-FIRST (v4.0)
    "AutoEvaluator",
    "EvaluationResult",
    "get_auto_evaluator",
    "BudgetManager",
    "ProviderBudget",
    "get_budget_manager",
    "ConsensusEngine",
    "ConsensusResult",
    "get_consensus_engine",
    "AIDecisionEngine",
    "DecisionResult",
    "get_decision_engine",
    "CacheEntry",
    "MultiLevelCache",
    "get_multi_level_cache",
    "AIDashboardData",
    "AIDashboardService",
    "get_ai_dashboard",
    "ConnectionMonitor",
    "ConnectionStatus",
    "OfflineFirstEngine",
    "OperationMode",
    "get_offline_first_engine",
    "Plan",
    "PlanStep",
    "StepStatus",
    "TaskPlanner",
    "PromptOptimizer",
    "PromptVersion",
    "PromptVersionManager",
    "get_prompt_optimizer",
    "get_prompt_version_manager",
    "ProviderRouter",
    "RouteDecision",
    "get_provider_router",
]
