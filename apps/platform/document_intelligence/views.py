"""
views.py — Document Intelligence Platform views.

Independent section with:
  - Dashboard: landing page with options
  - Create Form with AI: upload file → analyze → review → create
  - Scan Invoice: upload image/PDF → extract → review
  - History: view past AI analyses

PHASE 4 (Jun 28): AI Assistant improvements
  - ValorCampo added to Data Agent model whitelist
  - _FORM_ALIASES maps business terms (producto, venta, cliente) to form names
  - Data Agent queries Registro filtered by form (e.g., "productos" → Productos form)
  - ValorCampo enrichment: list queries show product names not "Registro #123"
  - Business data context: _build_system_context includes [DATOS DE NEGOCIO] section
    with product stock/price/category, sales revenue/count, client stats
  - Conversation memory: persistent DB storage via ConversationManager,
    replaces session-based di_chat_history; auto-summarization for long threads
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.platform.ai.models import AIAnalysisLog
from apps.platform.ai.services.conversation_manager import ConversationManager
from apps.platform.ai.providers import get_provider
from apps.platform.ai.services.ai_dashboard import get_ai_dashboard
from apps.platform.document_intelligence.services.pipeline import (
    DocumentIntelligencePipeline,
    PipelineConfig,
    PipelineResult,
)
from apps.platform.document_intelligence.services.memory_learner import MemoryLearner
from config.permissions import admin_required, es_administrador, rol_usuario

logger = logging.getLogger(__name__)

# ======================================================================
# FREE-FIRST: helpers de verificación de modo offline
# ======================================================================

def _check_ai_available() -> bool:
    """
    Verifica si al menos un proveedor IA tiene API Key configurada.
    
    Returns:
        False si ningún proveedor tiene API Key → sistema está en modo offline.
        True si al menos uno tiene API Key.
    """
    from django.conf import settings
    for key_attr in ["GEMINI_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "QWEN_API_KEY"]:
        if bool(getattr(settings, key_attr, "")):
            return True
    return False


def _offline_json_response(message: str = "", suggestions: list | None = None, status: int = 200) -> JsonResponse:
    """
    Respuesta JSON consistente para modo offline FREE-FIRST.
    NUNCA devuelve HTTP 500 cuando no hay API Keys.
    """
    return JsonResponse({
        "success": False,
        "mode": "offline",
        "message": message or (
            "⚡ **Modo offline FREE-FIRST activo**\n\n"
            "No hay proveedores de IA configurados. "
            "Las preguntas sobre datos del sistema (Data Agent) siguen funcionando.\n\n"
            "**✅ Ejemplos de preguntas que funcionan ahora:**\n"
            "• ¿Cuántos formularios existen?\n"
            "• ¿Cuántos registros hay?\n"
            "• Muéstrame las últimas importaciones\n"
            "• ¿Qué usuarios están activos?\n\n"
            "**🔧 Para habilitar OCR, Chat IA y análisis avanzados:**\n"
            "Configura GEMINI_API_KEY en tu archivo .env"
        ),
        "suggestions": suggestions or [
            "¿Cuántos formularios existen?",
            "¿Cuántos registros hay en total?",
            "Muéstrame las últimas importaciones",
            "Configura GEMINI_API_KEY en tu .env para IA completa",
        ],
    }, status=status)


_DI_SESSION_KEYS = ["di_pipeline_result", "di_import_ready", "di_catalog_suggestions"]

def _cleanup_di(request, *, delete_tmp_path=None):
    """Clean ALL DI session keys. Delete temp file if path provided.

    Call at:
      - Start of analyze (new file upload) — stale results disappear
      - After create_form new form success — pipeline_result stale, import_ready set
      - After create_form use_existing_form — full cleanup
      - After import_data (success and error) — full cleanup
      - All exception handlers

    delete_tmp_path: explicit path to delete (for import_data where
                     di_pipeline_result is already popped from create_form).
    """
    if delete_tmp_path:
        Path(delete_tmp_path).unlink(missing_ok=True)
    else:
        result_data = request.session.get("di_pipeline_result")
        if result_data and result_data.get("tmp_path"):
            Path(result_data["tmp_path"]).unlink(missing_ok=True)
    for key in _DI_SESSION_KEYS:
        request.session.pop(key, None)
    request.session.modified = True


def _get_ai_mode() -> dict:
    """
    Obtiene el estado del modo IA para mostrar en el dashboard.
    
    Returns:
        dict con: status (online/partial/offline),
                  configured_providers, available_count, message
    """
    from django.conf import settings
    providers_status = {}
    configured = 0
    total = 4
    
    for key, name in [
        ("GEMINI_API_KEY", "Gemini"),
        ("DEEPSEEK_API_KEY", "DeepSeek"),
        ("OPENROUTER_API_KEY", "OpenRouter"),
        ("QWEN_API_KEY", "Qwen"),
    ]:
        has_key = bool(getattr(settings, key, ""))
        providers_status[name.lower()] = {
            "configured": has_key,
            "name": name,
        }
        if has_key:
            configured += 1
    
    if configured == 0:
        status = "offline"
        message = "No hay APIs configuradas. Modo FREE-FIRST: Data Agent + heurísticas activos."
    elif configured < total:
        status = "partial"
        message = f"{configured}/{total} proveedores configurados."
    else:
        status = "online"
        message = "Todos los proveedores configurados."
    
    return {
        "status": status,
        "configured": configured,
        "total": total,
        "message": message,
        "providers": providers_status,
        "data_agent_activo": True,  # Siempre activo — es puramente heurístico
    }


# Allowed file types
ALLOWED_EXTENSIONS = {
    ".xlsx", ".csv", ".pdf",
    ".jpg", ".jpeg", ".png", ".webp",
    ".txt", ".json", ".xml",
}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB

# Cache for FieldType choices to avoid repeated DB queries
_TIPOS_CAMPO_CACHE = None


def _get_tipos_campo() -> dict[str, str]:
    """Get field type choices from the Campo model."""
    global _TIPOS_CAMPO_CACHE
    if _TIPOS_CAMPO_CACHE is None:
        from apps.platform.dynamic_forms.models import Campo
        _TIPOS_CAMPO_CACHE = dict(Campo.TIPOS)
    return _TIPOS_CAMPO_CACHE


def _validate_upload(file) -> str | None:
    """Validate uploaded file. Returns error message or None."""
    if not file:
        return "No file uploaded."
    if file.size == 0:
        return "Empty file."
    if file.size > MAX_UPLOAD_SIZE:
        return f"File too large ({file.size / 1024 / 1024:.1f} MB). Max: 50 MB."
    ext = Path(file.name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"Extension '{ext}' not supported. Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
    mime = (getattr(file, 'content_type', '') or '').lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": ["text/csv", "text/plain", "application/csv"],
        ".txt": "text/plain",
        ".json": "application/json",
    }
    expected_mime = mime_map.get(ext)
    if expected_mime and mime:
        if isinstance(expected_mime, list):
            if mime not in expected_mime:
                return f"MIME type '{mime}' does not match extension '{ext}'."
        elif mime != expected_mime and not mime.startswith("text/"):
            return f"MIME type '{mime}' does not match extension '{ext}'."
    return None


@login_required(login_url="login")
def dashboard(request):
    """
    Document Intelligence command center.
    
    Professional dashboard with comprehensive stats from:
      - AIDashboardService (AI usage, tokens, cache, budget)
      - SmartLearner (learnings, preferences)
      - MultiLevelCache (hit/miss by level)
    """
    dashboard_service = get_ai_dashboard()
    try:
        ai_data = dashboard_service.get_data(days=30)
    except Exception as e:
        logger.warning("Could not load AI stats: %s", e)
        ai_data = None

    # Últimos análisis
    try:
        recent_logs = AIAnalysisLog.objects.all().order_by("-created_at")[:10]
    except Exception:
        recent_logs = []

    ai_mode = _get_ai_mode()

    return render(request, "document_intelligence/dashboard.html", {
        "ai_data": ai_data,
        "recent_logs": recent_logs,
        "ai_mode": ai_mode,
        "es_admin": es_administrador(request.user),
        "rol_usuario": rol_usuario(request.user),
    })


@login_required(login_url="login")
@admin_required
def document_upload(request):
    """
    Punto de entrada ÚNICO para todos los documentos.
    
    Flujo E2E completo:
      1. Subir archivo o tomar foto
      2. Extraer + OCR + Pipeline AI
      3. Revisar en editor unificado
      4. Crear formulario + importar datos
      5. MemoryLearner aprende de correcciones
    
    Soporta: fotos, PDF, Excel, CSV, imágenes, TXT, XML, JSON
    """
    if request.method == "POST":
        action = request.POST.get("action", "analyze")

        if action == "analyze":
            return _handle_e2e_analyze(request)
        elif action == "create_form":
            return _handle_create_form(request, template_name="document_upload.html")
        elif action == "import_data":
            return _handle_import_data(request)

    # ── Verificar si hay un resultado previo en sesión (ej: desde scan_invoice) ──
    session_result = request.session.get("di_pipeline_result")
    if session_result:
        from apps.platform.dynamic_forms.models import Formulario as DF_Formulario
        fields_objects = _ai_fields_to_campo_objects(
            session_result.get("fields", [])
        )
        similar_forms = session_result.get("similar_forms", [])
        catalog_suggestions = request.session.get("di_catalog_suggestions", [])
        ctx = _document_upload_context(request)
        return render(request, "document_intelligence/document_upload.html", {
            **ctx,
            "result": session_result,
            "result_fields_objects": fields_objects,
            "similar_forms": similar_forms,
            "catalog_suggestions": catalog_suggestions,
            "formularios_disponibles": DF_Formulario.objects.all(),
        })

    tipos_campo = _get_tipos_campo()
    return render(request, "document_intelligence/document_upload.html", {
        "es_admin": es_administrador(request.user),
        "rol_usuario": rol_usuario(request.user),
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
        "tipos_campo": tipos_campo,
        "is_mobile": bool(request.headers.get("User-Agent", "").lower()
                         .find("mobile") >= 0),
    })


def _document_upload_context(request):
    """Shared context for document_upload renders."""
    return {
        "es_admin": es_administrador(request.user),
        "rol_usuario": rol_usuario(request.user),
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
        "tipos_campo": _get_tipos_campo(),
        "is_mobile": "mobile" in request.headers.get("User-Agent", "").lower(),
    }


@login_required(login_url="login")
@admin_required
def create_from_file(request):
    """
    Legacy wrapper — mantiene compatibilidad con URLs existentes.
    
    GET: redirige al nuevo document_upload.
    POST: delega a los handlers de document_upload (preserva datos POST).
    """
    if request.method == "POST":
        action = request.POST.get("action", "analyze")
        if action == "analyze":
            return _handle_e2e_analyze(request)
        elif action == "create_form":
            return _handle_create_form(request, template_name="create_from_file.html")
        elif action == "import_data":
            return _handle_import_data(request)
    return redirect("document_intelligence:document_upload")


def _handle_e2e_analyze(request):
    """
    E2E analyze: unified handler for ALL document types.
    
    El pipeline maneja OCR internamente (_step_ocr) para imágenes,
    clasificación, detección de estructura y propuesta de formulario.
    """
    _cleanup_di(request)
    ctx = _document_upload_context(request)

    file = request.FILES.get("document_file")
    error = _validate_upload(file)
    if error:
        messages.error(request, error)
        return render(request, "document_intelligence/document_upload.html", ctx)

    from django.conf import settings
    tmp_dir = Path(settings.BASE_DIR) / ".tmp_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{Path(file.name).name}"
    tmp_path = tmp_dir / safe_name
    with open(tmp_path, "wb") as f:
        for chunk in file.chunks():
            f.write(chunk)

    from apps.platform.ai.exceptions import ProviderNotAvailable
    
    # ── FREE-FIRST: si no hay IA, degradar con mensaje claro ──
    if not _check_ai_available():
        ext = Path(safe_name).suffix.lower()
        img_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
        if ext in img_exts or ext == ".pdf":
            messages.info(
                request,
                "🖼️ **OCR no disponible en modo offline.** "
                "Las imágenes y PDFs requieren Gemini API Key.\n\n"
                "**➡️ Configura GEMINI_API_KEY en tu archivo .env**\n\n"
                "Los archivos Excel y CSV siguen funcionando "
                "con extracción heurística sin necesidad de API Key."
            )
        elif ext in {".xlsx", ".xls", ".csv"}:
            # Extracción heurística real sin IA
            extracted_info = ""
            try:
                from apps.platform.document_intelligence.extractors import get_extractor
                extractor = get_extractor(file_path=tmp_path)
                extracted = extractor.extract_safe(tmp_path)
                if extracted and not extracted.is_empty:
                    cols = len(extracted.columns) if extracted.columns else 0
                    rows = len(extracted.rows) if extracted.rows else 0
                    extracted_info = f"\n\n**Extracción heurística completada:** {rows} filas, {cols} columnas detectadas."
            except Exception as e:
                logger.warning("Heuristic extraction failed: %s", e)
            
            messages.info(
                request,
                "📊 **Modo offline FREE-FIRST activo**"
                + extracted_info
                + "\n\n"
                "Puedes:\n"
                "• Crear formularios manualmente en Dynamic Forms\n"
                "• Importar datos con ColumnMatcher heurístico\n"
                "• Usar el **Data Agent** para consultar datos: "
                "*¿Cuántos formularios hay?*\n\n"
                "**➡️ Para habilitar análisis automático con IA:**\n"
                "Configura GEMINI_API_KEY en tu archivo .env. "
                "Gemini Free es gratuito."
            )
        else:
            messages.info(
                request,
                "⚡ **Modo offline FREE-FIRST activo**\n\n"
                "No hay proveedores de IA configurados. "
                "Configura GEMINI_API_KEY en tu .env para habilitar "
                "análisis automático de documentos con IA.\n\n"
                "Mientras tanto, puedes crear formularios manualmente "
                "en la sección de Dynamic Forms."
            )
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return render(request, "document_intelligence/document_upload.html", ctx)

    try:
        provider = get_provider()

        # ── Pipeline universal (incluye OCR para imágenes) ──
        pipeline = DocumentIntelligencePipeline(provider=provider)
        config = PipelineConfig(
            file_path=str(tmp_path),
            file_name=file.name,
            user_id=request.user.id,
            use_cache=True,
        )
        result = pipeline.run(config)

        if not result.success:
            messages.error(request, "; ".join(result.errors))
            _cleanup_di(request)
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return render(request, "document_intelligence/document_upload.html", ctx)

        # ── Almacenar resultado en sesión ──
        request.session["di_pipeline_result"] = _serialize_pipeline_result(result, tmp_path, file.name)

        # ── Similar form detection ──
        similar_forms = []
        if result.form_proposal and result.form_proposal.fields:
            try:
                from apps.platform.document_intelligence.services.form_similarity_finder import (
                    FormSimilarityFinder,
                )
                finder = FormSimilarityFinder()
                similar_forms = finder.find_similar(
                    [{"name": f.name} for f in result.form_proposal.fields]
                )
            except Exception as e:
                logger.warning("Similar form finder error: %s", e)

        # ── Catalog detection ──
        catalog_suggestions = []
        if result.extracted_doc and result.extracted_doc.rows:
            try:
                from apps.platform.document_intelligence.services.catalog_detector import CatalogDetector
                cd = CatalogDetector()
                catalog_results = cd.detect(result.extracted_doc)
                if catalog_results:
                    catalog_suggestions = [
                        {"column": s.column_name, "options": s.options, "confidence": s.confidence}
                        for s in catalog_results
                    ]
                    request.session["di_catalog_suggestions"] = catalog_suggestions
            except Exception as e:
                logger.warning("Catalog detection error: %s", e)

        from apps.platform.ai.utils import make_json_serializable
        request.session["di_pipeline_result"]["similar_forms"] = make_json_serializable(similar_forms)
        request.session.modified = True

        # ── Convertir campos para el editor unificado ──
        from apps.platform.dynamic_forms.models import Formulario as DF_Formulario
        result_data = request.session.get("di_pipeline_result", {})
        fields_campo_objects = _ai_fields_to_campo_objects(
            result_data.get("fields", [])
        ) if result_data else []

        return render(request, "document_intelligence/document_upload.html", {
            **ctx,
            "result": result_data,
            "result_fields_objects": fields_campo_objects,
            "similar_forms": similar_forms,
            "catalog_suggestions": catalog_suggestions,
            "formularios_disponibles": DF_Formulario.objects.all(),
        })

    except Exception as e:
        logger.exception("E2E analysis failed")
        messages.error(request, f"Analysis failed: {e}")
        _cleanup_di(request)
        if tmp_path.exists():
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        return render(request, "document_intelligence/document_upload.html", ctx)


def _serialize_pipeline_result(result, tmp_path, file_name):
    """Serialize PipelineResult to session-safe dict."""
    from apps.platform.ai.utils import make_json_serializable
    return make_json_serializable({
        "form_name": result.form_proposal.form_name if result.form_proposal else "",
        "form_description": result.form_proposal.form_description if result.form_proposal else "",
        "fields": [
            {
                "name": f.name,
                "type": f.suggested_type,
                "required": f.required,
                "unique": f.unique,
                "is_identifier": f.is_identifier,
                "order": f.order,
                "confidence": f.confidence,
                "explanation": f.explanation,
            }
            for f in (result.form_proposal.fields if result.form_proposal else [])
        ],
        "quality": {
            "stars": result.quality_score.stars if result.quality_score else 0,
            "label": result.quality_score.label if result.quality_score else "",
            "recommendations": result.quality_score.recommendations if result.quality_score else [],
            "risks": result.quality_score.risks if result.quality_score else [],
            "strengths": result.quality_score.strengths if result.quality_score else [],
        },
        "classification": result.classification.document_type if result.classification else "",
        "tmp_path": str(tmp_path),
        "file_name": file_name,
        "headers": list(result.extracted_doc.columns) if result and result.extracted_doc else [],
        "rows": list(result.extracted_doc.rows) if result and result.extracted_doc else [],
        "records": list(result.records) if result else [],
        "records_count": result.records_count if result else 0,
        "records_confidence": result.records_confidence if result else 0.0,
        "records_reason": result.records_reason or "",
    })


@login_required(login_url="login")
@admin_required
def scan_invoice(request):
    """
    Upload invoice image/PDF → pipeline → show proposal.
    
    Ahora reusa el pipeline universal (con OCR) en vez de
    InvoiceAnalyzer directamente. Si el pipeline detecta una
    factura, redirige al editor unificado con los datos precargados.
    """
    if request.method == "POST":
        _cleanup_di(request)
        file = request.FILES.get("invoice_file")
        error = _validate_upload(file)
        if error:
            messages.error(request, error)
            return render(request, "document_intelligence/scan_invoice.html", {
                "es_admin": es_administrador(request.user),
                "rol_usuario": rol_usuario(request.user),
            })

        from django.conf import settings
        tmp_dir = Path(settings.BASE_DIR) / ".tmp_uploads"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{uuid.uuid4().hex}_{Path(file.name).name}"
        tmp_path = tmp_dir / safe_name
        with open(tmp_path, "wb") as f:
            for chunk in file.chunks():
                f.write(chunk)

        # ── FREE-FIRST: si no hay IA, mensaje claro ──
        if not _check_ai_available():
            messages.info(
                request,
                "🖼️ **OCR de facturas no disponible en modo offline.**\n\n"
                "Las facturas requieren Gemini API Key para "
                "extraer proveedor, NIT, fechas, items, IVA y totales.\n\n"
                "**➡️ Configura GEMINI_API_KEY en tu archivo .env**\n\n"
                "Gemini Free es gratuito y soporta OCR de imágenes.\n"
                "GEMINI_API_KEY=tu_api_key_aqui"
            )
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return render(request, "document_intelligence/scan_invoice.html", {
                "es_admin": es_administrador(request.user),
                "rol_usuario": rol_usuario(request.user),
            })

        try:
            provider = get_provider()
            pipeline = DocumentIntelligencePipeline(provider=provider)
            config = PipelineConfig(
                file_path=str(tmp_path),
                file_name=file.name,
                user_id=request.user.id,
                use_cache=True,
            )
            result = pipeline.run(config)

            if not result.success:
                _cleanup_di(request)
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                messages.error(request, "; ".join(result.errors))
                return render(request, "document_intelligence/scan_invoice.html", {
                    "es_admin": es_administrador(request.user),
                    "rol_usuario": rol_usuario(request.user),
                })

            # ── Almacenar en sesión para el editor ──
            request.session["di_pipeline_result"] = _serialize_pipeline_result(result, tmp_path, file.name)

            # ── Aplicar MemoryLearner ──
            try:
                from apps.platform.document_intelligence.services.memory_learner import MemoryLearner
                learner = MemoryLearner()
                if result.form_proposal:
                    result.form_proposal = learner.apply_to_proposal(result.form_proposal)
            except Exception as e:
                logger.warning("MemoryLearner apply failed: %s", e)

            # ── Redirigir al editor unificado ──
            from django.shortcuts import redirect
            return redirect("document_intelligence:document_upload")

        except Exception as e:
            logger.exception("Invoice pipeline failed")
            messages.error(request, f"Invoice analysis failed: {e}")
            _cleanup_di(request)
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    return render(request, "document_intelligence/scan_invoice.html", {
        "es_admin": es_administrador(request.user),
        "rol_usuario": rol_usuario(request.user),
    })


@login_required(login_url="login")
def ai_chat(request):
    """
    Chat IA con documentos — punto de entrada al asistente conversacional.
    Se integra con ConversationalDocuments para responder preguntas
    sobre documentos ya analizados, formularios y registros.
    """
    # Build context for the template: available documents/forms to reference
    # Últimos documentos analizados
    recent_logs = []
    try:
        recent_logs = list(AIAnalysisLog.objects.filter(
            success=True
        ).order_by("-created_at").values(
            "id", "document_name", "document_type", "provider"
        )[:10])
    except Exception:
        pass

    # Formularios disponibles para preguntar
    forms = []
    try:
        from apps.platform.dynamic_forms.models import Formulario
        forms = list(Formulario.objects.all().values("id", "nombre")[:20])
    except Exception:
        pass

    stats_summary = ""
    try:
        dashboard = get_ai_dashboard().get_data(days=30)
        stats_summary = (
            f"{dashboard.total_calls} documentos analizados, "
            f"{dashboard.successful_calls} exitosos, "
            f"{dashboard.cached_calls} en caché, "
            f"{dashboard.total_prompt_tokens + dashboard.total_completion_tokens} tokens"
        )
    except Exception:
        pass

    return render(request, "document_intelligence/ai_chat.html", {
        "recent_logs": recent_logs,
        "forms": forms,
        "stats_summary": stats_summary,
        "es_admin": es_administrador(request.user),
        "rol_usuario": rol_usuario(request.user),
    })


# ── Metrics accumulators for Phase 7 ──
_chat_metrics = {
    "total_questions": 0,
    "heuristic_answers": 0,
    "orm_answers": 0,
    "ai_answers": 0,
    "total_time_ms": 0.0,
    "by_provider": {},
    "by_intent": {},
    "fallback_used": 0,
}


def _record_chat_metrics(intent_type: str, source: str, elapsed_ms: float, provider: str = ""):
    """Record internal chat metrics (no dashboard, just logging)."""
    _chat_metrics["total_questions"] += 1
    if source == "heuristic":
        _chat_metrics["heuristic_answers"] += 1
    elif source == "orm":
        _chat_metrics["orm_answers"] += 1
    elif source == "ai":
        _chat_metrics["ai_answers"] += 1
    _chat_metrics["total_time_ms"] += elapsed_ms
    _chat_metrics["by_intent"][intent_type] = _chat_metrics["by_intent"].get(intent_type, 0) + 1
    if provider:
        _chat_metrics["by_provider"][provider] = _chat_metrics["by_provider"].get(provider, 0) + 1

    # Log summary every 10 questions
    total = _chat_metrics["total_questions"]
    if total > 0 and total % 10 == 0:
        h_pct = (_chat_metrics["heuristic_answers"] + _chat_metrics["orm_answers"]) / total * 100
        ai_pct = _chat_metrics["ai_answers"] / total * 100
        avg_ms = _chat_metrics["total_time_ms"] / total
        logger.info(
            "CHAT METRICS [%d questions]: Heuristic/ORM=%.0f%% AI=%.0f%% Avg=%.0fms "
            "Fallbacks=%d Providers=%s",
            total, h_pct, ai_pct, avg_ms,
            _chat_metrics["fallback_used"],
            _chat_metrics["by_provider"],
        )


def _plan_recovery_suggestion(tool_name: str) -> str:
    """Generate a recovery suggestion for a failed plan step."""
    suggestions = {
        "import_records": "Verifica que el archivo Excel sea valido y que los campos coincidan con el formulario.",
        "create_form": "Verifica que el nombre del formulario no exista ya en el sistema.",
        "analyze_document": "Verifica que el documento sea legible y este en un formato soportado.",
        "inventory_queries": "Verifica que existan productos con datos de inventario registrados.",
        "sales_queries": "Verifica que existan ventas registradas en el sistema.",
        "search_records": "Verifica que el formulario exista y tenga registros.",
        "search_forms": "Verifica que haya formularios activos en el sistema.",
        "export_records": "Verifica que el formulario tenga registros para exportar.",
    }
    return suggestions.get(tool_name, "Revisa los parametros e intenta de nuevo.")


def ai_chat_ask(request):
    """
    AJAX endpoint for chat questions.
    
    PHASE 7 — Unified Decision Flow:
      1. OfflineFirstEngine → check connectivity
      2. DecisionEngine.classify_chat() → detect intent
      3. Data Agent → safe ORM for data queries
      4. AI Provider → for general_chat or complex queries
      5. SmartLearner → record every interaction
      6. Metrics → track heuristic/ORM/AI split
    
    Accepts POST with JSON:
      {"question": "...", "document_id": null}
    
    Returns JSON:
      {"answer": "...", "confidence": 0.9, "question_type": "...",
       "followups": [...], "visualizations": [...]}
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    import json
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        body = {}

    question = body.get("question", "").strip()
    if not question:
        return JsonResponse({"error": "Question is required"}, status=400)

    conversation_id = body.get("conversation_id")
    conversation = None
    if conversation_id:
        conversation = ConversationManager.get_conversation(conversation_id, request.user)
    if conversation is None:
        conversation = ConversationManager.create_conversation(
            request.user, title=question[:80],
        )

    from apps.platform.ai.services.decision_engine import get_decision_engine
    from apps.platform.ai.services.offline_first import get_offline_first_engine

    t0 = time.perf_counter()

    # ════════════════════════════════════════════════════════════════
    # STEP 0 — OfflineFirstEngine: check connectivity
    # ════════════════════════════════════════════════════════════════
    offline_engine = get_offline_first_engine()
    connectivity = offline_engine.monitor.get_status()
    is_online = connectivity.value == "online"

    # ════════════════════════════════════════════════════════════════
    # STEP 1 — DecisionEngine.classify_chat(): classify intent
    # ════════════════════════════════════════════════════════════════
    decision_engine = get_decision_engine()
    intent = decision_engine.classify_chat(question)

    logger.info(
        "Chat: intent=%s sub_intent=%s model=%s alias=%s confidence=%.2f can_no_ai=%s",
        intent.intent_type, intent.sub_intent, intent.target_model,
        intent.form_alias, intent.confidence, intent.can_answer_without_ai,
    )

    # ════════════════════════════════════════════════════════════════
    # STEP 2 — Route based on intent
    # ════════════════════════════════════════════════════════════════
    from apps.platform.ai.services.smart_learner import SmartLearner
    smart_learner = SmartLearner()

    # ── 2a. DATA_QUERY → Data Agent (ORM only, no AI) ──
    if intent.intent_type == "data_query":
        data_result = _try_data_query(intent, question)
        elapsed = (time.perf_counter() - t0) * 1000
        _record_chat_metrics(intent.sub_intent or "data_query", "orm", elapsed)

        # SmartLearner: record chat
        try:
            smart_learner.record_chat(
                question=question,
                answer=data_result.get("answer", ""),
                intent_type=intent.intent_type,
                sub_intent=intent.sub_intent,
                was_ai=False,
                confidence=intent.confidence,
                response_time_ms=elapsed,
                success=True,
            )
        except Exception:
            pass

        ConversationManager.add_message(
            conversation, role="user", content=question,
            intent=intent.intent_type, source="user",
        )
        ConversationManager.add_message(
            conversation, role="assistant", content=data_result.get("answer", ""),
            intent=intent.sub_intent or "data_query",
            provider="orm", source="data_agent",
            confidence=intent.confidence, execution_time=elapsed,
        )
        data_result["conversation_id"] = conversation.id
        return JsonResponse(data_result)

    # ── 2b. DOCUMENT_QUESTION → Show recent analyses ──
    if intent.intent_type == "document_question":
        try:
            recent = AIAnalysisLog.objects.filter(usuario=request.user).order_by("-created_at")[:5]
            if recent.exists():
                lines = [f"**Últimos {len(recent)} análisis:**"]
                for r in recent:
                    status = "OK" if r.success else "FAIL"
                    lines.append(f"  • {r.created_at.strftime('%Y-%m-%d %H:%M')} — {r.document_type or 'documento'} [{status}]")
                answer = "\n".join(lines)
            else:
                answer = "No hay análisis recientes. Sube un documento para comenzar."
        except Exception:
            answer = "No se pudieron recuperar los análisis recientes."

        elapsed = (time.perf_counter() - t0) * 1000
        _record_chat_metrics("document_question", "heuristic", elapsed)
        ConversationManager.add_message(
            conversation, role="user", content=question,
            intent=intent.intent_type, source="user",
        )
        ConversationManager.add_message(
            conversation, role="assistant", content=answer,
            intent="document_question", provider="heuristic", source="heuristic",
            confidence=0.8, execution_time=elapsed,
        )
        return JsonResponse({
            "answer": answer,
            "confidence": 0.8,
            "question_type": "document_question",
            "conversation_id": conversation.id,
            "followups": ["¿Cuántos documentos hay?", "Sube un nuevo documento"],
            "visualizations": ["kpi_card"],
            "processing_time_ms": round(elapsed, 1),
        })

    # ── 2c. FORM_CREATION → Show creation guide ──
    if intent.intent_type == "form_creation":
        elapsed = (time.perf_counter() - t0) * 1000
        _record_chat_metrics("form_creation", "heuristic", elapsed)
        answer = (
            "Para crear un formulario nuevo, usa la opción "
            "**Crear Formulario** en el menú o sube un archivo Excel/PDF "
            "desde **Document Intelligence** para que el sistema analice "
            "la estructura automáticamente."
        )
        ConversationManager.add_message(
            conversation, role="user", content=question,
            intent=intent.intent_type, source="user",
        )
        ConversationManager.add_message(
            conversation, role="assistant", content=answer,
            intent="form_creation", provider="heuristic", source="heuristic",
            confidence=0.9, execution_time=elapsed,
        )
        return JsonResponse({
            "answer": answer,
            "confidence": 0.9,
            "question_type": "form_creation",
            "conversation_id": conversation.id,
            "followups": [
                "¿Cómo analizar un documento?",
                "Muéstrame los formularios existentes",
            ],
            "visualizations": [],
            "processing_time_ms": round(elapsed, 1),
        })

    # ── 2d. GENERAL_CHAT (or unknown) → AI Provider ──
    # Fallback: offline or AI
    if not is_online:
        _chat_metrics["fallback_used"] += 1
        elapsed = (time.perf_counter() - t0) * 1000
        _record_chat_metrics("general_chat", "heuristic", elapsed)

        offline_answer = (
            "No tengo conexión a internet en este momento.\n\n"
            "Puedo responder preguntas sobre datos del sistema:\n"
            "  • ¿Cuántos productos hay?\n"
            "  • ¿Cuántas ventas se registraron?\n"
            "  • Muéstrame los clientes\n"
            "  • ¿Qué formularios existen?"
        )
        ConversationManager.add_message(
            conversation, role="user", content=question,
            intent=intent.intent_type, source="user",
        )
        ConversationManager.add_message(
            conversation, role="assistant", content=offline_answer,
            intent="offline", provider="heuristic", source="heuristic",
            confidence=0.5, execution_time=elapsed,
        )
        return JsonResponse({
            "answer": offline_answer,
            "confidence": 0.5,
            "conversation_id": conversation.id,
            "question_type": "offline",
            "followups": [
                "¿Cuántos productos hay?",
                "¿Cuántas ventas se registraron?",
                "¿Cuántos formularios existen?",
            ],
            "visualizations": [],
            "processing_time_ms": round(elapsed, 1),
        })

    # ── Online: use AI provider ──
    if not _check_ai_available():
        elapsed = (time.perf_counter() - t0) * 1000
        _record_chat_metrics("general_chat", "heuristic", elapsed)
        return _offline_json_response(
            message=(
                "⚡ **Modo offline FREE-FIRST activo**\n\n"
                "No hay proveedores de IA configurados. "
                "Las preguntas sobre datos del sistema siguen funcionando.\n\n"
                "**Preguntas que funcionan ahora:**\n"
                "  • ¿Cuántos formularios existen?\n"
                "  • ¿Cuántos registros hay?\n"
                "  • Muéstrame las últimas importaciones\n"
                "  • ¿Qué formulario tiene más registros?\n\n"
                "**Para habilitar Chat IA completo:**\n"
                "Configura GEMINI_API_KEY en tu archivo .env"
            ),
            suggestions=[
                "¿Cuántos formularios existen?",
                "¿Cuántos registros hay en total?",
                "Muéstrame las últimas importaciones",
                "¿Qué proveedores IA están disponibles?",
            ],
        )

    from apps.platform.ai.services.conversational_documents import (
        ConversationalDocuments, DocumentContext, QuestionType,
    )
    from apps.platform.ai.services.provider_router import get_provider_router
    from apps.platform.ai.types import ProviderType

    # Build DocumentContext
    doc_ctx = _build_chat_context(request)

    # Route to appropriate provider
    router = get_provider_router()
    route = router.route(task=question, task_type="chat")

    provider = None
    provider_name = "none"
    if not route.is_heuristic:
        try:
            provider_type = ProviderType.from_string(route.selected_provider)
            provider = get_provider(provider_type=provider_type)
            provider_name = route.selected_provider
        except Exception:
            provider = None
            _chat_metrics["fallback_used"] += 1

    cd = ConversationalDocuments(provider=provider)
    system_context = _build_system_context(request)

    # Conversation memory via ConversationManager
    context_str = ConversationManager.build_context(
        conversation, system_context=system_context,
    )
    enriched_question = f"{context_str}\n\n---\n\n## Pregunta del usuario:\n{question}"

    t1 = time.perf_counter()
    try:
        result = cd.ask(
            document=doc_ctx,
            question=enriched_question,
            use_cache=False,
        )
        ai_success = True
    except Exception as e:
        logger.warning("AI provider failed: %s", e)
        _chat_metrics["fallback_used"] += 1
        result = type("obj", (object,), {
            "answer": "Lo siento, no pude generar una respuesta en este momento. Intenta de nuevo.",
            "confidence": 0.3,
            "question_type": QuestionType.GENERAL,
            "followup_questions": [],
            "suggested_visualizations": [],
            "processing_time_ms": 0,
        })()
        ai_success = False

    ai_elapsed = (time.perf_counter() - t1) * 1000
    total_elapsed = (time.perf_counter() - t0) * 1000
    _record_chat_metrics("general_chat", "ai", ai_elapsed, provider=provider_name)

    # SmartLearner: record provider run
    try:
        smart_learner.record_provider_run(
            provider=provider_name,
            task_type="chat",
            confidence=result.confidence,
            time_ms=ai_elapsed,
            success=ai_success,
        )
        smart_learner.record_prompt_run(
            prompt_name="chat_ask",
            task_type="chat",
            confidence=result.confidence,
        )
        smart_learner.record_chat(
            question=question,
            answer=result.answer,
            intent_type=intent.intent_type,
            sub_intent=intent.sub_intent,
            was_ai=True,
            confidence=result.confidence,
            response_time_ms=ai_elapsed,
            success=ai_success,
            provider=provider_name,
        )
    except Exception:
        pass

    # Store Q&A in conversation history
    ConversationManager.add_message(
        conversation, role="user", content=question,
        intent=intent.intent_type, source="user",
    )
    ConversationManager.add_message(
        conversation, role="assistant", content=result.answer,
        intent=intent.sub_intent or "general_chat",
        provider=provider_name, source="ai",
        confidence=float(result.confidence) if hasattr(result, "confidence") else 0.7,
        execution_time=ai_elapsed,
    )

    return JsonResponse({
        "answer": result.answer,
        "confidence": result.confidence,
        "question_type": (result.question_type.value if hasattr(result.question_type, "value")
                          else "general_chat"),
        "conversation_id": conversation.id,
        "followups": getattr(result, "followup_questions", [])[:3],
        "visualizations": getattr(result, "suggested_visualizations", [])[:3],
        "processing_time_ms": round(total_elapsed, 1),
    })


def _sse_event(event: str, data: object) -> str:
    """Format an SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def ai_chat_stream(request):
    """
    SSE streaming chat endpoint.

    Uses the same decision flow as ai_chat_ask but streams
    responses via Server-Sent Events for progressive rendering.

    Events:
      status  — {"status": "analyzing"|"searching"|"generating"|"error"}
      source  — {"source": "heuristic"|"data_agent"|"ai_provider", "provider": "gemini"|...}
      token   — {"text": "..."}
      meta    — {"confidence": ..., "processing_time_ms": ..., "followups": [...]}
      done    — {"metrics": {"total_ms": ..., "tokens": ..., "tokens_per_sec": ...}}
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        body = {}

    question = body.get("question", "").strip()
    if not question:
        return JsonResponse({"error": "Question is required"}, status=400)

    conversation_id = body.get("conversation_id")
    conversation = None
    if conversation_id:
        conversation = ConversationManager.get_conversation(conversation_id, request.user)
    if conversation is None:
        conversation = ConversationManager.create_conversation(
            request.user, title=question[:80],
        )

    from apps.platform.ai.services.decision_engine import get_decision_engine
    from apps.platform.ai.services.offline_first import get_offline_first_engine
    from apps.platform.ai.services.smart_learner import SmartLearner

    t0 = time.perf_counter()

    def stream():
        total_tokens = 0
        first_token_time = None
        intent_info = ""
        source_type = "heuristic"
        provider_name = "none"
        last_message_id = None

        try:
            # ════════════════════════════════════════════
            # STEP 0 — Offline check
            # ════════════════════════════════════════════
            offline_engine = get_offline_first_engine()
            connectivity = offline_engine.monitor.get_status()
            is_online = connectivity.value == "online"

            # ════════════════════════════════════════════
            # STEP 1 — Classify intent
            # ════════════════════════════════════════════
            yield _sse_event("status", {"status": "analyzing"})

            decision_engine = get_decision_engine()
            intent = decision_engine.classify_chat(question)

            intent_info = f"{intent.intent_type}/{intent.sub_intent}"
            logger.info(
                "Stream chat: intent=%s sub_intent=%s model=%s alias=%s confidence=%.2f",
                intent.intent_type, intent.sub_intent, intent.target_model,
                intent.form_alias, intent.confidence,
            )

            smart_learner = SmartLearner()

            # Persist user message
            ConversationManager.add_message(
                conversation, role="user", content=question,
                intent=intent.intent_type, source="user",
            )

            # ════════════════════════════════════════════
            # STEP 2 — DATA_QUERY → Data Agent
            # ════════════════════════════════════════════
            if intent.intent_type == "data_query":
                yield _sse_event("status", {"status": "searching"})
                yield _sse_event("source", {"source": "data_agent", "provider": "orm"})
                source_type = "orm"

                data_result = _try_data_query(intent, question)
                answer = data_result.get("answer", "")

                elapsed = (time.perf_counter() - t0) * 1000
                _record_chat_metrics(intent.sub_intent or "data_query", "orm", elapsed)

                words = answer.split(" ")
                for i, word in enumerate(words):
                    if total_tokens == 0:
                        first_token_time = time.perf_counter()
                    yield _sse_event("token", {"text": word + (" " if i < len(words) - 1 else "")})
                    total_tokens += 1

                yield _sse_event("meta", {
                    "confidence": data_result.get("confidence", 0.95),
                    "processing_time_ms": round(elapsed, 1),
                    "followups": data_result.get("followups", [])[:3],
                    "token_count": total_tokens,
                })

                try:
                    smart_learner.record_chat(
                        question=question, answer=answer,
                        intent_type=intent.intent_type, sub_intent=intent.sub_intent,
                        was_ai=False, confidence=intent.confidence,
                        response_time_ms=elapsed, success=True,
                    )
                except Exception:
                    pass

                last_assistant_msg = ConversationManager.add_message(
                    conversation, role="assistant", content=answer,
                    intent=intent.sub_intent or "data_query",
                    provider="orm", source="data_agent",
                    confidence=data_result.get("confidence", 0.95),
                    execution_time=elapsed, token_count=total_tokens,
                )
                if last_assistant_msg:
                    last_message_id = last_assistant_msg.id

            # ════════════════════════════════════════════
            # STEP 3 — Heuristic intents
            # ════════════════════════════════════════════
            elif intent.intent_type in ("document_question", "form_creation"):
                yield _sse_event("status", {"status": "generating"})
                yield _sse_event("source", {"source": "heuristic", "provider": "none"})

                if intent.intent_type == "document_question":
                    try:
                        recent = AIAnalysisLog.objects.filter(usuario=request.user).order_by("-created_at")[:5]
                        if recent.exists():
                            lines = [f"**Últimos {len(recent)} análisis:**"]
                            for r in recent:
                                status_tag = "OK" if r.success else "FAIL"
                                lines.append(f"  • {r.created_at.strftime('%Y-%m-%d %H:%M')} — {r.document_type or 'documento'} [{status_tag}]")
                            answer = "\n".join(lines)
                        else:
                            answer = "No hay análisis recientes. Sube un documento para comenzar."
                    except Exception:
                        answer = "No se pudieron recuperar los análisis recientes."
                    followups = ["¿Cuántos documentos hay?", "Sube un nuevo documento"]
                    confidence = 0.8
                else:
                    answer = (
                        "Para crear un formulario nuevo, usa la opción "
                        "**Crear Formulario** en el menú o sube un archivo Excel/PDF "
                        "desde **Document Intelligence** para que el sistema analice "
                        "la estructura automáticamente."
                    )
                    followups = ["¿Cómo analizar un documento?", "Muéstrame los formularios existentes"]
                    confidence = 0.9

                elapsed = (time.perf_counter() - t0) * 1000
                _record_chat_metrics(intent.intent_type, "heuristic", elapsed)

                words = answer.split(" ")
                for i, word in enumerate(words):
                    if total_tokens == 0:
                        first_token_time = time.perf_counter()
                    yield _sse_event("token", {"text": word + (" " if i < len(words) - 1 else "")})
                    total_tokens += 1

                yield _sse_event("meta", {
                    "confidence": confidence,
                    "processing_time_ms": round(elapsed, 1),
                    "followups": followups[:3],
                    "token_count": total_tokens,
                })

                try:
                    smart_learner.record_chat(
                        question=question, answer=answer,
                        intent_type=intent.intent_type,
                        was_ai=False, confidence=confidence,
                        response_time_ms=elapsed, success=True,
                    )
                except Exception:
                    pass

                last_assistant_msg = ConversationManager.add_message(
                    conversation, role="assistant", content=answer,
                    intent=intent.intent_type,
                    provider="heuristic", source="heuristic",
                    confidence=confidence, execution_time=elapsed,
                    token_count=total_tokens,
                )
                if last_assistant_msg:
                    last_message_id = last_assistant_msg.id

            # ════════════════════════════════════════════
            # STEP 4 — GENERAL_CHAT → Planner | Tool Resolver | AI Provider
            # ════════════════════════════════════════════
            else:
                yield _sse_event("status", {"status": "generating"})

                # ── Try Planner first for multi-step requests ──
                from apps.platform.ai.services.planner import TaskPlanner
                from apps.platform.ai.services.tools import ExecutionEngine
                tool_engine = ExecutionEngine()

                planner = TaskPlanner()
                plan = planner.create_plan(question, intent, {"request": request})

                is_multi_step = plan and len(plan.steps) > 1
                is_paused_plan = plan and plan.status == "paused"

                if is_multi_step or is_paused_plan:
                    # Store intent for later use in plan execution
                    plan._intent = intent
                    source_type = "plan"

                    # Execute plan
                    collected_parts = []
                    plan_result = tool_engine.execute_plan(plan, request, progress_callback=lambda ev, dt: collected_parts.append((ev, dt)))

                    plan_elapsed = plan_result.total_duration_ms or ((time.perf_counter() - t0) * 1000)

                    if plan_result.status == "paused":
                        # Confirmation needed — show summary of what was done so far + what needs confirmation
                        completed = [s for s in plan_result.steps if s.status.value == "success"]
                        paused_step = next((s for s in plan_result.steps if s.status.value == "paused"), None)

                        text = ""
                        if completed:
                            text += "**Pasos completados:**\n"
                            for s in completed:
                                text += f"  ✅ {s.step_num}. {s.description}\n"
                            text += "\n"

                        if paused_step:
                            text += f"**Paso siguiente — {paused_step.description}**\n\n"
                            text += f"{paused_step.result.summary if paused_step.result else ''}\n\n"
                            text += "**¿Confirmas esta accion para continuar?**"

                        yield _sse_event("plan_paused", {
                            "plan_id": plan_result.id,
                            "step_num": plan_result.current_step,
                            "total_steps": len(plan_result.steps),
                            "steps": [s.to_dict() for s in plan_result.steps],
                            "message": f"Confirmacion requerida para: {paused_step.description if paused_step else ''}",
                            "confirmation_token": paused_step.confirmation_token if paused_step else "",
                            "tool_name": paused_step.tool_name if paused_step else "",
                        })
                    elif plan_result.status == "failed":
                        completed = [s for s in plan_result.steps if s.status.value == "success"]
                        failed_step = next((s for s in plan_result.steps if s.status.value == "failed"), None)
                        plan_failed_step = failed_step

                        text = ""
                        if completed:
                            text += "**Pasos completados:**\n"
                            for s in completed:
                                text += f"  ✅ {s.step_num}. {s.description}\n"
                            text += "\n"

                        if failed_step:
                            text += f"**❌ Paso {failed_step.step_num} fallo: {failed_step.description}**\n"
                            text += f"Error: {failed_step.error_message}\n\n"
                            text += f"**Sugerencia:** {_plan_recovery_suggestion(failed_step.tool_name)}\n"
                            text += "\nPuedes intentar de nuevo o pedir ayuda con otra cosa."

                        _record_chat_metrics("plan_failed", "plan", plan_elapsed)
                    elif plan_result.status == "cancelled":
                        text = "**El plan fue cancelado.**\n\n"
                        completed = [s for s in plan_result.steps if s.status.value == "success"]
                        if completed:
                            text += "Pasos completados antes de la cancelacion:\n"
                            for s in completed:
                                text += f"  ✅ {s.step_num}. {s.description}\n"
                    else:
                        # completed
                        texts = []
                        for s in plan_result.steps:
                            if s.status.value == "success" and s.result:
                                t = s.result.summary or ""
                                if t:
                                    texts.append(f"**{s.step_num}. {s.description}:**\n{t}")
                        text = "\n\n".join(texts) if texts else "Todos los pasos completados."

                        _record_chat_metrics("plan_completed", "plan", plan_elapsed)

                    # Stream the collected text
                    words = text.split(" ")
                    for i, word in enumerate(words):
                        if total_tokens == 0:
                            first_token_time = time.perf_counter()
                        yield _sse_event("token", {"text": word + (" " if i < len(words) - 1 else "")})
                        total_tokens += 1

                    is_plan_success = plan_result.status == "completed"
                    yield _sse_event("meta", {
                        "confidence": 0.9 if is_plan_success else 0.0,
                        "processing_time_ms": round(plan_elapsed, 1),
                        "followups": ["¿Que mas necesitas?", "¿Necesitas ayuda con otra cosa?"],
                        "token_count": total_tokens,
                        "plan_id": plan_result.id,
                        "plan_status": plan_result.status,
                        "plan_steps": len(plan_result.steps),
                    })

                    # SmartLearner
                    try:
                        completed_count = sum(1 for s in plan_result.steps if s.status.value == "success")
                        failed_count = sum(1 for s in plan_result.steps if s.status.value == "failed")
                        all_success = is_plan_success
                        pattern = plan_result.metrics.get("pattern", "unknown")
                        tool_sequence = [s.tool_name for s in plan_result.steps]
                        plan_error = ""
                        if not all_success:
                            first_failed = next((s for s in plan_result.steps if s.status.value == "failed"), None)
                            if first_failed:
                                plan_error = first_failed.error_message

                        smart_learner.record_plan(
                            plan_id=plan_result.id,
                            question=question,
                            pattern=pattern,
                            step_count=len(plan_result.steps),
                            success=all_success,
                            total_duration_ms=plan_elapsed,
                            completed_steps=completed_count,
                            failed_steps=failed_count,
                            tool_sequence=tool_sequence,
                            error_message=plan_error,
                        )
                    except Exception:
                        pass

                    last_assistant_msg = ConversationManager.add_message(
                        conversation, role="assistant", content=text,
                        intent="plan_execution",
                        provider="plan", source="plan",
                        confidence=0.9 if is_plan_success else 0.0,
                        execution_time=plan_elapsed,
                        token_count=total_tokens,
                    )
                    if last_assistant_msg:
                        last_message_id = last_assistant_msg.id

                else:
                    # ── Single step — Try Tool Resolver ──
                    tool, tool_params = tool_engine.resolver.resolve(intent)

                    if tool is not None:
                        yield _sse_event("source", {"source": "tool", "provider": tool.name})
                        source_type = "tool"

                        t_start = time.perf_counter()
                        tool_result = tool_engine.run(intent, request=request)
                        t_tool = (time.perf_counter() - t_start) * 1000

                        if tool_result.requires_confirmation:
                            text = (
                                f"{tool_result.confirmation_message}\n\n"
                                "**¿Confirmas esta accion?**"
                            )
                            yield _sse_event("confirmation", {
                                "token": tool_result.confirmation_token,
                                "message": tool_result.confirmation_message,
                                "tool": tool.name,
                            })
                        elif not tool_result.success:
                            text = f"**Error:** {tool_result.summary}"
                        else:
                            text = tool_result.summary

                        words = text.split(" ")
                        for i, word in enumerate(words):
                            if total_tokens == 0:
                                first_token_time = time.perf_counter()
                            yield _sse_event("token", {"text": word + (" " if i < len(words) - 1 else "")})
                            total_tokens += 1

                        yield _sse_event("meta", {
                            "confidence": 0.9 if tool_result.success else 0.0,
                            "processing_time_ms": round(t_tool, 1),
                            "followups": tool_result.followups[:3],
                            "token_count": total_tokens,
                        })

                        _record_chat_metrics(
                            intent.sub_intent or "tool_execution",
                            "tool", t_tool, provider=tool.name,
                        )

                        try:
                            smart_learner.record_chat(
                                question=question, answer=text,
                                intent_type=intent.intent_type,
                                sub_intent=intent.sub_intent or tool.name,
                                was_ai=False, confidence=0.9,
                                response_time_ms=t_tool, success=tool_result.success,
                            )
                            smart_learner.record_tool_execution(
                                tool_name=tool.name,
                                intent_type=intent.sub_intent or "tool_execution",
                                success=tool_result.success,
                                execution_time_ms=t_tool,
                                requires_confirmation=tool_result.requires_confirmation,
                                confirmed=not tool_result.requires_confirmation,
                                error_message=tool_result.summary if not tool_result.success else "",
                            )
                        except Exception:
                            pass

                        # Conversation memory
                        tool_assistant_msg = ConversationManager.add_message(
                            conversation, role="assistant", content=text,
                            intent=intent.sub_intent or tool.name,
                            provider=tool.name, source="tool",
                            confidence=0.9, execution_time=t_tool,
                            tool_name=tool.name,
                            tool_success=tool_result.success,
                            tool_dry_run=bool(tool_result.confirmation_message),
                            tool_confirmation=tool_result.requires_confirmation,
                        )
                        if tool_assistant_msg:
                            last_message_id = tool_assistant_msg.id
                        return
                    else:
                        # ── No tool matched — fall back to AI provider ──

                        # Offline fallback
                        if not is_online:
                            yield _sse_event("source", {"source": "heuristic", "provider": "none"})
                            offline_answer = (
                                "No tengo conexión a internet en este momento.\n\n"
                                "Puedo responder preguntas sobre datos del sistema:\n"
                                "  • ¿Cuántos productos hay?\n"
                                "  • ¿Cuántas ventas se registraron?\n"
                                "  • Muéstrame los clientes\n"
                                "  • ¿Qué formularios existen?"
                            )
                            words = offline_answer.split(" ")
                            for w in words:
                                if total_tokens == 0:
                                    first_token_time = time.perf_counter()
                                yield _sse_event("token", {"text": w + " "})
                                total_tokens += 1
                            yield _sse_event("meta", {
                                "confidence": 0.5,
                                "processing_time_ms": round((time.perf_counter() - t0) * 1000, 1),
                                "followups": ["¿Cuántos productos hay?", "¿Cuántas ventas se registraron?"],
                                "token_count": total_tokens,
                            })
                            return

                        # No AI provider configured
                        if not _check_ai_available():
                            yield _sse_event("source", {"source": "heuristic", "provider": "none"})
                            offline_msg = (
                                "⚡ **Modo offline FREE-FIRST activo**\n\n"
                                "No hay proveedores de IA configurados. "
                                "Las preguntas sobre datos del sistema siguen funcionando.\n\n"
                                "**Preguntas que funcionan ahora:**\n"
                                "  • ¿Cuántos formularios existen?\n"
                                "  • ¿Cuántos registros hay?\n"
                                "  • Muéstrame las últimas importaciones\n"
                                "  • ¿Qué formulario tiene más registros?\n\n"
                                "**Para habilitar Chat IA completo:**\n"
                                "Configura GEMINI_API_KEY en tu archivo .env"
                            )
                            words = offline_msg.split(" ")
                            for w in words:
                                if total_tokens == 0:
                                    first_token_time = time.perf_counter()
                                yield _sse_event("token", {"text": w + " "})
                                total_tokens += 1
                            yield _sse_event("meta", {
                                "confidence": 0.5,
                                "processing_time_ms": round((time.perf_counter() - t0) * 1000, 1),
                                "followups": ["¿Cuántos formularios existen?", "¿Cuántos registros hay?"],
                                "token_count": total_tokens,
                            })
                            return

                        # ── Build document context ──
                        from apps.platform.ai.services.conversational_documents import DocumentContext
                        doc_ctx = _build_chat_context(request)

                        # ── Route to provider ──
                        from apps.platform.ai.services.provider_router import get_provider_router
                        from apps.platform.ai.types import ProviderType
                        router = get_provider_router()
                        route = router.route(task=question, task_type="chat")

                        provider = None
                        if not route.is_heuristic:
                            try:
                                provider_type = ProviderType.from_string(route.selected_provider)
                                provider = get_provider(provider_type=provider_type)
                                provider_name = route.selected_provider
                                source_type = "ai"
                            except Exception:
                                provider = None
                                _chat_metrics["fallback_used"] += 1

                        yield _sse_event("source", {"source": "ai_provider", "provider": provider_name})

                        # ── Build system context + conversation history via ConversationManager ──
                        system_context = _build_system_context(request)
                        context_str = ConversationManager.build_context(
                            conversation, system_context=system_context,
                        )
                        enriched_question = f"{context_str}\n\n---\n\n## Pregunta del usuario:\n{question}"

                        # ── Stream from provider ──
                        collected_text = ""
                        ai_success = True
                        try:
                            from apps.platform.ai.services.conversational_documents import (
                                ConversationalDocuments, DocumentContext, QuestionType,
                            )
                            cd = ConversationalDocuments(provider=provider)

                            system_instruction = (
                                "Eres un asistente experto en gestión comercial y documentos. "
                                "Responde en español (Colombia) de forma clara y concisa."
                            )
                            messages = [{"role": "user", "parts": [{"text": enriched_question}]}]

                            for chunk in provider.stream_chat(
                                system_instruction=system_instruction,
                                messages=messages,
                            ):
                                if total_tokens == 0:
                                    first_token_time = time.perf_counter()
                                if chunk:
                                    yield _sse_event("token", {"text": chunk})
                                    collected_text += chunk
                                    total_tokens += 1

                        except Exception as e:
                            logger.warning("AI stream failed: %s", e)
                            _chat_metrics["fallback_used"] += 1
                            ai_success = False
                            yield _sse_event("token", {"text": "Lo siento, no pude generar una respuesta en este momento. Intenta de nuevo."})

                        ai_elapsed = (time.perf_counter() - t0) * 1000
                        _record_chat_metrics("general_chat", "ai", ai_elapsed, provider=provider_name)

                # SmartLearner
                try:
                    smart_learner.record_provider_run(
                        provider=provider_name, task_type="chat",
                        confidence=0.7, time_ms=ai_elapsed, success=ai_success,
                    )
                    smart_learner.record_prompt_run(
                        prompt_name="chat_stream",
                        task_type="chat",
                        confidence=0.7,
                        tokens=total_tokens,
                    )
                    smart_learner.record_chat(
                        question=question, answer=collected_text,
                        intent_type=intent.intent_type, sub_intent=intent.sub_intent,
                        was_ai=True, confidence=0.7,
                        response_time_ms=ai_elapsed, success=ai_success,
                        provider=provider_name,
                    )
                except Exception:
                    pass

                # Conversation memory
                if collected_text:
                    ai_assistant_msg = ConversationManager.add_message(
                        conversation, role="assistant", content=collected_text,
                        intent=intent.sub_intent or "general_chat",
                        provider=provider_name, source="ai",
                        confidence=0.7, execution_time=ai_elapsed,
                        token_count=total_tokens,
                    )
                    if ai_assistant_msg:
                        last_message_id = ai_assistant_msg.id

                yield _sse_event("meta", {
                    "confidence": 0.7,
                    "processing_time_ms": round(ai_elapsed, 1),
                    "followups": [
                        "¿Puedes darme más detalles?",
                        "¿Qué otros datos del sistema puedo consultar?",
                        "¿Cómo ha sido el rendimiento reciente?",
                    ],
                    "token_count": total_tokens,
                })

        except GeneratorExit:
            logger.info("Stream cancelled by client (GeneratorExit)")
        except Exception as e:
            logger.exception("Stream error")
            yield _sse_event("status", {"status": "error", "message": str(e)})
        finally:
            if first_token_time:
                first_token_latency = (first_token_time - t0) * 1000
            else:
                first_token_latency = 0
            total_ms = (time.perf_counter() - t0) * 1000
            tokens_per_sec = (total_tokens / (total_ms / 1000)) if total_ms > 0 else 0
            yield _sse_event("done", {
                "metrics": {
                    "total_ms": round(total_ms, 1),
                    "first_token_ms": round(first_token_latency, 1),
                    "tokens": total_tokens,
                    "tokens_per_sec": round(tokens_per_sec, 1),
                    "source": source_type,
                    "provider": provider_name,
                    "intent": intent_info,
                },
                "conversation_id": conversation.id,
                "message_id": last_message_id,
            })

    return StreamingHttpResponse(
        stream(),
        content_type="text/event-stream",
    )


# ════════════════════════════════════════════════════════════════
# Conversation CRUD (Phase 10 — Persistent Conversations)
# ════════════════════════════════════════════════════════════════


@login_required
def conversation_list(request):
    """
    GET — List user conversations (JSON).

    Query params:
      include_archived: bool (default false)
      limit: int (default 50)
    """
    include_archived = request.GET.get("include_archived") == "true"
    limit = int(request.GET.get("limit", "50"))
    conversations = ConversationManager.list_conversations(
        request.user, include_archived=include_archived, limit=limit,
    )
    data = [
        {
            "id": c.id,
            "title": c.title,
            "message_count": c.message_count,
            "pinned": c.pinned,
            "archived": c.archived,
            "created_at": c.created_at.isoformat(),
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
        }
        for c in conversations
    ]
    return JsonResponse({"conversations": data})


@login_required
def conversation_create(request):
    """
    POST — Create a new conversation (JSON).
    Body: {"title": "optional title"}
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    body = json.loads(request.body) if request.body else {}
    title = body.get("title", "").strip()
    conv = ConversationManager.create_conversation(request.user, title=title)
    return JsonResponse({
        "id": conv.id,
        "title": conv.title,
        "message_count": conv.message_count,
        "created_at": conv.created_at.isoformat(),
    })


@login_required
def conversation_detail(request, conversation_id: int):
    """
    GET — Get conversation with recent messages (JSON).
    Query param: messages (int, default 10)
    """
    conv = ConversationManager.get_conversation(conversation_id, request.user)
    if conv is None:
        return JsonResponse({"error": "Conversation not found"}, status=404)

    msg_limit = int(request.GET.get("messages", "10"))
    messages_data = []
    for msg in ConversationManager.get_recent_messages(conv, count=msg_limit):
        messages_data.append({
            "id": msg.id,
            "role": msg.role,
            "content": msg.content[:500],
            "intent": msg.intent,
            "source": msg.source,
            "provider": msg.provider,
            "confidence": msg.confidence,
            "created_at": msg.created_at.isoformat(),
            "tool_name": msg.tool_name,
            "tool_success": msg.tool_success,
        })

    return JsonResponse({
        "id": conv.id,
        "title": conv.title,
        "message_count": conv.message_count,
        "pinned": conv.pinned,
        "archived": conv.archived,
        "created_at": conv.created_at.isoformat(),
        "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
        "messages": list(reversed(messages_data)),
    })


@login_required
def conversation_rename(request, conversation_id: int):
    """
    POST — Rename a conversation.
    Body: {"title": "new title"}
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    body = json.loads(request.body) if request.body else {}
    title = body.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "Title is required"}, status=400)
    conv = ConversationManager.rename_conversation(conversation_id, request.user, title)
    if conv is None:
        return JsonResponse({"error": "Conversation not found"}, status=404)
    return JsonResponse({"id": conv.id, "title": conv.title})


@login_required
def conversation_archive(request, conversation_id: int):
    """
    POST — Toggle archive status.
    Body: {"archived": true|false}
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    body = json.loads(request.body) if request.body else {}
    archived = body.get("archived", True)
    conv = ConversationManager.archive_conversation(conversation_id, request.user, archived=archived)
    if conv is None:
        return JsonResponse({"error": "Conversation not found"}, status=404)
    return JsonResponse({"id": conv.id, "archived": conv.archived})


@login_required
def conversation_delete(request, conversation_id: int):
    """POST — Delete a conversation and all its messages."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    deleted = ConversationManager.delete_conversation(conversation_id, request.user)
    if not deleted:
        return JsonResponse({"error": "Conversation not found"}, status=404)
    return JsonResponse({"deleted": True})


@login_required
def conversation_search(request):
    """GET — Search conversations. Query: q, date_from, date_to, intent, limit."""
    query = request.GET.get("q", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    intent = request.GET.get("intent", "")
    limit = int(request.GET.get("limit", "20"))
    results = ConversationManager.search_conversations(
        request.user, query=query, date_from=date_from,
        date_to=date_to, intent=intent, limit=limit,
    )
    data = [
        {
            "id": c.id,
            "title": c.title,
            "message_count": c.message_count,
            "pinned": c.pinned,
            "created_at": c.created_at.isoformat(),
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
        }
        for c in results
    ]
    return JsonResponse({"conversations": data})


# ════════════════════════════════════════════════════════════════
# Conversation Feedback API (Phase 11 — User Feedback)
# ════════════════════════════════════════════════════════════════


@login_required
def feedback_create(request):
    """
    POST — Submit feedback on an assistant message.

    Body:
      message_id: int (required)
      rating: int (+1 or -1)
      reason: str (optional, for negative ratings)
      comment: str (optional)
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    body = json.loads(request.body) if request.body else {}

    message_id = body.get("message_id")
    rating = body.get("rating")
    if not message_id or rating not in (1, -1):
        return JsonResponse({"error": "message_id and rating (+1/-1) required"}, status=400)

    try:
        msg = ConversationMessage.objects.get(id=message_id)
    except ConversationMessage.DoesNotExist:
        return JsonResponse({"error": "Message not found"}, status=404)

    # Prevent duplicate feedback from same user on same message
    existing = ConversationFeedback.objects.filter(
        message_id=message_id, user=request.user,
    ).first()
    if existing:
        existing.rating = rating
        existing.reason = body.get("reason", "")
        existing.comment = body.get("comment", "")
        existing.save(update_fields=["rating", "reason", "comment", "updated_at"])
        feedback = existing
        created = False
    else:
        feedback = ConversationFeedback.objects.create(
            conversation=msg.conversation,
            message=msg,
            user=request.user,
            rating=rating,
            reason=body.get("reason", ""),
            comment=body.get("comment", ""),
        )
        created = True

    # SmartLearner integration
    try:
        from apps.platform.ai.services.smart_learner import SmartLearner
        learner = SmartLearner()
        learner.record_feedback(
            message_id=message_id,
            rating=rating,
            provider=msg.provider,
            intent_type=msg.intent,
            reason=body.get("reason", ""),
        )
    except Exception:
        pass

    return JsonResponse({
        "id": feedback.id,
        "created": created,
        "rating": feedback.rating,
        "reason": feedback.reason,
        "message_id": message_id,
    })


@login_required
def feedback_update(request, feedback_id: int):
    """
    PATCH — Update existing feedback.

    Body: any subset of {rating, reason, comment}
    """
    if request.method != "PATCH":
        return JsonResponse({"error": "PATCH required"}, status=405)
    body = json.loads(request.body) if request.body else {}

    try:
        feedback = ConversationFeedback.objects.get(
            id=feedback_id, user=request.user,
        )
    except ConversationFeedback.DoesNotExist:
        return JsonResponse({"error": "Feedback not found"}, status=404)

    if "rating" in body and body["rating"] in (1, -1):
        feedback.rating = body["rating"]
    if "reason" in body:
        feedback.reason = body["reason"]
    if "comment" in body:
        feedback.comment = body["comment"]
    feedback.save()

    return JsonResponse({
        "id": feedback.id,
        "rating": feedback.rating,
        "reason": feedback.reason,
    })


@login_required
def feedback_delete(request, feedback_id: int):
    """DELETE — Remove feedback."""
    if request.method != "DELETE":
        return JsonResponse({"error": "DELETE required"}, status=405)
    try:
        feedback = ConversationFeedback.objects.get(
            id=feedback_id, user=request.user,
        )
    except ConversationFeedback.DoesNotExist:
        return JsonResponse({"error": "Feedback not found"}, status=404)
    feedback.delete()
    return JsonResponse({"deleted": True})


@login_required
def feedback_stats(request):
    """
    GET — Get feedback statistics.

    Query params:
      days: int (default 30)
      user_only: bool (default false — admin can see all)
    """
    days = int(request.GET.get("days", "30"))
    user_only = request.GET.get("user_only") == "true"

    if user_only or not request.user.is_staff:
        stats = ConversationFeedback.get_stats(user=request.user, days=days)
    else:
        stats = ConversationFeedback.get_stats(days=days)

    return JsonResponse(stats)


# ════════════════════════════════════════════════════════════════
# Dashboard API (Phase 11 — Backend JSON Only)
# ════════════════════════════════════════════════════════════════


@login_required
def dashboard_metrics(request):
    """
    GET — Get overall conversation & learning metrics.

    Query params:
      days: int (default 30)
    """
    from apps.platform.ai.services.conversation_analytics import ConversationAnalytics
    days = int(request.GET.get("days", "30"))
    metrics = ConversationAnalytics.get_overall_metrics(
        user=request.user if not request.user.is_staff else None,
        days=days,
    )
    return JsonResponse(metrics)


@login_required
def dashboard_providers(request):
    """
    GET — Get provider effectiveness ratings.

    Query params:
      days: int (default 30)
    """
    from apps.platform.ai.services.conversation_analytics import ConversationAnalytics
    days = int(request.GET.get("days", "30"))
    data = ConversationAnalytics.get_provider_effectiveness(
        user=request.user if not request.user.is_staff else None,
        days=days,
    )
    return JsonResponse({"providers": data})


@login_required
def dashboard_tools(request):
    """
    GET — Get tool usage stats.

    Query params:
      days: int (default 30)
    """
    from apps.platform.ai.services.conversation_analytics import ConversationAnalytics
    days = int(request.GET.get("days", "30"))
    data = ConversationAnalytics.get_tool_usage_stats(
        user=request.user if not request.user.is_staff else None,
        days=days,
    )
    return JsonResponse({"tools": data})


@login_required
def dashboard_feedback(request):
    """
    GET — Get feedback summary.

    Query params:
      days: int (default 30)
    """
    days = int(request.GET.get("days", "30"))
    if request.user.is_staff:
        stats = ConversationFeedback.get_stats(days=days)
    else:
        stats = ConversationFeedback.get_stats(user=request.user, days=days)
    return JsonResponse(stats)


def _build_system_context(request) -> str:
    """
    Build a comprehensive text description of the ENTIRE system state.
    
    This is the FASE 1 — Universal Context Builder. It queries ALL data
    sources and returns a single rich text string that the AI can use
    to answer ANY question about the system.
    
    Sources:
      - Dynamic Forms (formularios, campos, registros)
      - AI analysis history (AIAnalysisLog)
      - Import history (ImportLog)
      - System users
      - AI Dashboard stats
      - Budget/cache status
      - SmartLearner knowledge
      - Recent session document (if any)
    """
    parts = []
    
    # ── 1. Dashboard / AI Stats ──
    try:
        dashboard = get_ai_dashboard().get_data(days=30)
        parts.append(
            f"[ESTADÍSTICAS IA - Últimos 30 días]\n"
            f"• Documentos analizados: {dashboard.total_calls}\n"
            f"• Exitosos: {dashboard.successful_calls} ({dashboard.failed_calls} fallos)\n"
            f"• En caché: {dashboard.cached_calls} (hit rate: {dashboard.cache_hit_rate}%)\n"
            f"• Tokens totales: {dashboard.total_prompt_tokens + dashboard.total_completion_tokens:,}\n"
            f"• Costo estimado: ${dashboard.estimated_cost_usd:.6f}\n"
            f"• Tiempo promedio: {dashboard.avg_time_ms:.0f}ms\n"
            f"• Documentos únicos: {dashboard.documents_analyzed}\n"
            f"• OCRs realizados: {dashboard.ocr_performed}\n"
            f"• Proveedor más usado: {dashboard.most_used_provider}\n"
            f"• Proveedores: {', '.join(f'{k}: {v}' for k, v in dashboard.by_provider.items())}\n"
            f"• Mejores proveedores por tarea: {dashboard.best_providers}\n"
        )
    except Exception:
        parts.append("[ESTADÍSTICAS IA] Sin datos disponibles.\n")
    
    # ── 2. Dynamic Forms ──
    try:
        from django.db import models
        from apps.platform.dynamic_forms.models import Formulario, Campo, Registro, ImportLog
        forms_qs = Formulario.objects.filter(activo=True)
        total_forms = forms_qs.count()
        total_campos = Campo.objects.filter(activo=True).count()
        total_registros = Registro.objects.count()
        total_imports = ImportLog.objects.count()
        
        # Detailed form info (top 10)
        form_details = []
        for f in forms_qs.order_by("-fecha_creacion")[:10]:
            campo_count = f.campos.filter(activo=True).count()
            registro_count = f.registros.count()
            import_count = f.importaciones.count()
            form_details.append(
                f"  • {f.nombre}: {campo_count} campos, {registro_count} registros, {import_count} importaciones"
            )
        
        parts.append(
            f"[FORMULARIOS DINÁMICOS]\n"
            f"• Total formularios activos: {total_forms}\n"
            f"• Total campos: {total_campos}\n"
            f"• Total registros: {total_registros:,}\n"
            f"• Total importaciones: {total_imports}\n"
            f"• Últimos formularios:\n" + "\n".join(form_details) + "\n"
        )
        
        # Count by field type
        type_counts_qs = (
            Campo.objects.filter(activo=True)
            .values("tipo")
            .annotate(count=models.Count("id"))
            .order_by("-count")
        )[:10]
        type_counts = {item["tipo"]: item["count"] for item in type_counts_qs}
        if type_counts:
            types_str = ", ".join(f"{t}: {c}" for t, c in type_counts.items())
            parts.append(f"• Tipos de campo más usados: {types_str}\n")
    except Exception as e:
        parts.append(f"[FORMULARIOS] Error: {e}\n")
    
    # ── 2b. Business Data (ValorCampo summaries) ──
    try:
        from apps.platform.dynamic_forms.models import Formulario, Campo, Registro, ValorCampo
        from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
        from django.db.models import Count
        
        # Productos: list all products with stock, price, category
        prod_form = Formulario.objects.filter(nombre="Productos", activo=True).first()
        if prod_form:
            prod_registros = Registro.objects.filter(formulario=prod_form).order_by("-fecha_creacion")[:50]
            if prod_registros.exists():
                prod_valores = DS.cargar_valores_mapa(prod_registros)
                stock_campo = prod_form.campos.filter(nombre__icontains="stock").first()
                precio_campo = prod_form.campos.filter(nombre__icontains="precio").first()
                nombre_campo = prod_form.campos.filter(nombre__icontains="nombre").first()
                categoria_campo = prod_form.campos.filter(nombre__icontains="categoria").first()
                sku_campo = prod_form.campos.filter(nombre__icontains="sku").first()
                
                prod_lines = []
                total_inv_value = 0
                low_stock_count = 0
                for reg in prod_registros:
                    v = prod_valores.get(reg.id, {})
                    nombre = v.get(nombre_campo.nombre, f"#{reg.id}") if nombre_campo else f"#{reg.id}"
                    stock_str = v.get(stock_campo.nombre, "0") if stock_campo else "0"
                    precio_str = v.get(precio_campo.nombre, "0") if precio_campo else "0"
                    sku = v.get(sku_campo.nombre, "") if sku_campo else ""
                    categoria = v.get(categoria_campo.nombre, "") if categoria_campo else ""
                    try:
                        stock_val = float(stock_str) if stock_str else 0
                        precio_val = float(precio_str) if precio_str else 0
                        total_inv_value += stock_val * precio_val
                        if stock_val < 10:
                            low_stock_count += 1
                    except (ValueError, TypeError):
                        stock_val = 0
                        precio_val = 0
                    sku_str = f" [{sku}]" if sku else ""
                    cat_str = f" ({categoria})" if categoria else ""
                    prod_lines.append(f"    • {nombre}{sku_str}{cat_str} — stock: {stock_str}, precio: ${precio_str}")
                
                parts.append(
                    f"[DATOS DE NEGOCIO — PRODUCTOS]\n"
                    f"• Total productos: {len(prod_registros)}\n"
                    f"• Valor total del inventario: ${total_inv_value:,.2f}\n"
                    f"• Productos con stock bajo (<10): {low_stock_count}\n"
                    f"• Listado de productos:\n" + "\n".join(prod_lines[:20]) + "\n"
                    + (f"  ... y {len(prod_registros) - 20} más\n" if len(prod_registros) > 20 else "")
                )
        
        # Ventas: total sales, revenue, recent sales
        ventas_form = Formulario.objects.filter(nombre="Ventas", activo=True).first()
        if ventas_form:
            ventas_registros = Registro.objects.filter(formulario=ventas_form).order_by("-fecha_creacion")[:30]
            if ventas_registros.exists():
                ventas_valores = DS.cargar_valores_mapa(ventas_registros)
                total_campo = ventas_form.campos.filter(nombre__icontains="total").first()
                cantidad_campo = ventas_form.campos.filter(nombre__icontains="cantidad").first()
                producto_campo = ventas_form.campos.filter(nombre__icontains="producto").first()
                sku_campo_v = ventas_form.campos.filter(nombre__icontains="sku").first()
                
                total_revenue = 0
                total_quantity = 0
                recent_sales = []
                for reg in ventas_registros:
                    v = ventas_valores.get(reg.id, {})
                    total_str = v.get(total_campo.nombre, "0") if total_campo else "0"
                    cant_str = v.get(cantidad_campo.nombre, "0") if cantidad_campo else "0"
                    prod_val = v.get(producto_campo.nombre, "") if producto_campo else ""
                    try:
                        total_revenue += float(total_str) if total_str else 0
                        total_quantity += float(cant_str) if cant_str else 0
                    except (ValueError, TypeError):
                        pass
                    recent_sales.append(
                        f"    • {reg.fecha_creacion.strftime('%Y-%m-%d')}: "
                        f"{prod_val} — ${total_str} ({cant_str} unds)"
                    )
                
                parts.append(
                    f"[DATOS DE NEGOCIO — VENTAS]\n"
                    f"• Total ventas registradas: {len(ventas_registros)}\n"
                    f"• Ingresos totales: ${total_revenue:,.2f}\n"
                    f"• Unidades vendidas: {int(total_quantity)}\n"
                    f"• Ticket promedio: ${total_revenue / len(ventas_registros):,.2f}\n"
                    f"• Últimas ventas ({min(10, len(recent_sales))}):\n" + "\n".join(recent_sales[:10]) + "\n"
                )
        
        # Clientes: total, active
        clientes_form = Formulario.objects.filter(nombre="Clientes", activo=True).first()
        if clientes_form:
            clientes_registros = Registro.objects.filter(formulario=clientes_form)
            total_clientes = clientes_registros.count()
            clientes_valores = DS.cargar_valores_mapa(clientes_registros)
            activo_campo = clientes_form.campos.filter(nombre__icontains="activo").first()
            active_count = 0
            if activo_campo:
                for reg in clientes_registros:
                    v = clientes_valores.get(reg.id, {})
                    if v.get(activo_campo.nombre, "").lower() in ("sí", "si", "true", "1", "yes"):
                        active_count += 1
            else:
                active_count = total_clientes
            
            parts.append(
                f"[DATOS DE NEGOCIO — CLIENTES]\n"
                f"• Total clientes: {total_clientes}\n"
                f"• Clientes activos: {active_count}\n"
                f"• Clientes inactivos: {total_clientes - active_count}\n"
            )
    except Exception:
        pass
    
    # ── 3. Import History ──
    try:
        from apps.platform.dynamic_forms.models import ImportLog, ImportAudit
        recent_imports = ImportLog.objects.order_by("-fecha")[:5]
        if recent_imports.exists():
            import_details = []
            total_audit = ImportAudit.objects.count()
            for imp in recent_imports:
                audit_count = imp.audits.count()
                import_details.append(
                    f"  • #{imp.id} {imp.archivo_nombre} → {imp.formulario.nombre}: "
                    f"{imp.creados} creados, {imp.actualizados} actualizados, "
                    f"{imp.errores} errores ({imp.estado}) — {audit_count} auditorías"
                )
            parts.append(
                f"[IMPORTACIONES RECIENTES]\n" + "\n".join(import_details) + "\n"
                f"• Total registros de auditoría en el sistema: {total_audit}\n"
            )
    except Exception:
        pass
    
    # ── 4. AI Analysis History ──
    try:
        recent_ai = AIAnalysisLog.objects.order_by("-created_at")[:10]
        if recent_ai.exists():
            ai_details = []
            error_count = 0
            invoice_count = 0
            for log in recent_ai:
                status = "OK" if log.success else "FAIL"
                if log.cached:
                    status += " (cache)"
                if not log.success:
                    error_count += 1
                if log.document_type == "invoice" or "factura" in (log.document_name or "").lower():
                    invoice_count += 1
                ai_details.append(
                    f"  • [{log.created_at.strftime('%Y-%m-%d %H:%M')}] {log.document_name}: "
                    f"{log.provider}/{log.service} → {status}"
                )
            parts.append(
                f"[ANÁLISIS IA RECIENTES]\n"
                f"• Últimos 10 análisis:\n" + "\n".join(ai_details) + "\n"
                f"• Errores en últimos 10: {error_count}\n"
                f"• Facturas en últimos 10: {invoice_count}\n"
            )
        # Invoice stats from history
        total_invoices = AIAnalysisLog.objects.filter(
            document_type="invoice"
        ).count()
        if total_invoices:
            parts.append(f"• Total facturas analizadas históricamente: {total_invoices}\n")
    except Exception:
        pass
    
    # ── 5. Session Document (current context) ──
    session_result = request.session.get("di_pipeline_result")
    if session_result:
        fields_info = []
        for f in (session_result.get("fields", []) or [])[:10]:
            fields_info.append(f"    • {f.get('name')}: {f.get('type')} (required={f.get('required')}, unique={f.get('unique')}, confidence={f.get('confidence')})")
        parts.append(
            f"[DOCUMENTO ACTUAL EN SESIÓN]\n"
            f"• Archivo: {session_result.get('file_name')}\n"
            f"• Tipo: {session_result.get('classification')}\n"
            f"• Formulario propuesto: {session_result.get('form_name')}\n"
            f"• Calidad: {session_result.get('quality', {}).get('label')} ({session_result.get('quality', {}).get('stars')}/5)\n"
            f"• Campos detectados ({len(session_result.get('fields', []))}):\n"
            + "\n".join(fields_info) + "\n"
        )
    
    # ── 6. Budget / Provider Status ──
    try:
        from apps.platform.ai.services.budget_manager import get_budget_manager
        budget = get_budget_manager().get_status()
        if budget:
            budget_lines = []
            for prov, b in budget.items():
                status = "✅ Activo" if b.get("enabled") else f"❌ {b.get('disabled_reason', 'Inactivo')}"
                budget_lines.append(
                    f"  • {prov}: {status} ({b.get('total_requests', 0)} requests, {b.get('total_tokens', 0):,} tokens)"
                )
            parts.append(
                f"[ESTADO DE PROVEEDORES IA]\n" + "\n".join(budget_lines) + "\n"
            )
    except Exception:
        pass
    
    # ── 7. Cache Stats ──
    try:
        from apps.platform.ai.services.multi_level_cache import get_multi_level_cache
        cache = get_multi_level_cache().get_stats()
        if cache:
            parts.append(
                f"[CACHÉ MULTINIVEL]\n"
                f"• Hit rate: {cache['hit_rate']}% ({cache['total_hits']} hits / {cache['total_misses']} misses)\n"
            )
    except Exception:
        pass
    
    # ── 8. System Users ──
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        total_users = User.objects.count()
        active_users = User.objects.filter(is_active=True).count()
        admin_users = User.objects.filter(is_superuser=True).count()
        parts.append(
            f"[USUARIOS DEL SISTEMA]\n"
            f"• Total: {total_users} ({active_users} activos, {admin_users} administradores)\n"
        )
    except Exception:
        pass
    
    # ── 9. SmartLearner / Learning ──
    try:
        from apps.platform.ai.services.smart_learner import SmartLearner
        learner = SmartLearner()
        provider_stats = learner.get_all_provider_stats()
        if provider_stats:
            parts.append(
                f"[APRENDIZAJE - SMARTLEARNER]\n"
                f"• Proveedores con rendimiento histórico: {len(provider_stats)}\n"
            )
    except Exception:
        pass
    
    return "\n".join(parts)


def _build_chat_context(request) -> "DocumentContext":
    """
    Build a DocumentContext from the best available source.
    
    FASE 1 — Universal Context Builder:
    Returns a DocumentContext enriched with ALL system data:
      - Dynamic Forms (formularios, campos, registros, importaciones)
      - AI Analysis history
      - Session document (if any)
      - System users
      - Dashboard stats
      - Budget / Cache status
      - SmartLearner knowledge
    """
    from apps.platform.ai.services.conversational_documents import DocumentContext
    
    ctx = DocumentContext()
    
    # Build the universal system context text
    system_text = _build_system_context(request)
    ctx.raw_text = system_text
    ctx.file_name = "Document Intelligence Platform (Sistema Completo)"
    ctx.document_type = "sistema_integral"
    
    # Count totals from DB for metadata columns
    try:
        from apps.platform.dynamic_forms.models import Formulario, Registro
        ctx.total_records = Registro.objects.count()
        ctx.total_columns = Formulario.objects.filter(activo=True).count()
        ctx.columns = [
            "formularios", "campos", "registros", "importaciones",
            "analisis_ia", "proveedores", "usuarios", "cache"
        ]
    except Exception:
        pass
    
    return ctx


# ═══════════════════════════════════════════════════════════════════
# FASE 2 — Data Agent: Safe Query Builder (Django ORM only, no SQL)
# ═══════════════════════════════════════════════════════════════════

# Whitelist of allowed models for data queries
# ── Routing data imported from DecisionEngine (single source of truth) ──
from apps.platform.ai.services.decision_engine import (
    _DATA_AGENT_MODELS,
    _DATA_AGENT_LABELS,
    _FORM_ALIASES,
    get_data_agent_models,
    get_data_agent_labels,
    get_form_aliases,
)


def _resolve_data_agent_model(model_path: str):
    """
    Resuelve un path de modelo a su clase Django Model de forma segura.

    Maneja casos especiales:
      - '__user_model__': utiliza get_user_model() en vez de 'auth.user'
      - Paths regulares: importlib.import_module()

    Returns:
        La clase del modelo, o None si no se puede resolver.
    """
    if model_path == "__user_model__":
        try:
            from django.contrib.auth import get_user_model
            return get_user_model()
        except Exception:
            return None

    try:
        parts = model_path.split(".")
        module_path = ".".join(parts[:-1])
        class_name = parts[-1]
        import importlib
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError, ValueError) as e:
        logger.warning("DataAgent: no se pudo resolver modelo '%s': %s", model_path, e)
        return None


def _validate_filter_fields(Model, filter_kwargs: dict) -> dict:
    """
    Filtra filter_kwargs para incluir solo campos que realmente existen en el modelo.

    Usa _meta.get_fields() para validar dinámicamente. Soporta lookups
    con doble guion bajo (ej: 'errores__gt' → campo base 'errores').

    Args:
        Model: clase Django Model
        filter_kwargs: dict de kwargs para filter()

    Returns:
        Dict con solo los filtros válidos.
    """
    if not filter_kwargs:
        return {}

    try:
        model_field_names = {f.name for f in Model._meta.get_fields()}
    except Exception:
        return filter_kwargs  # fallback seguro: aplicar sin validar

    safe = {}
    for k, v in filter_kwargs.items():
        field_name = k.split("__")[0]  # 'errores__gt' → 'errores'
        if field_name in model_field_names:
            safe[k] = v
        else:
            logger.debug("DataAgent: campo '%s' no existe en %s, omitiendo filtro", field_name, Model.__name__)

    return safe


# _detect_data_intent() removed in Phase 7 refactor.
# Replaced by DecisionEngine.classify_chat() in decision_engine.py.
# All routing goes through classify_chat() exclusively.


def _execute_safe_query(intent: str, model_key: str, params: dict) -> str:
    """
    Execute a safe Django ORM query based on detected intent and params.
    
    ONLY uses Django ORM. NO SQL generated. NO arbitrary code execution.
    Only whitelisted models and operations.
    
    Returns a human-readable string with the query result.
    """
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Count, Q, Avg, Sum

    model_path = _DATA_AGENT_MODELS.get(model_key, "")
    if not model_path:
        return f"No reconozco el tipo de dato '{model_key}'."

    Model = _resolve_data_agent_model(model_path)
    if Model is None:
        return (
            f"No se pudo acceder al modelo para '{model_key}'. "
            "Verifica que el módulo esté instalado."
        )

    try:
        qs = Model.objects.all()
        label = _DATA_AGENT_LABELS.get(Model.__name__, model_key)
        model_field_names = {f.name for f in Model._meta.get_fields()}
        from django.db.models import DateField, DateTimeField
        model_date_field_names = {
            f.name for f in Model._meta.get_fields()
            if isinstance(f, (DateField, DateTimeField))
        }

        # ── Apply single filter ──
        filter_kwargs = params.get("filter", {})
        if filter_kwargs:
            if "activo" in filter_kwargs:
                if not any(f.name == "activo" for f in Model._meta.get_fields()):
                    if any(f.name == "is_active" for f in Model._meta.get_fields()):
                        filter_kwargs["is_active"] = filter_kwargs.pop("activo")
                    else:
                        filter_kwargs.pop("activo", None)
            safe_filters = _validate_filter_fields(Model, filter_kwargs)
            if safe_filters:
                qs = qs.filter(**safe_filters)

        # ── Apply combined filters (Phase 7) ──
        combined_filters = params.get("filters", [])
        for cf in combined_filters:
            field = cf.get("field", "")
            value = cf.get("value")
            op = cf.get("op", "exact")
            if field in model_field_names:
                lookup = f"{field}__{op}" if op != "exact" else field
                qs = qs.filter(**{lookup: value})

        # ── Apply date filter ──
        date_cutoff = params.get("date_filter")
        if date_cutoff:
            date_field = None
            for fn in ["created_at", "fecha_creacion", "fecha", "fecha_actualizacion"]:
                if fn in model_date_field_names:
                    date_field = fn
                    break
            if date_field:
                qs = qs.filter(**{f"{date_field}__gte": date_cutoff})

        # ── Apply date_range param (from DecisionEngine) ──
        date_range = params.get("date_range")
        if date_range and not date_cutoff:
            today = timezone.now()
            delta_map = {"month": 30, "week": 7, "today": 1, "year": 365}
            delta_days = delta_map.get(date_range, 30)
            date_field = None
            for fn in ["created_at", "fecha_creacion", "fecha", "fecha_actualizacion"]:
                if fn in model_date_field_names:
                    date_field = fn
                    break
            if date_field:
                qs = qs.filter(**{f"{date_field}__gte": today - timedelta(days=delta_days)})

        # ── Apply form filter ──
        form_filter = params.get("form_filter")
        if form_filter and Model.__name__ == "Registro":
            qs = qs.filter(formulario__nombre=form_filter)
            _form_label_overrides = {
                "Productos": "productos",
                "Ventas": "ventas",
                "Clientes": "clientes",
                "MovimientosInventario": "movimientos de inventario",
            }
            label = _form_label_overrides.get(form_filter, form_filter.lower())

        # ── Apply pending filter ──
        if params.get("pending") and Model.__name__ == "ImportLog":
            qs = qs.filter(estado__in=["en_proceso", "pendiente"])

        # ── Helper: format list items ──
        def _format_items(items, order_by=""):
            if form_filter and Model.__name__ == "Registro":
                from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
                try:
                    valores_map = DS.cargar_valores_mapa(items)
                    form_obj = items[0].formulario
                    id_campo = form_obj.campos.filter(identificador_principal=True).first()
                    for item in items:
                        v_dict = valores_map.get(item.id, {})
                        if id_campo and id_campo.nombre in v_dict:
                            item._display_name = v_dict[id_campo.nombre]
                        else:
                            for v in v_dict.values():
                                if v and v != "0" and v != "0.00":
                                    item._display_name = v
                                    break
                            else:
                                item._display_name = f"#{item.id}"
                except Exception:
                    pass

            result_lines = []
            for item in items:
                name = str(item)
                if hasattr(item, "_display_name"):
                    name = item._display_name
                elif hasattr(item, "nombre"):
                    name = item.nombre
                elif hasattr(item, "document_name"):
                    name = item.document_name or str(item.id)
                elif hasattr(item, "username"):
                    name = item.username

                extra = ""
                for fn in ["created_at", "fecha_creacion", "fecha", "provider", "document_type"]:
                    if hasattr(item, fn):
                        val = getattr(item, fn)
                        if val:
                            if hasattr(val, "strftime"):
                                extra += f" ({val.strftime('%Y-%m-%d')})"
                            else:
                                extra += f" ({val})"
                            break
                result_lines.append(f"  • {name}{extra}")
            return f"**{len(items)}** {label}:\n" + "\n".join(result_lines)

        def _default_order():
            for fn in ["-created_at", "-fecha_creacion", "-fecha", "-id"]:
                base = fn.lstrip("-")
                if base in model_field_names:
                    return fn
            return ""

        # ==================================================================
        # INTENT HANDLERS
        # ==================================================================

        if intent == "count":
            total = qs.count()
            return f"Hay **{total}** {label}."

        elif intent in ("list", "search", "latest"):
            limit = params.get("limit", 10)
            if intent == "latest" and not params.get("order"):
                order_by = _default_order()
            else:
                order_by = params.get("order", _default_order())
            if order_by:
                qs = qs.order_by(order_by)
            items = list(qs[:limit])
            if not items:
                return f"No se encontraron {label}."
            return _format_items(items)

        elif intent == "filter":
            limit = params.get("limit", 20)
            order_by = params.get("order", _default_order())
            if order_by:
                qs = qs.order_by(order_by)
            items = list(qs[:limit])
            if not items:
                return f"No se encontraron {label} con esos filtros."
            return _format_items(items)

        elif intent == "oldest":
            limit = params.get("limit", 5)
            order_by = None
            for fn in ["created_at", "fecha_creacion", "fecha", "id"]:
                if fn in model_field_names:
                    order_by = fn
                    break
            if order_by:
                qs = qs.order_by(order_by)
            items = list(qs[:limit])
            if not items:
                return f"No se encontraron {label}."
            return _format_items(items)

        elif intent == "top":
            limit = params.get("limit", 10)
            valid_relations = {
                f.name for f in Model._meta.get_fields()
                if hasattr(f, "related_model") and f.related_model is not None
            }
            for rel_name in ["registros", "campos", "valores", "audits"]:
                if rel_name in valid_relations:
                    items = (
                        Model.objects.annotate(count=Count(rel_name))
                        .filter(**filter_kwargs)
                        .order_by("-count")[:limit]
                    )
                    if items:
                        result_lines = []
                        for item in items:
                            name = getattr(item, "nombre", str(item))
                            result_lines.append(f"  • {name}: {item.count}")
                        return f"**Top {limit}** {label} por cantidad:\n" + "\n".join(result_lines)
            return _execute_safe_query("list", model_key, params)

        elif intent == "bottom":
            limit = params.get("limit", 10)
            valid_relations = {
                f.name for f in Model._meta.get_fields()
                if hasattr(f, "related_model") and f.related_model is not None
            }
            for rel_name in ["registros", "campos", "valores", "audits"]:
                if rel_name in valid_relations:
                    items = (
                        Model.objects.annotate(count=Count(rel_name))
                        .filter(**filter_kwargs)
                        .order_by("count")[:limit]
                    )
                    if items:
                        result_lines = []
                        for item in items:
                            name = getattr(item, "nombre", str(item))
                            result_lines.append(f"  • {name}: {item.count}")
                        return f"**Bottom {limit}** {label} por cantidad:\n" + "\n".join(result_lines)
            return _execute_safe_query("list", model_key, params)

        elif intent == "exists":
            exists = qs.exists()
            if exists:
                total = qs.count()
                return f"Sí, hay **{total}** {label}."
            return f"No hay {label}."

        elif intent == "sum":
            agg_field = params.get("aggregate_field", "")
            if Model.__name__ == "Registro" and form_filter:
                from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
                from apps.platform.dynamic_forms.models import Campo
                try:
                    form_obj = qs.first().formulario if qs.exists() else None
                    if form_obj:
                        # Sum numeric values from ValorCampo for a given field
                        campo = form_obj.campos.filter(
                            nombre__icontains=agg_field,
                            tipo__in=["numero", "moneda", "decimal"],
                        ).first()
                        if campo:
                            from apps.platform.dynamic_forms.models import ValorCampo
                            valor_qs = ValorCampo.objects.filter(
                                campo=campo,
                                registro__in=qs,
                            )
                            total_val = 0
                            count = 0
                            for vc in valor_qs:
                                try:
                                    total_val += float(vc.valor)
                                    count += 1
                                except (ValueError, TypeError):
                                    pass
                            if count:
                                result_val = f"${total_val:,.0f}" if total_val >= 1000 else str(total_val)
                                return f"La suma de **{agg_field}** en {label} es **{result_val}** (sobre {count} registros)."
                except Exception:
                    pass
            # Fallback: try standard numeric field aggregation
            agg_field_map = {
                "precio": "precio", "precios": "precio",
                "stock": "stock", "cantidad": "cantidad",
                "total": "total", "totales": "total",
                "valor": "valor", "valores": "valor",
            }
            mapped_field = agg_field_map.get(agg_field, agg_field)
            if mapped_field in model_field_names:
                total = qs.aggregate(total=Sum(mapped_field))["total"]
                if total is not None:
                    return f"La suma de **{mapped_field}** es **{total}**."
            total = qs.count()
            return f"Hay **{total}** {label} en total."

        elif intent == "average":
            agg_field = params.get("aggregate_field", "")
            if Model.__name__ == "Registro" and form_filter:
                from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
                from apps.platform.dynamic_forms.models import Campo
                try:
                    form_obj = qs.first().formulario if qs.exists() else None
                    if form_obj:
                        campo = form_obj.campos.filter(
                            nombre__icontains=agg_field,
                            tipo__in=["numero", "moneda", "decimal"],
                        ).first()
                        if campo:
                            from apps.platform.dynamic_forms.models import ValorCampo
                            valor_qs = ValorCampo.objects.filter(
                                campo=campo,
                                registro__in=qs,
                            )
                            total_val = 0
                            count = 0
                            for vc in valor_qs:
                                try:
                                    total_val += float(vc.valor)
                                    count += 1
                                except (ValueError, TypeError):
                                    pass
                            if count:
                                avg_val = total_val / count
                                result_val = f"${avg_val:,.0f}" if avg_val >= 1000 else f"{avg_val:.2f}"
                                return f"El promedio de **{agg_field}** en {label} es **{result_val}** (sobre {count} registros)."
                except Exception:
                    pass
            agg_field_map = {
                "precio": "precio", "precios": "precio",
                "stock": "stock", "cantidad": "cantidad",
                "total": "total", "totales": "total",
            }
            mapped_field = agg_field_map.get(agg_field, agg_field)
            if mapped_field in model_field_names:
                avg_val = qs.aggregate(avg=Avg(mapped_field))["avg"]
                if avg_val is not None:
                    return f"El promedio de **{mapped_field}** es **{avg_val:.2f}**."
            total = qs.count()
            return f"Hay **{total}** {label} en total."

        elif intent in ("max", "min"):
            agg_field = params.get("aggregate_field", "")
            is_max = intent == "max"
            direction = "-" if is_max else ""

            if Model.__name__ == "Registro" and form_filter:
                from apps.platform.dynamic_forms.models import Campo
                try:
                    form_obj = qs.first().formulario if qs.exists() else None
                    if form_obj:
                        campo = form_obj.campos.filter(
                            nombre__icontains=agg_field,
                            tipo__in=["numero", "moneda", "decimal"],
                        ).first()
                        if not campo:
                            campo = form_obj.campos.filter(
                                nombre__icontains=agg_field,
                            ).first()
                        if campo:
                            from apps.platform.dynamic_forms.models import ValorCampo
                            from django.db.models import Max, Min
                            agg_func = Max if is_max else Min
                            # Need to coerce text to float
                            result = ValorCampo.objects.filter(
                                campo=campo,
                                registro__in=qs,
                            ).aggregate(val=agg_func("valor"))["val"]
                            if result is not None:
                                direction_text = "máximo" if is_max else "mínimo"
                                return f"El valor **{direction_text}** de **{agg_field}** en {label} es **{result}**."
                except Exception:
                    pass

            agg_field_map = {
                "precio": "precio", "precios": "precio",
                "stock": "stock", "cantidad": "cantidad",
                "total": "total", "totales": "total",
            }
            mapped_field = agg_field_map.get(agg_field, agg_field)
            if mapped_field in model_field_names:
                from django.db.models import Max, Min
                agg_func = Max if is_max else Min
                result = qs.aggregate(val=agg_func(mapped_field))["val"]
                if result is not None:
                    direction_text = "máximo" if is_max else "mínimo"
                    return f"El valor **{direction_text}** de **{mapped_field}** es **{result}**."

            # Fallback: list top/bottom item
            fallback_order = _default_order()
            if is_max and fallback_order:
                fallback_order = fallback_order
            elif not is_max:
                fallback_order = fallback_order.lstrip("-") if fallback_order else ""
            qs = qs.order_by(fallback_order) if fallback_order else qs
            item = qs.first()
            if item:
                name = str(item)
                if hasattr(item, "_display_name"):
                    name = item._display_name
                elif hasattr(item, "nombre"):
                    name = item.nombre
                direction_text = "más reciente" if is_max else "más antiguo"
                return f"El {direction_text} es **{name}**."
            return f"No se encontraron {label}."

        elif intent == "group":
            limit = params.get("limit", 15)
            group_fields = [
                "tipo", "estado", "provider", "document_type",
                "service", "modo", "is_active", "is_superuser",
            ]
            group_field = None
            for gf in group_fields:
                if gf in model_field_names:
                    group_field = gf
                    break
            if group_field:
                grouped = (
                    qs.values(group_field)
                    .annotate(count=Count("id"))
                    .order_by("-count")[:limit]
                )
                if grouped:
                    lines = [f"**{label} agrupados por {group_field}:**"]
                    for g in grouped:
                        val = g.get(group_field) or "(sin valor)"
                        lines.append(f"  • {val}: {g['count']}")
                    return "\n".join(lines)
            return _execute_safe_query("stats", model_key, params)

        elif intent == "statistics":
            total = qs.count()
            lines = [f"**Estadísticas de {label}:**", f"  • Total: {total}"]
            for fn in ["created_at", "fecha_creacion", "fecha"]:
                if fn in model_field_names:
                    today = timezone.now()
                    week_count = qs.filter(**{f"{fn}__gte": today - timedelta(days=7)}).count()
                    month_count = qs.filter(**{f"{fn}__gte": today - timedelta(days=30)}).count()
                    lines.append(f"  • Última semana: {week_count}")
                    lines.append(f"  • Último mes: {month_count}")
                    break
            return "\n".join(lines)

        elif intent in ("compare", "trend"):
            total = qs.count()
            today = timezone.now()
            lines = [f"**{label.capitalize()}:**", f"  • Total: {total}"]
            for fn in ["created_at", "fecha_creacion", "fecha"]:
                if fn in model_field_names:
                    this_month = qs.filter(**{f"{fn}__gte": today - timedelta(days=30)}).count()
                    last_month = qs.filter(
                        **{f"{fn}__gte": today - timedelta(days=60)},
                        **{f"{fn}__lt": today - timedelta(days=30)},
                    ).count()
                    lines.append(f"  • Este mes: {this_month}")
                    lines.append(f"  • Mes anterior: {last_month}")
                    if last_month > 0:
                        change = ((this_month - last_month) / last_month) * 100
                        arrow = "📈" if change > 0 else "📉"
                        lines.append(f"  • Cambio: {change:+.1f}% {arrow}")
                    break
            return "\n".join(lines)

        return f"No se pudo procesar la consulta para {label}."

    except Exception as e:
        logger.warning("SafeQueryBuilder error: %s", e)
        return f"Error al consultar datos: {e}"


def _try_data_query(intent: "ChatIntent", question: str) -> dict:
    """
    Answer a data query using the DecisionEngine's ChatIntent + SafeQueryBuilder.
    
    Uses DecisionEngine.classify_chat() output to route to the ORM query.
    Always returns a response dict (no None) — called only for data_query intents.
    """
    from apps.platform.ai.services.decision_engine import ChatIntent
    sub = intent.sub_intent or "list"
    model_key = intent.target_model or "registro"
    params = intent.params

    t0 = time.perf_counter()
    
    # If no specific model and has form alias, use registro
    if not model_key and intent.form_alias:
        model_key = "registro"
        params["form_filter"] = intent.form_alias
    
    answer = _execute_safe_query(sub, model_key, params)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    
    # Followup suggestions by sub_intent
    followup_map = {
        "count": ["Muéstrame los detalles", "¿Y cuántos hay activos?", "¿Cómo ha cambiado este mes?"],
        "list": ["¿Cuántos hay en total?", "¿Puedes filtrar por estado?", "¿Cuáles son los más recientes?"],
        "top": ["Muéstrame el detalle del primero", "¿Y el ranking inverso?", "¿Cómo ha cambiado con el tiempo?"],
        "bottom": ["Muéstrame el detalle", "¿Y cuál es el top?", "¿Cómo ha cambiado?"],
        "stats": ["Muéstrame la tendencia", "Compara con el mes anterior", "¿Hay anomalías?"],
        "trend": ["¿Qué factores explican este cambio?", "¿Hay alguna tendencia?", "Genera un reporte ejecutivo"],
        "compare": ["¿Qué factores explican esta diferencia?", "¿Cómo ha cambiado?", "Muéstrame los detalles"],
        "average": ["¿Cuál es el total?", "Muéstrame la distribución", "Compara con el período anterior"],
        "sum": ["¿Cuál es el promedio?", "¿Cómo se distribuye?", "Muéstrame los detalles"],
        "max": ["¿Y el mínimo?", "¿Cuál es el promedio?", "Muéstrame el ranking completo"],
        "min": ["¿Y el máximo?", "¿Cuál es el promedio?", "Muéstrame el ranking completo"],
        "latest": ["¿Cuántos hay en total?", "¿Cuáles son los más antiguos?", "¿Cómo ha cambiado?"],
        "oldest": ["¿Cuáles son los más recientes?", "¿Cuántos hay ahora?", "Muéstrame la evolución"],
        "exists": ["¿Cuántos hay en total?", "Muéstrame los detalles", "¿Hay algún otro?"],
        "statistics": ["Muéstrame la tendencia", "Compara con el mes anterior", "¿Hay algún KPI relevante?"],
        "group": ["Muéstrame los detalles", "¿Cuál es el más grande?", "¿Cómo ha cambiado?"],
    }
    followups = followup_map.get(sub, ["¿Cuántos hay en total?", "Muéstrame más detalles", "¿Qué tendencias observas?"])
    
    return {
        "answer": answer,
        "confidence": 0.95,
        "question_type": f"data_{sub}",
        "followups": followups[:3],
        "visualizations": ["kpi_card", "list", "table"],
        "processing_time_ms": round(elapsed_ms, 1),
    }


@login_required(login_url="login")
@admin_required
def ai_reports(request):
    """
    Reportes IA — generador de reportes ejecutivos.
    
    FREE-FIRST: si no hay proveedor IA, genera un reporte heurístico
    con datos reales del sistema (formularios, registros, importaciones).
    Nunca falla por falta de API Keys.
    """
    ai_mode = _get_ai_mode()
    
    # ── Datos del sistema para reporte heurístico ──
    heuristic_data = {}
    try:
        from django.db.models import Count
        from apps.platform.dynamic_forms.models import Formulario, Registro, ImportLog, Campo
        total_forms = Formulario.objects.filter(activo=True).count()
        total_registros = Registro.objects.count()
        total_campos = Campo.objects.filter(activo=True).count()
        total_imports = ImportLog.objects.count()
        
        # Últimas importaciones
        recent_imports = list(ImportLog.objects.order_by("-fecha").values(
            "archivo_nombre", "creados", "actualizados", "errores", "estado"
        )[:5])
        
        # Formularios con más registros
        top_forms = list(
            Formulario.objects.filter(activo=True)
            .annotate(num_registros=Count("registros"))
            .order_by("-num_registros")
            .values("nombre", "num_registros")[:5]
        )
        
        heuristic_data = {
            "total_formularios": total_forms,
            "total_registros": total_registros,
            "total_campos": total_campos,
            "total_importaciones": total_imports,
            "ultimas_importaciones": recent_imports,
            "formularios_top": top_forms,
        }
    except Exception:
        pass
    
    # ── Historial de IA (si existe) ──
    ia_history = []
    try:
        ia_history = list(AIAnalysisLog.objects.order_by("-created_at").values(
            "id", "document_name", "document_type", "provider", "success",
            "total_tokens", "processing_time_ms", "created_at"
        )[:20])
    except Exception:
        pass
    
    return render(request, "document_intelligence/ai_reports.html", {
        "es_admin": es_administrador(request.user),
        "rol_usuario": rol_usuario(request.user),
        "ai_mode": ai_mode,
        "heuristic_data": heuristic_data,
        "ia_history": ia_history,
    })


@login_required(login_url="login")
@admin_required
def ai_settings(request):
    """
    Configuración IA — permite ajustar proveedores, límites y caché.
    """
    budget_status = {}
    cache_stats = {}
    try:
        from apps.platform.ai.services.budget_manager import get_budget_manager
        budget_status = get_budget_manager().get_status()
    except Exception as e:
        logger.warning("Could not load budget status: %s", e)
    try:
        from apps.platform.ai.services.multi_level_cache import get_multi_level_cache
        cache_stats = get_multi_level_cache().get_stats()
    except Exception as e:
        logger.warning("Could not load cache stats: %s", e)

    return render(request, "document_intelligence/ai_settings.html", {
        "budget_status": budget_status,
        "cache_stats": cache_stats,
        "es_admin": es_administrador(request.user),
        "rol_usuario": rol_usuario(request.user),
    })


@login_required(login_url="login")
def history(request):
    """View past AI analyses."""
    try:
        page = request.GET.get("page", "1")
        if not page.isdigit():
            page = 1
        else:
            page = int(page)
        per_page = 25
        start = (page - 1) * per_page
        start = max(0, start)

        logs = AIAnalysisLog.objects.all().order_by("-created_at")[start:start + per_page]
        total = AIAnalysisLog.objects.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
    except Exception:
        logs = AIAnalysisLog.objects.none()
        page = 1
        total_pages = 1

    return render(request, "document_intelligence/history.html", {
        "logs": logs,
        "page": page,
        "total_pages": total_pages,
        "es_admin": es_administrador(request.user),
        "rol_usuario": rol_usuario(request.user),
    })


# ── Handler functions ──


def _handle_analyze(request):
    """Upload + analyze file (legacy)."""
    _cleanup_di(request)
    tipos_campo = _get_tipos_campo()

    file = request.FILES.get("document_file")
    error = _validate_upload(file)
    if error:
        messages.error(request, error)
        return render(request, "document_intelligence/create_from_file.html", {
            "es_admin": es_administrador(request.user),
            "rol_usuario": rol_usuario(request.user),
            "tipos_campo": tipos_campo,
        })

    # ── FREE-FIRST: si no hay IA, mensaje claro ──
    if not _check_ai_available():
        messages.info(
            request,
            "⚡ **Modo offline FREE-FIRST activo**\n\n"
            "No hay proveedores de IA configurados. "
            "Configura GEMINI_API_KEY en tu .env para analizar documentos con IA.\n\n"
            "Puedes crear formularios manualmente en Dynamic Forms "
            "y usar el Data Agent para consultar datos del sistema."
        )
        return render(request, "document_intelligence/create_from_file.html", {
            "es_admin": es_administrador(request.user),
            "rol_usuario": rol_usuario(request.user),
            "tipos_campo": tipos_campo,
        })

    # Save to temp file
    from django.conf import settings
    tmp_dir = Path(settings.BASE_DIR) / ".tmp_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{Path(file.name).name}"
    tmp_path = tmp_dir / safe_name
    with open(tmp_path, "wb") as f:
        for chunk in file.chunks():
            f.write(chunk)

    try:
        provider = get_provider()
        pipeline = DocumentIntelligencePipeline(provider=provider)
        config = PipelineConfig(
            file_path=str(tmp_path),
            file_name=file.name,
            user_id=request.user.id,
            use_cache=True,
        )
        result = pipeline.run(config)

        if not result.success:
            messages.error(request, "; ".join(result.errors))
            _cleanup_di(request)
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return render(request, "document_intelligence/create_from_file.html", {
                "es_admin": es_administrador(request.user),
                "rol_usuario": rol_usuario(request.user),
                "tipos_campo": tipos_campo,
            })

        from apps.platform.ai.utils import make_json_serializable
        # Store in session for next steps
        request.session["di_pipeline_result"] = make_json_serializable({
            "form_name": result.form_proposal.form_name if result.form_proposal else "",
            "form_description": result.form_proposal.form_description if result.form_proposal else "",
            "fields": [
                {
                    "name": f.name,
                    "type": f.suggested_type,
                    "required": f.required,
                    "unique": f.unique,
                    "is_identifier": f.is_identifier,
                    "order": f.order,
                    "confidence": f.confidence,
                    "explanation": f.explanation,
                }
                for f in (result.form_proposal.fields if result.form_proposal else [])
            ],
            "quality": {
                "stars": result.quality_score.stars if result.quality_score else 0,
                "label": result.quality_score.label if result.quality_score else "",
                "recommendations": result.quality_score.recommendations if result.quality_score else [],
                "risks": result.quality_score.risks if result.quality_score else [],
                "strengths": result.quality_score.strengths if result.quality_score else [],
            },
            "classification": result.classification.document_type if result.classification else "",
            "tmp_path": str(tmp_path),
            "file_name": file.name,
            "headers": list(result.extracted_doc.columns) if result and result.extracted_doc else [],
            "rows": list(result.extracted_doc.rows) if result and result.extracted_doc else [],
        })

        # Run similar form detection (FASE 6)
        similar_forms = []
        if result.form_proposal and result.form_proposal.fields:
            try:
                from apps.platform.document_intelligence.services.form_similarity_finder import (
                    FormSimilarityFinder,
                )
                finder = FormSimilarityFinder()
                similar_forms = finder.find_similar(
                    [{"name": f.name} for f in result.form_proposal.fields]
                )
            except Exception as e:
                logger.warning("Similar form finder error: %s", e)

        # Run catalog detection (FASE 3)
        catalog_suggestions = []
        if result.extracted_doc and result.extracted_doc.rows:
            try:
                from apps.platform.document_intelligence.services.catalog_detector import (
                    CatalogDetector,
                )
                cd = CatalogDetector()
                catalog_results = cd.detect(result.extracted_doc)
                if catalog_results:
                    catalog_suggestions = [
                        {"column": s.column_name, "options": s.options, "confidence": s.confidence}
                        for s in catalog_results
                    ]
                    request.session["di_catalog_suggestions"] = catalog_suggestions
            except Exception as e:
                logger.warning("Catalog detection error: %s", e)

        from apps.platform.ai.utils import make_json_serializable
        request.session["di_pipeline_result"]["similar_forms"] = make_json_serializable(similar_forms)
        request.session.modified = True

        # ── Convert AI field dicts to objects for the shared partial ──
        from apps.platform.dynamic_forms.models import Formulario as DF_Formulario
        fields_campo_objects = _ai_fields_to_campo_objects(
            result_data.get("fields", [])
        ) if (result_data := request.session.get("di_pipeline_result")) else []

        return render(request, "document_intelligence/create_from_file.html", {
            "result": request.session["di_pipeline_result"],
            "result_fields_objects": fields_campo_objects,
            "similar_forms": similar_forms,
            "catalog_suggestions": catalog_suggestions,
            "tipos_campo": tipos_campo,
            "formularios_disponibles": DF_Formulario.objects.all(),
            "es_admin": es_administrador(request.user),
            "rol_usuario": rol_usuario(request.user),
        })

    except Exception as e:
        logger.exception("Pipeline failed")
        messages.error(request, f"Analysis failed: {e}")
        _cleanup_di(request)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return render(request, "document_intelligence/create_from_file.html", {
            "es_admin": es_administrador(request.user),
            "rol_usuario": rol_usuario(request.user),
            "tipos_campo": tipos_campo,
        })



def _ai_fields_to_campo_objects(fields_data: list[dict]) -> list:
    """Convert AI-detected field dicts to objects compatible with _field_editor.html partial.
    
    The shared partial expects objects with .nombre, .tipo, .obligatorio, etc.
    AI detection returns dicts with name, type, required, etc.
    """
    class CampoProxy:
        """Proxy object that exposes AI field dict keys as Campo model attributes."""
        def __init__(self, data):
            self._data = data
            self.nombre = data.get("name", "")
            self.tipo = data.get("type", "texto")
            self.obligatorio = data.get("required", False)
            self.unico = data.get("unique", False)
            self.identificador_principal = data.get("is_identifier", False)
            self.visible = data.get("visible", True) if data.get("visible") is not None else True
            self.orden = data.get("order", 0)
            self.opciones = data.get("options", None)
            self.descripcion = data.get("descripcion", "")
            self.formula = None
            self.formulario_destino_id = None
            self.metadata_json = {}
            dv = data.get("default_value", "")
            ml = data.get("max_length", "")
            if dv:
                self.metadata_json["default_value"] = dv
            if ml:
                try:
                    self.metadata_json["max_length"] = int(ml)
                except (ValueError, TypeError):
                    pass

    return [CampoProxy(f) for f in fields_data]


def _handle_create_form(request, template_name="document_upload.html"):
    """
    Create form in Dynamic Forms from the analyzed proposal.
    
    Args:
        template_name: Template para el mensaje de éxito.
                       "document_upload.html" para el nuevo flujo E2E,
                       "create_from_file.html" para legacy.
    
    Handles the full visual editor output:
      - Field renames, types, required, unique, identifier, visible
      - Default values, max length, options (for list type)
      - Field description and metadata
      - Form similarity detection and reuse
    """
    result_data = request.session.get("di_pipeline_result")
    if not result_data:
        messages.error(request, "Session expired. Please upload the file again.")
        return redirect("document_intelligence:create_from_file")

    # ── Reuse existing form if user selected one ──
    use_existing_form_id = request.POST.get("use_existing_form_id", "").strip()
    if use_existing_form_id:
        from apps.platform.dynamic_forms.models import Formulario
        try:
            existing = Formulario.objects.get(id=int(use_existing_form_id))
        except (ValueError, Formulario.DoesNotExist):
            messages.error(request, "Formulario existente no encontrado.")
            return redirect("document_intelligence:document_upload")
        _cleanup_di(request)
        messages.success(
            request,
            f'Usando formulario existente "{existing.nombre}". '
            f'Puedes importar tus datos desde la opción "Importar Excel".'
        )
        return redirect("dynamic_forms:ver_registros", existing.id)

    from apps.platform.dynamic_forms.models import Formulario, Campo

    form_name = request.POST.get("form_name", result_data.get("form_name", "Untitled"))
    form_description = request.POST.get("form_description", result_data.get("form_description", ""))
    identifier_field_name = request.POST.get("identifier_field", "")

    from django.db import transaction as db_transaction

    # Create fields from JSON editor data
    field_data = []
    try:
        field_data = json.loads(request.POST.get("fields_json", "[]"))
    except (json.JSONDecodeError, TypeError):
        field_data = result_data.get("fields", [])

    with db_transaction.atomic():
        formulario = Formulario.objects.create(
            nombre=form_name,
            descripcion=form_description,
            creado_por=request.user,
        )

        has_identifier = False
        for idx, f_data in enumerate(field_data):
            f_name = f_data.get("name", f"campo_{idx}")
            f_type = f_data.get("type", "texto")

            is_id = f_data.get("is_identifier", False)
            if identifier_field_name and f_name == identifier_field_name:
                is_id = True

            if is_id:
                has_identifier = True

            metadata = {}
            default_value = f_data.get("default_value", "")
            max_length = f_data.get("max_length", "")
            if default_value:
                metadata["default_value"] = default_value
            if max_length:
                try:
                    metadata["max_length"] = int(max_length)
                except (ValueError, TypeError):
                    pass

            options = f_data.get("options", None)
            if isinstance(options, list) and len(options) > 0:
                pass
            else:
                options = None

            Campo.objects.create(
                formulario=formulario,
                nombre=f_name,
                tipo=f_type,
                obligatorio=f_data.get("required", False),
                unico=f_data.get("unique", is_id),
                identificador_principal=is_id,
                visible=f_data.get("visible", True),
                orden=f_data.get("order", idx),
                opciones=options,
                metadata_json=metadata if metadata else None,
            )

    # Save mapping memory for future imports
    tmp_path = result_data.get("tmp_path")
    if tmp_path:
        try:
            from apps.platform.dynamic_forms.import_service import guardar_memoria_mapeo
            headers = [f.get("name", "") for f in (result_data.get("fields", []) or [])]
            guardar_memoria_mapeo(
                formulario,
                headers,
                {i: f.get("name", f"col_{i}") for i, f in enumerate(field_data)}
            )
        except Exception as e:
            logger.warning("Could not save mapping memory: %s", e)

    # ── SmartLearner + MemoryLearner: record form creation (Phase 7) ──
    try:
        from apps.platform.ai.services.smart_learner import SmartLearner
        from apps.platform.document_intelligence.services.memory_learner import MemoryLearner
        learner = MemoryLearner()
        smart = SmartLearner()

        # SmartLearner: record form creation
        fields_for_smart = []
        for idx, f_data in enumerate(field_data):
            f_name = f_data.get("name", f"campo_{idx}")
            f_type = f_data.get("type", "texto")
            is_id = f_data.get("is_identifier", False) or (identifier_field_name and f_name == identifier_field_name)
            fields_for_smart.append({
                "name": f_name,
                "tipo": f_type,
                "identificador": is_id,
                "obligatorio": f_data.get("required", False),
                "unico": f_data.get("unique", is_id),
                "order": f_data.get("order", idx),
            })
            # SmartLearner: record field preference individually
            smart.record_field_preference(
                form_name=form_name,
                field_name=f_name,
                field_type=f_type,
                is_identifier=is_id,
                order=f_data.get("order", idx),
                required=f_data.get("required", False),
                unique=f_data.get("unique", is_id),
                catalog_options=f_data.get("options", None),
            )
            # MemoryLearner: learn identifier if marked
            if is_id:
                learner.learn_identifier(form_name, f_name)
            # MemoryLearner: learn type correction
            learner.learn_type_correction(f_name, f_type)

        smart.record_form_creation(
            form_name=form_name,
            description=form_description,
            fields=fields_for_smart,
        )

        # MemoryLearner: learn form name from source document type
        source_type = result_data.get("file_name", "")
        if source_type:
            ext = Path(source_type).suffix.lower()
            learner.learn_form_name(ext, form_name)
            # MemoryLearner: learn field order
            learner.learn_field_order(form_name, [f["name"] for f in fields_for_smart])

        # MemoryLearner: track renames from original field names
        original_field_names = [
            f.get("name", "") for f in (result_data.get("fields", []) or [])
        ]
        for i, f_data in enumerate(field_data):
            original_name = original_field_names[i] if i < len(original_field_names) else ""
            new_name = f_data.get("name", "")
            if original_name and new_name and original_name != new_name:
                learner.learn_field_rename(original_name, new_name)
    except Exception as e:
        logger.warning("SmartLearner/MemoryLearner error: %s", e)

    messages.success(request, f'Formulario "{form_name}" creado exitosamente con {len(field_data)} campos.')

    # Check if there's data to import
    has_data = bool(tmp_path and result_data.get("fields"))

    request.session["di_import_ready"] = {
        "formulario_id": formulario.id,
        "tmp_path": str(tmp_path),
        "file_name": result_data.get("file_name", ""),
        "headers": result_data.get("headers", []),
        "rows": result_data.get("rows", []),
        "fields": result_data.get("fields", []),
        "records": result_data.get("records", []),
    }
    # Pipeline result no longer needed — import step only uses di_import_ready
    request.session.pop("di_pipeline_result", None)
    request.session.pop("di_catalog_suggestions", None)
    request.session.modified = True

    success_template = (
        "document_intelligence/create_from_file.html"
        if template_name == "create_from_file.html"
        else "document_intelligence/document_upload.html"
    )

    return render(request, success_template, {
        "form_created": True,
        "formulario_id": formulario.id,
        "form_name": form_name,
        "total_fields": len(field_data),
        "has_data": has_data,
        "es_admin": es_administrador(request.user),
        "rol_usuario": rol_usuario(request.user),
    })


def _handle_import_data(request):
    """Import data into the newly created form."""
    import_data = request.session.get("di_import_ready")
    if not import_data:
        messages.error(request, "No form ready for import.")
        return redirect("document_intelligence:create_from_file")

    formulario_id = import_data.get("formulario_id")
    tmp_path = import_data.get("tmp_path")

    if not formulario_id or not tmp_path:
        messages.error(request, "Import data incomplete.")
        return redirect("document_intelligence:create_from_file")

    try:
        from django.conf import settings
        _tmp_dir = Path(settings.BASE_DIR) / ".tmp_uploads"
        _resolved_path = Path(tmp_path).resolve()
        _resolved_tmp = _tmp_dir.resolve()
        if not str(_resolved_path).startswith(str(_resolved_tmp)):
            logger.warning("Path traversal attempt blocked: %s", tmp_path)
            messages.error(request, "Ruta de archivo inválida.")
            return redirect("document_intelligence:create_from_file")

        from apps.platform.dynamic_forms.models import Formulario
        from apps.platform.dynamic_forms.import_service import (
            previsualizar,
            importar,
        )

        formulario = Formulario.objects.get(id=formulario_id)

        _ext = Path(tmp_path).suffix.lower()

        if _ext in {".xlsx", ".xls"}:
            # Excel: use openpyxl with ColumnMatcher
            from apps.platform.dynamic_forms.import_service import analyze_workbook
            analysis = analyze_workbook(tmp_path, formulario)
            encabezados = analysis["encabezados"]
            filas = analysis["filas"]
            match_results = analysis["match_results"]
            mapeo_idx = {}
            for r in match_results:
                if r.matched_to:
                    mapeo_idx[r.column_index] = r.matched_to

        elif _ext == ".csv":
            # CSV: parse with Python's csv module + ColumnMatcher
            from apps.platform.dynamic_forms.column_matching import ColumnMatcher
            from apps.platform.dynamic_forms.models import Campo
            import csv as _csv
            with open(tmp_path, newline='', encoding='utf-8-sig') as _f:
                _reader = _csv.reader(_f)
                _raw_headers = next(_reader, [])
                encabezados = [h.strip() for h in _raw_headers]
                filas = []
                for _row in _reader:
                    _fila_dict = {}
                    for i, h in enumerate(encabezados):
                        _fila_dict[h] = _row[i].strip() if i < len(_row) else ''
                    filas.append(_fila_dict)
            campos = list(Campo.objects.filter(formulario=formulario, activo=True).order_by('orden'))
            nombres_campos = [c.nombre for c in campos]
            matcher = ColumnMatcher(nombres_campos)
            match_results = matcher.match_all(encabezados)
            mapeo_idx = {}
            for r in match_results:
                if r.matched_to:
                    mapeo_idx[r.column_index] = r.matched_to

        else:
            # PDF, images, text: use records (Phase 5 canonical source) first
            from apps.platform.dynamic_forms.column_matching import ColumnMatcher
            from apps.platform.dynamic_forms.models import Campo
            records = import_data.get("records", [])
            headers = import_data.get("headers", [])
            rows = import_data.get("rows", [])

            if records:
                encabezados = list(records[0].keys())
                filas = records
            elif headers and rows:
                encabezados = headers
                filas = []
                for row in rows:
                    fila_dict = {}
                    for i, h in enumerate(headers):
                        fila_dict[h] = row[i] if i < len(row) else ''
                    filas.append(fila_dict)
            else:
                messages.error(request, "No extracted data available. Upload the file again.")
                _cleanup_di(request)
                return redirect("document_intelligence:document_upload")

            campos = list(Campo.objects.filter(formulario=formulario, activo=True).order_by('orden'))
            nombres_campos = [c.nombre for c in campos]
            matcher = ColumnMatcher(nombres_campos)
            match_results = matcher.match_all(encabezados)
            mapeo_idx = {}
            for r in match_results:
                if r.matched_to:
                    mapeo_idx[r.column_index] = r.matched_to

        preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
        valid_rows = [r for r in preview if r["valida"]]
        invalid_count = len(preview) - len(valid_rows)

        if not valid_rows:
            mensaje = "No hay filas válidas para importar."
            if invalid_count:
                mensaje += f" {invalid_count} fila(s) fueron inválidas (revisa validaciones)."
            messages.warning(request, mensaje)
            return redirect("document_intelligence:create_from_file")

        result = importar(
            formulario, valid_rows,
            usuario=request.user, modo="crear", mapeo=mapeo_idx,
        )

        # ── SmartLearner: record import (Phase 7) ──
        try:
            from apps.platform.ai.services.smart_learner import SmartLearner
            smart = SmartLearner()
            smart.record_import(
                form_name=formulario.nombre,
                rows_imported=result.get("creados", 0),
                rows_failed=len(result.get("errores", [])),
                rows_ignored=result.get("ignorados", 0),
                file_name=import_data.get("file_name", ""),
                success=True,
            )
        except Exception:
            pass

        partes = [f"{result['creados']} registro(s) importados en '{formulario.nombre}'"]
        if invalid_count:
            partes.append(f"{invalid_count} fila(s) inválidas omitidas")
        if result.get('ignorados'):
            partes.append(f"{result['ignorados']} ignorado(s)")
        if result.get('errores'):
            partes.append(f"{len(result['errores'])} error(es)")
        messages.success(request, ". ".join(partes) + ".")

        _cleanup_di(request, delete_tmp_path=tmp_path)
        return redirect("dynamic_forms:ver_registros", formulario_id=formulario.id)

    except Exception as e:
        logger.exception("Import failed")
        _cleanup_di(request)
        messages.error(request, f"Import failed: {e}")
        return redirect("document_intelligence:create_from_file")


# ═══════════════════════════════════════════════════════════════════════
# Plan API views (FASE 12)
# ═══════════════════════════════════════════════════════════════════════

@login_required
def plan_detail(request, plan_id):
    """Get plan details as JSON."""
    from apps.platform.ai.services.tools import ExecutionEngine
    engine = ExecutionEngine()
    plan = engine.get_plan(plan_id, request)
    if plan is None:
        return JsonResponse({"error": "Plan not found"}, status=404)
    plan_dict = plan.to_dict()
    plan_dict["context"] = plan.context
    plan_dict["metrics"] = plan.metrics
    return JsonResponse(plan_dict)


@require_POST
@login_required
def plan_confirm_step(request, plan_id):
    """Confirm a paused plan step and prepare for resume."""
    from apps.platform.ai.services.tools import ExecutionEngine
    body = json.loads(request.body)
    token = body.get("confirmation_token", "")
    engine = ExecutionEngine()
    plan = engine.confirm_plan_step(plan_id, token, request)
    if plan is None:
        return JsonResponse({"error": "Plan not found"}, status=404)
    if plan.status == "failed":
        return JsonResponse({
            "status": "failed",
            "error": "No se pudo confirmar el paso",
        }, status=400)
    return JsonResponse({
        "status": "confirmed",
        "plan_id": plan_id,
        "current_step": plan.current_step,
        "message": "Paso confirmado. Puedes reanudar el plan.",
    })


@require_POST
@login_required
def plan_resume(request, plan_id):
    """Resume a paused plan via streaming."""
    from apps.platform.ai.services.tools import ExecutionEngine
    engine = ExecutionEngine()
    plan = engine.get_plan(plan_id, request)
    if plan is None:
        return JsonResponse({"error": "Plan not found"}, status=404)
    if plan.status not in ("paused",):
        return JsonResponse({
            "status": plan.status,
            "error": "El plan no esta en pausa",
        }, status=400)
    return JsonResponse({
        "status": "ready",
        "plan_id": plan_id,
        "message": "Plan listo para reanudar. Usa el endpoint stream para ejecutar.",
        "stream_url": f"/document-intelligence/plan/{plan_id}/stream/",
    })


@require_POST
@login_required
def plan_cancel(request, plan_id):
    """Cancel a plan."""
    from apps.platform.ai.services.tools import ExecutionEngine
    engine = ExecutionEngine()
    plan = engine.cancel_plan(plan_id, request)
    if plan is None:
        return JsonResponse({"error": "Plan not found"}, status=404)
    return JsonResponse({
        "status": "cancelled",
        "plan_id": plan_id,
        "message": "Plan cancelado.",
    })


@require_POST
@login_required
def plan_retry(request, plan_id):
    """Retry a failed plan."""
    from apps.platform.ai.services.tools import ExecutionEngine
    engine = ExecutionEngine()
    plan = engine.get_plan(plan_id, request)
    if plan is None:
        return JsonResponse({"error": "Plan not found"}, status=404)
    if plan.status != "failed":
        return JsonResponse({
            "status": plan.status,
            "error": "El plan no esta en estado fallido",
        }, status=400)
    return JsonResponse({
        "status": "ready",
        "plan_id": plan_id,
        "message": "Plan listo para reintentar. Usa el endpoint stream para ejecutar.",
        "stream_url": f"/document-intelligence/plan/{plan_id}/stream/",
    })


@login_required
def plan_stream(request, plan_id):
    """
    SSE streaming endpoint for resuming a paused plan or retrying a failed one.

    Events:
      plan_resumed / plan_retry — step lifecycle
      plan_step / plan_step_done — per-step progress
      plan_step_confirmation — if confirmation needed
      plan_paused — awaiting confirmation
      plan_complete — all steps done
      plan_failed — step failed
      token / meta / done — standard events
    """
    from apps.platform.ai.services.tools import ExecutionEngine
    engine = ExecutionEngine()
    plan = engine.get_plan(plan_id, request)
    if plan is None:
        return JsonResponse({"error": "Plan not found"}, status=404)

    if plan.status not in ("paused", "failed"):
        return JsonResponse({
            "status": plan.status,
            "error": f"No se puede reanudar un plan en estado '{plan.status}'",
        }, status=400)

    is_retry = plan.status == "failed"

    def stream():
        nonlocal plan
        total_tokens = 0
        t0 = time.perf_counter()

        try:
            if is_retry:
                plan = engine.retry_failed_step(plan_id, request, progress_callback=lambda ev, dt: None)

            plan = engine.resume_plan(plan_id, request, progress_callback=lambda ev, dt: None)

            # Collect step events then replay as SSE
            events: list[tuple[str, dict]] = []

            def capture(ev, dt):
                events.append((ev, dt))

            plan = engine.execute_plan(plan, request, progress_callback=capture)

            # Replay collected events as SSE
            for ev, dt in events:
                yield _sse_event(ev, dt)

            # Build and stream summary
            text_parts = []
            for s in plan.steps:
                if s.status.value == "success" and s.result:
                    t = s.result.summary or ""
                    if t:
                        text_parts.append(f"**{s.step_num}. {s.description}:**\n{t}")
                elif s.status.value == "failed":
                    text_parts.append(f"**{s.step_num}. {s.description} falló:**\n{s.error_message}")

            text = "\n\n".join(text_parts) if text_parts else "Plan completado."

            words = text.split(" ")
            for w in words:
                yield _sse_event("token", {"text": w + " "})
                total_tokens += 1

            is_success = plan.status == "completed"
            yield _sse_event("meta", {
                "confidence": 0.9 if is_success else 0.0,
                "processing_time_ms": round(plan.total_duration_ms, 1),
                "token_count": total_tokens,
                "plan_id": plan.id,
                "plan_status": plan.status,
            })

            # SmartLearner
            try:
                from apps.platform.ai.services.smart_learner import SmartLearner
                sl = SmartLearner()
                completed_count = sum(1 for s in plan.steps if s.status.value == "success")
                failed_count = sum(1 for s in plan.steps if s.status.value == "failed")
                tool_seq = [s.tool_name for s in plan.steps]
                plan_error = ""
                if failed_count > 0:
                    first_failed = next((s for s in plan.steps if s.status.value == "failed"), None)
                    if first_failed:
                        plan_error = first_failed.error_message
                sl.record_plan(
                    plan_id=plan.id, question="", pattern=plan.metrics.get("pattern", "unknown"),
                    step_count=len(plan.steps), success=is_success,
                    total_duration_ms=plan.total_duration_ms,
                    completed_steps=completed_count, failed_steps=failed_count,
                    tool_sequence=tool_seq, error_message=plan_error,
                )
            except Exception:
                pass

        except GeneratorExit:
            pass
        except Exception as e:
            logger.exception("Plan stream error")
            yield _sse_event("status", {"status": "error", "message": str(e)})
        finally:
            yield _sse_event("done", {
                "metrics": {
                    "total_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "source": "plan",
                    "provider": "plan",
                    "intent": f"plan/{plan_id[:8] if plan else 'unknown'}",
                },
                "conversation_id": None,
                "message_id": None,
            })

    return StreamingHttpResponse(
        stream(),
        content_type="text/event-stream",
    )
