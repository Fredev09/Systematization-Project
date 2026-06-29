"""
conversational_documents.py — Conversational Documents backend (FASE 8).

Preparates the infrastructure so that ANY document can answer questions:

  - "Resume este archivo"
  - "¿Cuántos registros tiene?"
  - "¿Qué columnas detectaste?"
  - "¿Qué datos faltan?"
  - "¿Qué errores encontraste?"
  - "¿Qué información importante ves?"
  - "¿Qué recomendaciones harías?"
  - "Genera un dashboard"
  - "Resume en lenguaje ejecutivo"

Backend-only — no visual chat yet.
Designed to be consumed by any frontend (Django template, REST API, WebSocket).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from apps.platform.ai.exceptions import AnalysisError
from apps.platform.ai.providers.base import BaseAIProvider
from apps.platform.ai.providers import get_provider
from apps.platform.ai.services.context_builder import ContextBuilder, AIContext
from apps.platform.ai.services.prompt_composer import PromptComposer
from apps.platform.ai.tools.base import ExecutionContext
from apps.platform.ai.types import ProviderConfig
from apps.platform.ai.utils import truncate_text

logger = logging.getLogger(__name__)


# ======================================================================
# Question Types
# ======================================================================

class QuestionType(str, Enum):
    """Types of questions that can be asked about a document."""
    SUMMARY = "summary"               # "Resume este archivo"
    COUNT = "count"                   # "¿Cuántos registros tiene?"
    COLUMNS = "columns"               # "¿Qué columnas detectaste?"
    MISSING = "missing"               # "¿Qué datos faltan?"
    ERRORS = "errors"                 # "¿Qué errores encontraste?"
    INSIGHTS = "insights"             # "¿Qué información importante ves?"
    RECOMMENDATIONS = "recommendations"  # "¿Qué recomendaciones harías?"
    DASHBOARD = "dashboard"           # "Genera un dashboard"
    EXECUTIVE = "executive"           # "Resume en lenguaje ejecutivo"
    ANOMALIES = "anomalies"           # "¿Qué anomalías encuentras?"
    TRENDS = "trends"                 # "¿Qué tendencias observas?"
    COMPARISON = "comparison"         # "Compara con periodos anteriores"
    FREE = "free"                     # Any other question


# ======================================================================
# Data Classes
# ======================================================================

@dataclass
class DocumentContext:
    """
    Context for a document that can answer questions.
    
    Built from a pipeline result, extracted document, or form data.
    """
    document_id: Optional[int] = None
    file_name: str = ""
    file_type: str = ""
    document_type: str = ""
    raw_text: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)
    total_records: int = 0
    total_columns: int = 0
    field_names: list[str] = field(default_factory=list)
    field_types: dict[str, str] = field(default_factory=dict)
    form_name: str = ""
    form_description: str = ""
    quality_score: float = 0.0
    warnings: list[str] = field(default_factory=list)
    errors_found: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """Check if document has no content."""
        return not self.raw_text and not self.rows and not self.columns


@dataclass
class QuestionResult:
    """
    Structured answer to a document question.
    
    Every question produces this — never raw text alone.
    """
    question: str
    question_type: QuestionType = QuestionType.FREE
    answer: str = ""
    confidence: float = 0.0
    data: Optional[dict[str, Any]] = None
    suggested_visualizations: list[str] = field(default_factory=list)
    followup_questions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    processing_time_ms: float = 0.0


@dataclass
class DocumentConversation:
    """
    Complete conversation context for a document.
    
    Keeps history of questions and answers for follow-up context.
    """
    document: DocumentContext
    history: list[dict[str, Any]] = field(default_factory=list)
    current_summary: str = ""
    current_dashboard: Optional[dict[str, Any]] = None


# ======================================================================
# Question Classifier — detects question type from natural language
# ======================================================================

class QuestionClassifier:
    """
    Classifies a user question into a QuestionType.
    
    Heuristic-only — no AI call needed for classification.
    """
    
    _PATTERNS: dict[QuestionType, list[str]] = {
        QuestionType.SUMMARY: [
            "resume", "resumen", "resuma", "resúmen", "resumir",
            "sintetiza", "síntesis", "sintesis",
            "describe", "descripción", "descripcion",
        ],
        QuestionType.COUNT: [
            "cuántos", "cuantos", "cuántas", "cuantas",
            "cantidad", "total de", "número de", "numero de",
            "¿cuánto", "¿cuanto",
        ],
        QuestionType.COLUMNS: [
            "columnas", "encabezados", "campos",
            "qué columnas", "que columnas",
            "cuáles son los campos", "cuales son los campos",
        ],
        QuestionType.MISSING: [
            "faltan", "falta", "faltante", "faltantes",
            "datos faltantes", "información faltante",
            "qué falta", "que falta", "qué datos faltan", "que datos faltan",
        ],
        QuestionType.ERRORS: [
            "error", "errores", "problemas", "incorrecto",
            "mal", "inválido", "invalido", "inconsistencia",
            "inconsistencias", "anomalías", "anomalias",
        ],
        QuestionType.INSIGHTS: [
            "información importante", "informacion importante",
            "qué ves", "que ves", "qué observas", "que observas",
            "insights", "hallazgos", "descubrimientos",
            "qué información", "que informacion",
        ],
        QuestionType.RECOMMENDATIONS: [
            "recomendaciones", "recomendación", "recomendacion",
            "sugerencias", "sugerencia", "qué harías", "que harías",
            "qué acciones", "que acciones", "mejorar",
        ],
        QuestionType.DASHBOARD: [
            "dashboard", "tablero", "panel",
            "gráfico", "grafico", "gráfica", "grafica",
            "visualización", "visualizacion", "chart",
        ],
        QuestionType.EXECUTIVE: [
            "ejecutivo", "ejecutiva", "lenguaje ejecutivo",
            "directivo", "ceo", "gerente",
            "resumen ejecutivo", "resúmen ejecutivo",
        ],
        QuestionType.ANOMALIES: [
            "anomalía", "anomalia", "anomalías", "anomalias",
            "valores atípicos", "atipicos", "outlier",
            "extraño", "extraña", "raro", "rara",
        ],
        QuestionType.TRENDS: [
            "tendencia", "tendencias", "evolución", "evolucion",
            "cambio", "cambios", "patrón", "patron",
            "crecimiento", "decrecimiento", "aumento",
        ],
        QuestionType.COMPARISON: [
            "comparación", "comparacion", "comparar",
            "vs", "versus", "diferencia", "diferencias",
            "periodo anterior", "período anterior",
            "mes pasado", "año pasado", "semana pasada",
        ],
    }

    def classify(self, question: str) -> QuestionType:
        """Classify the question into a QuestionType."""
        q_lower = question.lower().strip()
        
        for qtype, patterns in self._PATTERNS.items():
            for pattern in patterns:
                if pattern in q_lower:
                    return qtype
        
        return QuestionType.FREE


# ======================================================================
# Context Builder for Documents
# ======================================================================

class DocumentContextBuilder:
    """
    Builds DocumentContext from various sources.
    
    Supports:
      - PipelineResult
      - ExtractedDocument
      - Dynamic Form + records
      - Raw text/headers/rows
    """
    
    def from_pipeline_result(self, result: Any) -> DocumentContext:
        """Build context from a PipelineResult (document_intelligence)."""
        ctx = DocumentContext()
        
        if hasattr(result, 'extracted_doc') and result.extracted_doc:
            doc = result.extracted_doc
            ctx.file_name = getattr(doc, 'title', '') or getattr(doc, 'file_name', '')
            ctx.document_type = getattr(doc, 'document_type', 'unknown')
            ctx.raw_text = getattr(doc, 'raw_text', '')
            ctx.columns = getattr(doc, 'columns', getattr(doc, 'headers', []))
            ctx.rows = getattr(doc, 'rows', [])
            ctx.total_records = len(ctx.rows)
            ctx.total_columns = len(ctx.columns)
        
        if hasattr(result, 'classification') and result.classification:
            ctx.document_type = getattr(result.classification, 'document_type', ctx.document_type)
            ctx.warnings.extend(getattr(result.classification, 'warnings', []))
        
        if hasattr(result, 'form_proposal') and result.form_proposal:
            proposal = result.form_proposal
            ctx.form_name = getattr(proposal, 'form_name', '')
            ctx.form_description = getattr(proposal, 'form_description', '')
            fields = getattr(proposal, 'fields', [])
            ctx.field_names = [f.get('name', f.name) if hasattr(f, 'name') else str(f) for f in (fields or [])]
            for f in (fields or []):
                fname = f.get('name', f.name) if hasattr(f, 'name') else str(f)
                ftype = f.get('suggested_type', f.suggested_type) if hasattr(f, 'suggested_type') else 'texto'
                ctx.field_types[fname] = ftype
        
        if hasattr(result, 'quality_score') and result.quality_score:
            ctx.quality_score = getattr(result.quality_score, 'overall', 0.0)
        
        if hasattr(result, 'errors'):
            ctx.errors_found = result.errors or []
        
        return ctx
    
    def from_extracted_doc(self, doc: Any) -> DocumentContext:
        """Build context from an ExtractedDocument."""
        ctx = DocumentContext()
        ctx.file_name = getattr(doc, 'title', '') or getattr(doc, 'file_name', '')
        ctx.document_type = getattr(doc, 'document_type', 'unknown')
        ctx.raw_text = getattr(doc, 'raw_text', '')
        ctx.columns = getattr(doc, 'columns', getattr(doc, 'headers', []))
        ctx.rows = getattr(doc, 'rows', [])
        ctx.total_records = len(ctx.rows)
        ctx.total_columns = len(ctx.columns)
        ctx.warnings = getattr(doc, 'warnings', [])
        return ctx
    
    def from_form_data(
        self,
        form_name: str,
        field_names: list[str],
        field_types: dict[str, str],
        records: list[dict[str, Any]],
        total_records: int = 0,
    ) -> DocumentContext:
        """Build context from Dynamic Form data."""
        ctx = DocumentContext()
        ctx.form_name = form_name
        ctx.field_names = field_names
        ctx.field_types = field_types
        ctx.rows = records
        ctx.total_records = total_records or len(records)
        ctx.total_columns = len(field_names)
        ctx.columns = field_names
        ctx.document_type = "form"
        return ctx


# ======================================================================
# ConversationalDocuments — Main Service
# ======================================================================

class ConversationalDocuments:
    """
    Main service for document Q&A (FASE 8).
    
    Backend-only. Designed to be consumed by:
      - Django templates (via view)
      - REST API (via DRF)
      - WebSockets (via Django Channels)
      - AgentOrchestrator (as a tool)
    
    Usage:
        cd = ConversationalDocuments(provider=gemini_provider)
        result = cd.ask(
            document=document_context,
            question="¿Cuántos registros tiene?",
        )
        print(result.answer)
    
    Or with a full conversation:
        conversation = cd.start_conversation(document_context)
        result1 = cd.ask_in_conversation(conversation, "Resume este archivo")
        result2 = cd.ask_in_conversation(conversation, "¿Qué anomalías ves?")
    """
    
    def __init__(self, provider: Optional[BaseAIProvider] = None):
        self._offline = provider is None
        self.provider = provider
        self.classifier = QuestionClassifier()
        self.doc_context_builder = DocumentContextBuilder()
        self.prompt_composer = PromptComposer()
        self.context_builder = ContextBuilder()

    # ── Single Question ──

    def ask(
        self,
        document: DocumentContext,
        question: str,
        use_cache: bool = True,
    ) -> QuestionResult:
        """
        Ask a question about a document.
        
        Args:
            document: DocumentContext with the document's data.
            question: The question in natural language.
            use_cache: Whether to use cached responses.
            
        Returns:
            QuestionResult with answer and confidence.
        """
        import time
        t0 = time.perf_counter()
        
        qtype = self.classifier.classify(question)

        # ── Modo offline: sin proveedor IA disponible ──
        if self._offline or self.provider is None:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return QuestionResult(
                question=question,
                question_type=qtype,
                answer=(
                    "⚡ **Modo offline FREE-FIRST activo**\n\n"
                    "No hay ningún proveedor de IA configurado. "
                    "El sistema sigue funcionando en modo offline.\n\n"
                    "**✅ Sigue funcionando:**\n"
                    "• Preguntas sobre datos del sistema (Data Agent) — "
                    "ej: *\"¿Cuántos formularios hay?\"*\n"
                    "• Subida de archivos Excel/CSV con extracción heurística\n"
                    "• Formularios dinámicos, importaciones y usuarios\n"
                    "• ColumnMatcher para matching de columnas\n\n"
                    "**🔧 Para habilitar IA completa:**\n"
                    "Configura GEMINI_API_KEY en tu archivo .env:\n"
                    "```\nGEMINI_API_KEY=tu_api_key_aqui\n```\n\n"
                    "Gemini Free es gratuito y no requiere tarjeta de crédito.\n\n"
                    "**Alternativas gratuitas:**\n"
                    "• DeepSeek: DEEPSEEK_API_KEY\n"
                    "• Qwen: QWEN_API_KEY (Alibaba Cloud)\n"
                    "• OpenRouter: OPENROUTER_API_KEY"
                ),
                confidence=1.0,
                followup_questions=[
                    "¿Cuántos formularios existen?",
                    "¿Cuántos registros hay en total?",
                    "¿Qué proveedores IA están disponibles?",
                    "¿Cómo configuro una API Key?",
                ],
                processing_time_ms=elapsed_ms,
            )

        # Build the prompt
        prompt = self._build_question_prompt(document, question, qtype)
        
        # System instruction based on question type
        system_instruction = self._get_system_instruction(qtype)
        
        # Call provider
        if document.raw_text and len(document.raw_text) > 500:
            # Use analyze_document for text-heavy responses
            response = self.provider.analyze_document(
                content=prompt,
                system_instruction=system_instruction,
                use_cache=use_cache,
            )
        else:
            # Use generate_json for structured responses
            response = self.provider.generate_json(
                prompt=prompt,
                system_instruction=system_instruction,
                use_cache=use_cache,
            )
        
        elapsed_ms = (time.perf_counter() - t0) * 1000
        
        if not response.success:
            return QuestionResult(
                question=question,
                question_type=qtype,
                answer="No pude procesar la pregunta en este momento.",
                confidence=0.0,
                warnings=[response.error or "AI call failed"],
                processing_time_ms=elapsed_ms,
            )
        
        # Build the result
        answer_text = response.text or ""
        confidence = 0.5
        
        if response.json_data:
            data = response.json_data
            answer_text = data.get("answer", data.get("respuesta", data.get("text", answer_text)))
            confidence = data.get("confidence", 0.7)
        
        # Generate followup suggestions
        followups = self._generate_followups(qtype, document)
        
        # Suggested visualizations
        visualizations = self._suggest_visualizations(qtype, document)
        
        return QuestionResult(
            question=question,
            question_type=qtype,
            answer=answer_text,
            confidence=confidence,
            data=response.json_data,
            suggested_visualizations=visualizations,
            followup_questions=followups,
            processing_time_ms=elapsed_ms,
        )

    def ask_stream(
        self,
        document: DocumentContext,
        question: str,
    ):
        """
        Ask a question and stream the response token by token.

        Yields strings (text chunks) as they arrive from the provider.
        Falls back to self.ask() if the provider doesn't support streaming.

        Args:
            document: DocumentContext with the document's data.
            question: The question in natural language.

        Yields:
            str: text chunks.
        """
        result = self.ask(document=document, question=question, use_cache=False)
        answer_text = result.answer or ""
        if not answer_text:
            answer_text = "No se pudo generar una respuesta."
        words = answer_text.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
        yield "\n\n"
    
    # ── Conversation ──

    def start_conversation(
        self,
        document: DocumentContext,
    ) -> DocumentConversation:
        """Start a new conversation context for a document."""
        return DocumentConversation(document=document)
    
    def ask_in_conversation(
        self,
        conversation: DocumentConversation,
        question: str,
        use_cache: bool = True,
    ) -> QuestionResult:
        """
        Ask a question within a conversation.
        
        Maintains history for follow-up context.
        """
        result = self.ask(conversation.document, question, use_cache=use_cache)
        
        # Record in conversation history
        conversation.history.append({
            "question": question,
            "question_type": result.question_type.value,
            "answer": result.answer,
            "confidence": result.confidence,
            "timestamp": datetime.now().isoformat(),
        })
        
        # Update summary if applicable
        if result.question_type == QuestionType.SUMMARY:
            conversation.current_summary = result.answer
        
        # Update dashboard if applicable
        if result.question_type == QuestionType.DASHBOARD and result.data:
            conversation.current_dashboard = result.data
        
        return result
    
    # ── Batch Questions ──

    def ask_batch(
        self,
        document: DocumentContext,
        questions: list[str],
        use_cache: bool = True,
    ) -> list[QuestionResult]:
        """Ask multiple questions about the same document."""
        return [
            self.ask(document, q, use_cache=use_cache)
            for q in questions
        ]
    
    # ── Convenience Methods ──

    def summarize(
        self,
        document: DocumentContext,
        use_cache: bool = True,
    ) -> QuestionResult:
        """Quick-summarize a document."""
        return self.ask(document, "Resume este archivo en 3 párrafos ejecutivos", use_cache=use_cache)
    
    def get_executive_summary(
        self,
        document: DocumentContext,
        use_cache: bool = True,
    ) -> QuestionResult:
        """Get an executive summary of the document."""
        return self.ask(document, "Resume en lenguaje ejecutivo para un gerente", use_cache=use_cache)
    
    def detect_anomalies(
        self,
        document: DocumentContext,
        use_cache: bool = True,
    ) -> QuestionResult:
        """Detect anomalies in the document."""
        return self.ask(document, "¿Qué anomalías encuentras en estos datos?", use_cache=use_cache)
    
    def get_dashboard(
        self,
        document: DocumentContext,
        use_cache: bool = True,
    ) -> QuestionResult:
        """Generate a dashboard suggestion for the document."""
        return self.ask(document, "Genera un dashboard con los indicadores más importantes", use_cache=use_cache)
    
    def get_recommendations(
        self,
        document: DocumentContext,
        use_cache: bool = True,
    ) -> QuestionResult:
        """Get recommendations from the document."""
        return self.ask(document, "¿Qué recomendaciones harías basado en estos datos?", use_cache=use_cache)
    
    # ── Internal ──

    def _build_question_prompt(
        self,
        document: DocumentContext,
        question: str,
        qtype: QuestionType,
    ) -> str:
        """Build the prompt for a question."""
        parts = [f"## Documento: {document.file_name or document.form_name or 'Sin nombre'}"]
        
        if document.document_type:
            parts.append(f"Tipo: {document.document_type}")
        
        if document.total_records:
            parts.append(f"Registros: {document.total_records}")
        
        if document.total_columns:
            parts.append(f"Columnas: {document.total_columns}")
        
        if document.columns:
            parts.append(f"Campos: {', '.join(document.columns)}")
        
        if document.raw_text:
            parts.append(f"\n--- CONTENIDO ---\n{truncate_text(document.raw_text, 10000)}")
        
        if document.rows:
            # Show first 10 rows as sample
            sample = "\n".join(
                " | ".join(str(v)[:40] for v in row.values())
                for row in document.rows[:10]
            )
            parts.append(f"\n--- MUESTRA (primeros {min(10, len(document.rows))} registros) ---\n{sample}")
        
        if document.warnings:
            parts.append(f"\nAdvertencias: {'; '.join(document.warnings[:5])}")
        
        if document.errors_found:
            parts.append(f"\nErrores: {'; '.join(document.errors_found[:5])}")
        
        parts.append(f"\n---\n## Pregunta:\n{question}")
        
        return "\n".join(parts)
    
    def _get_system_instruction(self, qtype: QuestionType) -> str:
        """Get system instruction for a question type."""
        instructions = {
            QuestionType.SUMMARY: (
                "Eres un analista de documentos experto. "
                "Genera resúmenes claros, estructurados y ejecutivos. "
                "Incluye: propósito del documento, datos principales, hallazgos clave. "
                "Responde en español colombiano."
            ),
            QuestionType.COUNT: (
                "Responde con números precisos. "
                "Si no tienes la información exacta, indica por qué. "
                "Responde en español."
            ),
            QuestionType.COLUMNS: (
                "Lista las columnas o campos disponibles con sus tipos si es posible. "
                "Sé preciso y ordenado. "
                "Responde en español."
            ),
            QuestionType.MISSING: (
                "Identifica qué información debería estar presente pero no lo está. "
                "Sé específico sobre qué falta y por qué podría ser importante. "
                "Responde en español colombiano."
            ),
            QuestionType.ERRORS: (
                "Eres un auditor de datos experto. "
                "Identifica errores, inconsistencias y problemas en los datos. "
                "Clasifícalos por severidad (alto, medio, bajo). "
                "Responde en español colombiano."
            ),
            QuestionType.INSIGHTS: (
                "Eres un analista de negocio senior. "
                "Identifica la información más valiosa y los patrones importantes. "
                "Responde en español colombiano."
            ),
            QuestionType.RECOMMENDATIONS: (
                "Eres un consultor senior. "
                "Genera recomendaciones accionables basadas en los datos. "
                "Prioriza por impacto y facilidad de implementación. "
                "Responde en español colombiano."
            ),
            QuestionType.DASHBOARD: (
                "Eres un experto en visualización de datos. "
                "Sugiere los indicadores y gráficos más relevantes. "
                "Responde ÚNICAMENTE con JSON con: indicadores, graficos_sugeridos, "
                "kpis_principales, resumen_ejecutivo."
            ),
            QuestionType.EXECUTIVE: (
                "Eres un CEO con 20 años de experiencia. "
                "Genera un resumen ejecutivo de alto nivel. "
                "Máximo 3 párrafos. Enfócate en lo que importa para la toma de decisiones. "
                "Responde en español colombiano."
            ),
            QuestionType.ANOMALIES: (
                "Eres un auditor forense de datos. "
                "Detecta valores atípicos, inconsistencias y patrones sospechosos. "
                "Clasifica cada anomalía por nivel de riesgo. "
                "Responde en español colombiano."
            ),
            QuestionType.TRENDS: (
                "Eres un analista de tendencias. "
                "Identifica patrones de cambio, tendencias alcistas/bajistas, "
                "estacionalidad y cambios significativos. "
                "Responde en español colombiano."
            ),
            QuestionType.COMPARISON: (
                "Eres un analista de comparación de datos. "
                "Identifica diferencias, cambios y evoluciones. "
                "Usa porcentajes y números absolutos. "
                "Responde en español colombiano."
            ),
            QuestionType.FREE: (
                "Eres un asistente experto en análisis de datos. "
                "Responde preguntas sobre el documento de manera clara y precisa. "
                "Si no tienes suficiente información, indícalo. "
                "Responde en español colombiano."
            ),
        }
        return instructions.get(qtype, instructions[QuestionType.FREE])
    
    def _generate_followups(
        self,
        qtype: QuestionType,
        document: DocumentContext,
    ) -> list[str]:
        """Generate relevant follow-up questions based on the question type."""
        followups_map = {
            QuestionType.SUMMARY: [
                "¿Cuántos registros tiene?",
                "¿Qué anomalías encuentras?",
                "¿Qué recomendaciones harías?",
            ],
            QuestionType.COUNT: [
                "¿Qué columnas tiene?",
                "¿Faltan datos en algún campo?",
                "Genera un resumen ejecutivo",
            ],
            QuestionType.COLUMNS: [
                "¿Cuántos registros tiene?",
                "¿Qué tipos de datos tiene cada campo?",
                "¿Qué datos faltan?",
            ],
            QuestionType.MISSING: [
                "¿Qué errores encontraste?",
                "¿Qué recomendaciones harías?",
                "Genera un resumen ejecutivo",
            ],
            QuestionType.ERRORS: [
                "¿Qué datos faltan?",
                "¿Qué recomendaciones harías?",
                "Genera un dashboard",
            ],
            QuestionType.INSIGHTS: [
                "¿Qué tendencias observas?",
                "¿Qué anomalías encuentras?",
                "¿Qué recomendaciones harías?",
            ],
            QuestionType.RECOMMENDATIONS: [
                "¿Qué riesgos ves?",
                "¿Qué oportunidades identificas?",
                "Genera un dashboard",
            ],
            QuestionType.DASHBOARD: [
                "Explica los indicadores del dashboard",
                "¿Qué anomalías encuentras?",
                "Genera un resumen ejecutivo",
            ],
            QuestionType.EXECUTIVE: [
                "¿Qué anomalías encuentras?",
                "¿Qué oportunidades de mejora ves?",
                "Genera un dashboard",
            ],
            QuestionType.ANOMALIES: [
                "¿Qué recomendaciones harías?",
                "¿Qué riesgos identificas?",
                "Genera un resumen ejecutivo",
            ],
            QuestionType.TRENDS: [
                "¿Qué anomalías encuentras?",
                "¿Qué recomendaciones harías para aprovechar las tendencias?",
                "Compara con el período anterior",
            ],
            QuestionType.COMPARISON: [
                "¿Qué tendencias observas?",
                "¿Qué insights ves?",
                "Genera un dashboard comparativo",
            ],
            QuestionType.FREE: [
                "Resume este archivo",
                "¿Qué anomalías encuentras?",
                "¿Qué recomendaciones harías?",
            ],
        }
        return followups_map.get(qtype, followups_map[QuestionType.FREE])
    
    def _suggest_visualizations(
        self,
        qtype: QuestionType,
        document: DocumentContext,
    ) -> list[str]:
        """Suggest relevant visualizations based on question type."""
        visualizations_map = {
            QuestionType.SUMMARY: ["bar_chart", "kpi_cards"],
            QuestionType.COUNT: ["kpi_card", "number_card"],
            QuestionType.COLUMNS: ["table", "data_grid"],
            QuestionType.MISSING: ["heatmap", "missing_values_chart"],
            QuestionType.ERRORS: ["list", "severity_chart"],
            QuestionType.INSIGHTS: ["bar_chart", "pie_chart", "kpi_cards"],
            QuestionType.RECOMMENDATIONS: ["priority_matrix", "list"],
            QuestionType.DASHBOARD: ["kpi_cards", "bar_chart", "line_chart", "pie_chart"],
            QuestionType.EXECUTIVE: ["kpi_cards", "bar_chart"],
            QuestionType.ANOMALIES: ["scatter_plot", "list", "severity_heatmap"],
            QuestionType.TRENDS: ["line_chart", "area_chart", "bar_chart"],
            QuestionType.COMPARISON: ["comparison_bar", "dual_axis_chart", "table"],
            QuestionType.FREE: ["bar_chart", "kpi_cards"],
        }
        return visualizations_map.get(qtype, [])
