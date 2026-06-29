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
  - Conversation memory: Q&A history stored in di_chat_history session key,
    last 5 exchanges prepended to each prompt, cache disabled for conversation
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render

from apps.platform.ai.models import AIAnalysisLog
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
    ".xlsx", ".xls", ".csv", ".pdf",
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


@login_required(login_url="login")
def ai_chat_ask(request):
    """
    AJAX endpoint for chat questions.
    
    FASE 2 — Data Agent Integration:
      - First tries to detect a data intent (count, list, search, etc.)
      - If detected, uses SafeQueryBuilder (Django ORM only, no SQL)
      - If ambiguous, uses ConversationalDocuments with Universal Context
      - If not a data question, uses ConversationalDocuments directly
    
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
    
    # ════════════════════════════════════════════════════════════════
    # STEP 1 — Try Data Agent first (heuristic intent detection)
    # ════════════════════════════════════════════════════════════════
    data_result = _try_data_query(request, question)
    if data_result is not None:
        return JsonResponse(data_result)
    
    # ════════════════════════════════════════════════════════════════
    # STEP 2 — Fall through to ConversationalDocuments (AI chat)
    # ════════════════════════════════════════════════════════════════
    # ════════════════════════════════════════════════════════════════
    # CHECK — Si no hay API Keys, responder offline inmediatamente
    # ════════════════════════════════════════════════════════════════
    if not _check_ai_available():
        return _offline_json_response(
            message=(
                "⚡ **Modo offline FREE-FIRST activo**\n\n"
                "No hay proveedores de IA configurados. "
                "Las preguntas sobre datos del sistema (Data Agent) siguen funcionando.\n\n"
                "**✅ Preguntas que funcionan ahora (Data Agent):**\n"
                "• ¿Cuántos formularios existen?\n"
                "• ¿Cuántos registros hay?\n"
                "• Muéstrame las últimas importaciones\n"
                "• ¿Cuántos usuarios hay activos?\n"
                "• ¿Qué formulario tiene más registros?\n\n"
                "**🔧 Para habilitar Chat IA completo:**\n"
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
    from apps.platform.ai.services.decision_engine import get_decision_engine
    from apps.platform.ai.services.provider_router import get_provider_router
    from apps.platform.ai.types import ProviderType

    # 2a. Build DocumentContext from available sources
    doc_ctx = _build_chat_context(request)
    
    # 2b. Decide if AI is needed
    decision_engine = get_decision_engine()
    decision = decision_engine.decide(
        task=question,
        headers=doc_ctx.columns,
        raw_text=doc_ctx.raw_text[:500] if doc_ctx.raw_text else "",
    )
    
    # 2c. Route to appropriate provider
    router = get_provider_router()
    route = router.route(task=question, task_type="chat")
    
    # 2d. Get provider — si heuristic, no intentar crear provider
    provider = None
    if not route.is_heuristic:
        try:
            provider_type = ProviderType.from_string(route.selected_provider)
            provider = get_provider(provider_type=provider_type)
        except Exception:
            provider = None  # fallback silencioso a offline
    
    # 2e. Si sigue siendo heuristic/None, delegar a ConversationalDocuments
    #     que ahora maneja modo offline internamente
    cd = ConversationalDocuments(provider=provider)
    
    # Prepend full system context so the AI knows about all forms, imports, users, etc.
    system_context = _build_system_context(request)
    
    # ════════════════════════════════════════════════════════════════
    # Conversation memory — accumulate Q&A history in session
    # ════════════════════════════════════════════════════════════════
    chat_history = request.session.get("di_chat_history", [])
    history_lines = []
    for entry in chat_history[-5:]:  # last 5 exchanges only
        history_lines.append(f"Usuario: {entry['q']}")
        history_lines.append(f"Asistente: {entry['a']}")
    history_text = "\n".join(history_lines)
    
    if history_text:
        enriched_question = (
            f"[HISTORIAL DE LA CONVERSACIÓN]\n{history_text}\n\n"
            f"---\n\n{system_context}\n\n---\n\n"
            f"## Pregunta del usuario:\n{question}"
        )
    else:
        enriched_question = f"{system_context}\n\n---\n\n## Pregunta del usuario:\n{question}"
    
    import time
    t0 = time.perf_counter()
    
    result = cd.ask(
        document=doc_ctx,
        question=enriched_question,
        use_cache=False,  # disable cache for conversational questions
    )
    
    # Store Q&A in conversation history
    chat_history.append({"q": question, "a": result.answer})
    # Keep last 20 exchanges max
    request.session["di_chat_history"] = chat_history[-20:]
    request.session.modified = True
    
    return JsonResponse({
        "answer": result.answer,
        "confidence": result.confidence,
        "question_type": result.question_type.value,
        "followups": result.followup_questions[:3],
        "visualizations": result.suggested_visualizations[:3],
        "processing_time_ms": round(result.processing_time_ms, 1),
    })


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
_DATA_AGENT_MODELS = {
    "formulario": "apps.platform.dynamic_forms.models.Formulario",
    "formularios": "apps.platform.dynamic_forms.models.Formulario",
    "campo": "apps.platform.dynamic_forms.models.Campo",
    "campos": "apps.platform.dynamic_forms.models.Campo",
    "registro": "apps.platform.dynamic_forms.models.Registro",
    "registros": "apps.platform.dynamic_forms.models.Registro",
    "valor": "apps.platform.dynamic_forms.models.ValorCampo",
    "valores": "apps.platform.dynamic_forms.models.ValorCampo",
    "importacion": "apps.platform.dynamic_forms.models.ImportLog",
    "importaciones": "apps.platform.dynamic_forms.models.ImportLog",
    "auditoria": "apps.platform.dynamic_forms.models.ImportAudit",
    "auditorias": "apps.platform.dynamic_forms.models.ImportAudit",
    "factura": "apps.platform.ai.models.AIAnalysisLog",
    "facturas": "apps.platform.ai.models.AIAnalysisLog",
    "analisis": "apps.platform.ai.models.AIAnalysisLog",
    "analisis_ia": "apps.platform.ai.models.AIAnalysisLog",
    "documento": "apps.platform.ai.models.AIAnalysisLog",
    "documentos": "apps.platform.ai.models.AIAnalysisLog",
    "usuario": "__user_model__",
    "usuarios": "__user_model__",
    "user": "__user_model__",
    "users": "__user_model__",
}

# Form name aliases — maps business keywords to dynamic form names
# so "¿Cuántos productos?" queries Registro filtered by Formulario "Productos"
_FORM_ALIASES = {
    "producto": "Productos",
    "productos": "Productos",
    "venta": "Ventas",
    "ventas": "Ventas",
    "cliente": "Clientes",
    "clientes": "Clientes",
    "inventario": "MovimientosInventario",
    "movimiento": "MovimientosInventario",
    "movimientos": "MovimientosInventario",
}

# Model name -> display name mapping for responses
_DATA_AGENT_LABELS = {
    "Formulario": "formularios",
    "Campo": "campos",
    "Registro": "registros",
    "ValorCampo": "valores",
    "ImportLog": "importaciones",
    "ImportAudit": "auditorías",
    "AIAnalysisLog": "análisis",
    "User": "usuarios",
}

# Supported intent types and their pattern keywords
_DATA_INTENTS = {
    "count": ["cuántos", "cuantos", "cuántas", "cuantas", "cuánto", "cuanto", "total de", "número de", "numero de", "cantidad"],
    "list": ["lista", "listar", "muestra", "muéstrame", "muestrame", "dime", "cuáles son", "cuales son", "qué hay", "que hay"],
    "search": ["busca", "buscar", "encuentra", "encontrar", "búsqueda", "busqueda", "filtrar", "filtra"],
    "top": ["top", "más", "mayor", "mayores", "superior", "primeros", "principales"],
    "group": ["agrupa", "agrupar", "grupo", "grupos", "por tipo", "por categoría", "por categoria", "agrupado", "agrupados"],
    "stats": ["estadística", "estadisticas", "promedio", "media", "suma", "total", "kpi", "indicador"],
    "recent": ["último", "ultimo", "últimos", "ultimos", "reciente", "recientes", "recién", "recien"],
    "compare": ["comparación", "comparacion", "comparar", "vs", "versus", "diferencia", "diferencias"],
    "trend": ["tendencia", "tendencias", "evolución", "evolucion", "cambio", "cambios", "crecimiento"],
}


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


def _detect_data_intent(question: str) -> tuple[str, str, dict]:
    """
    Detect if a question is a data query and extract intent + target model + params.
    
    Returns (intent, model_name, params) or ("", "", {}) if not a data question.
    
    Heuristic-only. No AI call needed for detection.
    """
    q = question.lower().strip()
    
    # 1. Detect target model
    target_model = ""
    for keyword, model_path in _DATA_AGENT_MODELS.items():
        if keyword in q:
            target_model = keyword
            break
    
    # 1b. Check form aliases (producto, venta, cliente, etc.)
    form_alias_found = ""
    if not target_model:
        for alias, form_name in _FORM_ALIASES.items():
            if alias in q:
                form_alias_found = form_name
                target_model = "registros"
                break
    
    # 2. If no model found, check for generic data question patterns
    if not target_model:
        # Check for question patterns that imply data query
        generic_patterns = [
            "cuántos", "cuantas", "cuantos", "total", "lista", "listar",
            "top ", "último", "ultimo", "reciente", "promedio", "suma",
            "kpi", "indicador", "estadística", "estadisticas",
        ]
        if not any(p in q for p in generic_patterns):
            return ("", "", {})  # Not a data question
        # Generic: use Formulario as default if no specific model found
        target_model = "registros"
    
    # 3. Detect intent
    intent = "list"
    for intent_name, patterns in _DATA_INTENTS.items():
        if any(p in q for p in patterns):
            intent = intent_name
            break
    
    # 4. Extract params
    params = {}
    # Apply form filter if alias was resolved
    if form_alias_found:
        params["form_filter"] = form_alias_found
    # Check for filters (active, failed, errors, etc.)
    fail_keywords = ["falló", "fallo", "fallido", "fallaron", "error", "errores", "failed"]
    if any(fk in q for fk in fail_keywords):
        # Filter ImportLog by estado or AIAnalysisLog by success=False
        if "importacion" in q or "importaciones" in q:
            params["filter"] = {"errores__gt": 0}
        elif target_model in ("analisis", "analisis_ia", "documento", "documentos"):
            params["filter"] = {"success": False}
        else:
            params["filter"] = {"success": False}
    elif "activo" in q or "activos" in q:
        # El filtro 'activo' se aplicará con validación dinámica en _execute_safe_query:
        #   - Formulario/Campo → campo 'activo'
        #   - User → mapea a 'is_active'
        #   - Otros modelos → se omite silenciosamente
        params["filter"] = {"activo": True}
    
    # Check for limit (top N, últimos N)
    import re
    # Usar raw string con \s correcto para detectar whitespace
    limit_match = re.search(r"(?:top|últimos?|ultimos?|primeros?)\s*(\d+)", q)
    if limit_match:
        params["limit"] = int(limit_match.group(1))
    elif intent == "recent":
        params["limit"] = 5
    elif intent == "top" and "limit" not in params:
        params["limit"] = 10
    
    # Check for time filters
    if "este mes" in q or "del mes" in q:
        from django.utils import timezone
        from datetime import timedelta
        params["date_filter"] = timezone.now() - timedelta(days=30)
    elif "esta semana" in q or "de la semana" in q:
        from django.utils import timezone
        from datetime import timedelta
        params["date_filter"] = timezone.now() - timedelta(days=7)
    elif "hoy" in q:
        from django.utils import timezone
        from datetime import timedelta
        params["date_filter"] = timezone.now() - timedelta(days=1)
    
    # Check for order
    if "más registros" in q or "más campos" in q or "más" in q:
        params["order"] = "-count"
    
    return (intent, target_model, params)


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
    
    # Resolve model class de forma segura (maneja __user_model__ especial)
    Model = _resolve_data_agent_model(model_path)
    if Model is None:
        return f"No se pudo acceder al modelo para '{model_key}'. Verifica que el módulo esté instalado."
    
    # Build query based on intent
    try:
        qs = Model.objects.all()
        label = _DATA_AGENT_LABELS.get(Model.__name__, model_key)
        model_field_names = {f.name for f in Model._meta.get_fields()}
        from django.db.models import DateField, DateTimeField
        model_date_field_names = {
            f.name for f in Model._meta.get_fields()
            if isinstance(f, (DateField, DateTimeField))
        }
        
        # Apply filters — validate all fields exist on the model first
        filter_kwargs = params.get("filter", {})
        if filter_kwargs:
            # Normalize 'activo' → 'is_active' for User model
            if "activo" in filter_kwargs:
                if not any(f.name == "activo" for f in Model._meta.get_fields()):
                    # El modelo no tiene 'activo' — buscar alternativa
                    if any(f.name == "is_active" for f in Model._meta.get_fields()):
                        filter_kwargs["is_active"] = filter_kwargs.pop("activo")
                    else:
                        filter_kwargs.pop("activo", None)
            safe_filters = _validate_filter_fields(Model, filter_kwargs)
            if safe_filters:
                qs = qs.filter(**safe_filters)
        
        # Apply date filter — validate using model_date_field_names
        date_cutoff = params.get("date_filter")
        if date_cutoff:
            date_field = None
            for field_name in ["created_at", "fecha_creacion", "fecha", "fecha_actualizacion"]:
                if field_name in model_date_field_names:
                    date_field = field_name
                    break
            if date_field:
                qs = qs.filter(**{f"{date_field}__gte": date_cutoff})
        
        # Apply form filter — resolve form name alias to Registro.filter(formulario__nombre=...)
        form_filter = params.get("form_filter")
        if form_filter and Model.__name__ == "Registro":
            qs = qs.filter(formulario__nombre=form_filter)
            label = form_filter.lower()
            # Override label to use pluralized form name for better responses
            _form_label_overrides = {
                "Productos": "productos",
                "Ventas": "ventas",
                "Clientes": "clientes",
                "MovimientosInventario": "movimientos de inventario",
            }
            label = _form_label_overrides.get(form_filter, form_filter.lower())
        
        if intent == "count":
            total = qs.count()
            period = ""
            if date_cutoff:
                days = 30 if params.get("date_filter") else 0
                period = " del período"
            return f"Hay **{total}** {label}{period}."
        
        elif intent == "list" or intent == "search" or intent == "recent":
            limit = params.get("limit", 10)
            order_by = params.get("order", "")
            if params.get("order_field"):
                order_by = params["order_field"]
            
            # Default ordering — validate with model_field_names
            if not order_by:
                for field_name in ["-created_at", "-fecha_creacion", "-fecha", "-id"]:
                    base_name = field_name.lstrip("-")
                    if base_name in model_field_names:
                        order_by = field_name
                        break
            
            if order_by:
                qs = qs.order_by(order_by)
            
            items = list(qs[:limit])
            
            if not items:
                return f"No se encontraron {label}."
            
            # Enrich Registro items with ValorCampo values when form_filter is active
            if form_filter and Model.__name__ == "Registro":
                from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
                try:
                    valores_map = DS.cargar_valores_mapa(items)
                    # Find the identifier field for this form
                    form_obj = items[0].formulario
                    id_campo = form_obj.campos.filter(identificador_principal=True).first()
                    for item in items:
                        v_dict = valores_map.get(item.id, {})
                        if id_campo and id_campo.nombre in v_dict:
                            item._display_name = v_dict[id_campo.nombre]
                        else:
                            # Fallback: use first non-empty text value
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
                
                # Add extra context for recent items
                extra = ""
                for field_name in ["created_at", "fecha_creacion", "fecha", "provider", "document_type"]:
                    if hasattr(item, field_name):
                        val = getattr(item, field_name)
                        if val:
                            if hasattr(val, "strftime"):
                                extra += f" ({val.strftime('%Y-%m-%d')})"
                            else:
                                extra += f" ({val})"
                            break
                result_lines.append(f"  • {name}{extra}")
            
            return f"**{len(items)}** {label}:\n" + "\n".join(result_lines)
        
        elif intent == "top":
            limit = params.get("limit", 10)
            # Try to annotate with count of related objects (validar con _meta)
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
                            c = item.count
                            result_lines.append(f"  • {name}: {c}")
                        return f"**Top {limit}** {label} por cantidad:\n" + "\n".join(result_lines)
            
            # Fallback to simple list if no related models
            return _execute_safe_query("list", model_key, params)
        
        elif intent == "group":
            """Group by a field and count (agrupar)."""
            limit = params.get("limit", 15)
            # Try to group by common field names (validar con model_field_names)
            group_fields = ["tipo", "estado", "provider", "document_type", "service", "modo", "is_active", "is_superuser"]
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
        
        elif intent == "stats":
            total = qs.count()
            lines = [f"**Estadísticas de {label}:**", f"  • Total: {total}"]
            
            # Check for time-based stats (validar con model_field_names)
            for field_name in ["created_at", "fecha_creacion", "fecha"]:
                if field_name in model_field_names:
                    today = timezone.now()
                    week_ago = today - timedelta(days=7)
                    month_ago = today - timedelta(days=30)
                    
                    week_count = qs.filter(**{f"{field_name}__gte": week_ago}).count()
                    month_count = qs.filter(**{f"{field_name}__gte": month_ago}).count()
                    lines.append(f"  • Última semana: {week_count}")
                    lines.append(f"  • Último mes: {month_count}")
                    break
            
            return "\n".join(lines)
        
        elif intent == "compare" or intent == "trend":
            # Simple comparison: show count and recent trend
            total = qs.count()
            today = timezone.now()
            
            lines = [f"**{label.capitalize()}:**", f"  • Total: {total}"]
            
            for field_name in ["created_at", "fecha_creacion", "fecha"]:
                if field_name in model_field_names:
                    this_month = qs.filter(**{f"{field_name}__gte": today - timedelta(days=30)}).count()
                    last_month = qs.filter(
                        **{f"{field_name}__gte": today - timedelta(days=60)},
                        **{f"{field_name}__lt": today - timedelta(days=30)},
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


def _try_data_query(request, question: str) -> dict | None:
    """
    Try to answer a question using the Data Agent (safe ORM queries).
    
    Returns None if the question is not a data query — the caller
    should fall through to ConversationalDocuments.
    
    Returns a response dict if the question was answered.
    """
    import time
    t0 = time.perf_counter()
    
    intent, model_key, params = _detect_data_intent(question)
    
    if not model_key:
        return None  # Not a data question, fall through
    
    # Execute safe query (Django ORM only)
    answer = _execute_safe_query(intent, model_key, params)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    
    # Generate followup suggestions
    followups = []
    if intent == "count":
        followups = ["Muéstrame los detalles", "¿Y cuántos hay activos?", "¿Cómo ha cambiado este mes?"]
    elif intent == "list":
        followups = ["¿Cuántos hay en total?", "¿Puedes filtrar por estado?", "¿Cuáles son los más recientes?"]
    elif intent == "top":
        followups = ["Muéstrame el detalle del primero", "¿Y el ranking inverso?", "¿Cómo ha cambiado con el tiempo?"]
    elif intent == "stats":
        followups = ["Muéstrame la tendencia", "Compara con el mes anterior", "¿Hay anomalías?"]
    elif intent == "trend" or intent == "compare":
        followups = ["¿Qué factores explican este cambio?", "¿Qué recomendaciones harías?", "Genera un reporte ejecutivo"]
    else:
        followups = ["¿Cuántos hay en total?", "Muéstrame más detalles", "¿Qué tendencias observas?"]
    
    return {
        "answer": answer,
        "confidence": 0.95,
        "question_type": f"data_{intent}",
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

    # Learn from user decisions (FASE 9)
    try:
        from apps.platform.document_intelligence.services.memory_learner import MemoryLearner
        learner = MemoryLearner()
        # Get original field names from result_data for rename tracking
        original_field_names = [
            f.get("name", "") for f in (result_data.get("fields", []) or [])
        ]
        for i, f_data in enumerate(field_data):
            original_name = original_field_names[i] if i < len(original_field_names) else ""
            new_name = f_data.get("name", "")
            if original_name and new_name and original_name != new_name:
                learner.learn_field_rename(original_name, new_name)
    except Exception as e:
        logger.warning("MemoryLearner error: %s", e)

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
            # CSV: parse with Python's csv module (no openpyxl, no AI needed)
            import csv as _csv
            with open(tmp_path, newline='', encoding='utf-8-sig') as _f:
                _reader = _csv.reader(_f)
                _raw_headers = next(_reader, [])
                encabezados = [h.strip() for h in _raw_headers if h.strip()]
                filas = []
                for _row in _reader:
                    _fila_dict = {}
                    for i, h in enumerate(encabezados):
                        _fila_dict[h] = _row[i].strip() if i < len(_row) else ''
                    filas.append(_fila_dict)
            from apps.platform.dynamic_forms.models import Campo
            campos = list(Campo.objects.filter(formulario=formulario, activo=True).order_by('orden'))
            mapeo_idx = {}
            for i, campo in enumerate(campos):
                if i < len(encabezados):
                    mapeo_idx[i] = campo.nombre

        else:
            # PDF, images, text: use records (Phase 5 canonical source) first
            records = import_data.get("records", [])
            headers = import_data.get("headers", [])
            rows = import_data.get("rows", [])

            if records:
                # records is list[dict[str, str]] — convert directly to filas
                encabezados = list(records[0].keys())
                filas = records
            elif headers and rows:
                # Fallback: legacy rows format (list of lists)
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

            from apps.platform.dynamic_forms.models import Campo
            campos = list(Campo.objects.filter(formulario=formulario, activo=True).order_by('orden'))
            mapeo_idx = {}
            for i, campo in enumerate(campos):
                if i < len(headers):
                    mapeo_idx[i] = campo.nombre

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
