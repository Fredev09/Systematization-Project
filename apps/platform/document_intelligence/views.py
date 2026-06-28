"""
views.py — Document Intelligence Platform views.

Independent section with:
  - Dashboard: landing page with options
  - Create Form with AI: upload file → analyze → review → create
  - Scan Invoice: upload image/PDF → extract → review
  - History: view past AI analyses
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render

from apps.platform.ai.models import AIAnalysisLog
from apps.platform.ai.providers import get_provider
from apps.platform.document_intelligence.services.pipeline import (
    DocumentIntelligencePipeline,
    PipelineConfig,
    PipelineResult,
)
from apps.platform.document_intelligence.services.memory_learner import MemoryLearner
from config.permissions import admin_required, es_administrador, rol_usuario

logger = logging.getLogger(__name__)    # Allowed file types
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
    if file.size > MAX_UPLOAD_SIZE:
        return f"File too large ({file.size / 1024 / 1024:.1f} MB). Max: 50 MB."
    ext = Path(file.name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"Extension '{ext}' not supported. Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
    return None


@login_required(login_url="login")
def dashboard(request):
    """Document Intelligence landing page."""
    stats = {}
    try:
        stats = AIAnalysisLog.get_stats(days=30)
    except Exception as e:
        logger.warning("Could not load AI stats: %s", e)

    return render(request, "document_intelligence/dashboard.html", {
        "stats": stats,
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
    ctx = _document_upload_context(request)

    file = request.FILES.get("document_file")
    error = _validate_upload(file)
    if error:
        messages.error(request, error)
        return render(request, "document_intelligence/document_upload.html", ctx)

    from django.conf import settings
    tmp_dir = Path(settings.BASE_DIR) / ".tmp_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / file.name
    with open(tmp_path, "wb") as f:
        for chunk in file.chunks():
            f.write(chunk)

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

        request.session["di_pipeline_result"]["similar_forms"] = similar_forms

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
        if tmp_path.exists():
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        return render(request, "document_intelligence/document_upload.html", ctx)


def _serialize_pipeline_result(result, tmp_path, file_name):
    """Serialize PipelineResult to session-safe dict."""
    from apps.platform.ai.utils import safe_json_parse
    return {
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
    }


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
        tmp_path = tmp_dir / file.name
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
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    return render(request, "document_intelligence/scan_invoice.html", {
        "es_admin": es_administrador(request.user),
        "rol_usuario": rol_usuario(request.user),
    })


@login_required(login_url="login")
@admin_required
def history(request):
    """View past AI analyses."""
    page = int(request.GET.get("page", 1))
    per_page = 25
    start = (page - 1) * per_page

    logs = AIAnalysisLog.objects.all().order_by("-created_at")[start:start + per_page]
    total = AIAnalysisLog.objects.count()
    total_pages = max(1, (total + per_page - 1) // per_page)

    return render(request, "document_intelligence/history.html", {
        "logs": logs,
        "page": page,
        "total_pages": total_pages,
        "es_admin": es_administrador(request.user),
        "rol_usuario": rol_usuario(request.user),
    })


# ── Handler functions ──


def _handle_analyze(request):
    """Upload + analyze file."""
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

    # Save to temp file
    from django.conf import settings
    tmp_dir = Path(settings.BASE_DIR) / ".tmp_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / file.name
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
            return render(request, "document_intelligence/create_from_file.html", {
                "es_admin": es_administrador(request.user),
                "rol_usuario": rol_usuario(request.user),
                "tipos_campo": tipos_campo,
            })

        # Store in session for next steps
        request.session["di_pipeline_result"] = {
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
        }

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

        request.session["di_pipeline_result"]["similar_forms"] = similar_forms

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
        if tmp_path.exists():
            tmp_path.unlink()
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

    from apps.platform.dynamic_forms.models import Formulario, Campo

    form_name = request.POST.get("form_name", result_data.get("form_name", "Untitled"))
    form_description = request.POST.get("form_description", result_data.get("form_description", ""))
    identifier_field_name = request.POST.get("identifier_field", "")

    # Create the form
    formulario = Formulario.objects.create(
        nombre=form_name,
        descripcion=form_description,
        creado_por=request.user,
    )

    # Create fields from JSON editor data
    field_data = []
    try:
        field_data = json.loads(request.POST.get("fields_json", "[]"))
    except (json.JSONDecodeError, TypeError):
        field_data = result_data.get("fields", [])

    has_identifier = False
    for idx, f_data in enumerate(field_data):
        f_name = f_data.get("name", f"campo_{idx}")
        f_type = f_data.get("type", "texto")

        # Determine if this field is the identifier
        is_id = f_data.get("is_identifier", False)
        if identifier_field_name and f_name == identifier_field_name:
            is_id = True

        if is_id:
            has_identifier = True

        # Build metadata
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

        # Parse options for list type
        options = f_data.get("options", None)
        if isinstance(options, list) and len(options) > 0:
            pass  # Already a list
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
        "tmp_path": tmp_path,
        "file_name": result_data.get("file_name", ""),
    }

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
        from apps.platform.dynamic_forms.models import Formulario
        from apps.platform.dynamic_forms.import_service import (
            analyze_workbook,
            previsualizar,
            importar,
        )

        formulario = Formulario.objects.get(id=formulario_id)
        analysis = analyze_workbook(tmp_path, formulario)
        encabezados = analysis["encabezados"]
        filas = analysis["filas"]
        match_results = analysis["match_results"]

        mapeo_idx = {}
        for r in match_results:
            if r.matched_to:
                mapeo_idx[r.column_index] = r.matched_to

        preview = previsualizar(formulario, encabezados, filas, mapeo_idx)
        valid_rows = [r for r in preview if r["valida"]]

        if not valid_rows:
            messages.warning(request, "No valid rows to import.")
            return redirect("document_intelligence:create_from_file")

        result = importar(
            formulario, valid_rows,
            usuario=request.user, modo="crear", mapeo=mapeo_idx,
        )

        messages.success(
            request,
            f"Imported {result['creados']} records into '{formulario.nombre}'."
            f"{' Warnings: ' + str(result['errores'][:3]) if result['errores'] else ''}"
        )

        # Clean up
        for key in ["di_pipeline_result", "di_import_ready"]:
            request.session.pop(key, None)
        path = Path(tmp_path)
        if path.exists():
            path.unlink()

        return redirect("dynamic_forms:ver_registros", formulario_id=formulario.id)

    except Exception as e:
        logger.exception("Import failed")
        messages.error(request, f"Import failed: {e}")
        return redirect("document_intelligence:create_from_file")
