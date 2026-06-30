"""
decision_engine.py — AI Decision Engine (FASE 3, v4.0 FREE-FIRST).

Antes de llamar a cualquier IA, analiza:

  ¿Realmente hace falta IA?

Ejemplos de cuándo NO usar IA:
  - Excel con encabezados claros → heurísticas
  - CSV simple → matching clásico
  - Factura perfectamente estructurada → extracción directa
  - Columnas con nombres estándar → tipos predecibles

Cuándo SÍ usar IA:
  - Imagen/escaneo/foto (necesita OCR)
  - PDF sin estructura clara
  - Documento con formato ambiguo
  - Datos no estructurados

FREE-FIRST priority: NO usar IA a menos que sea realmente necesario.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from apps.platform.ai.types import FieldType

logger = logging.getLogger(__name__)


# ======================================================================
# ChatIntent — Clasificación de preguntas del chat
# ======================================================================

@dataclass
class ChatIntent:
    """Resultado de clasificación de una pregunta del chat."""
    intent_type: str = "unknown"
    # 'data_query', 'document_question', 'form_creation', 'general_chat', 'search', 'unknown'
    sub_intent: str = ""
    # 'count', 'list', 'search', 'compare', 'top', 'bottom', 'trend',
    # 'average', 'sum', 'max', 'min', 'latest', 'oldest', 'exists',
    # 'statistics', 'group'
    target_model: str = ""
    # Model key from _DATA_AGENT_MODELS
    form_alias: str = ""
    # Form name from _FORM_ALIASES
    params: dict = field(default_factory=dict)
    # Filters, limits, order, date filters
    confidence: float = 0.0
    can_answer_without_ai: bool = False
    explanation: str = ""
    follow_up: bool = False
    # True if this intent was inherited from a previous context (follow-up question)


# ======================================================================
# CENTRALIZED ROUTING DATA — single source of truth
# ======================================================================
# All routing constants live here. views.py imports from this file.
# ======================================================================

# Model whitelist: keyword → dotted model path for safe ORM access
_DATA_AGENT_MODELS: dict[str, str] = {
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

# Model class name → display label for human-readable responses
_DATA_AGENT_LABELS: dict[str, str] = {
    "Formulario": "formularios",
    "Campo": "campos",
    "Registro": "registros",
    "ValorCampo": "valores",
    "ImportLog": "importaciones",
    "ImportAudit": "auditorías",
    "AIAnalysisLog": "análisis",
    "User": "usuarios",
}

# Business keyword → dynamic form name mapping for Registro queries
# "¿Cuántos productos?" → Registro.objects.filter(formulario__nombre="Productos")
_FORM_ALIASES: dict[str, str] = {
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

# ======================================================================
# Public accessors (views.py uses these instead of internal vars)
# ======================================================================

def get_data_agent_models() -> dict[str, str]:
    return dict(_DATA_AGENT_MODELS)

def get_data_agent_labels() -> dict[str, str]:
    return dict(_DATA_AGENT_LABELS)

def get_form_aliases() -> dict[str, str]:
    return dict(_FORM_ALIASES)


# ======================================================================
# Chat Intent Detection Patterns
# ======================================================================

# Patrones de detección de intents para el chat
_GENERIC_DATA_PATTERNS: list[str] = [
    "cuantos", "cuantas", "cuanto", "cuanta", "list", "lista", "listar",
    "muestrame", "muéstrame", "mostrar", "ver", "dime", "consulta",
    "busca", "buscar", "encuentra", "encontrar", "todos", "todas",
    "existe", "existen", "hay", "cuales", "cuales son", "quien",
    "quienes", "registros", "formularios", "campos", "valores",
    "importacion", "exporta", "exportar",
]

_CHAT_MODEL_KEYWORDS: dict[str, list[str]] = {
    "formulario": ["formulario", "formularios"],
    "campo": ["campo", "campos"],
    "registro": ["registro", "registros"],
    "valor": ["valor", "valores"],
    "importacion": ["importacion", "importaciones", "importado"],
    "analisis": ["analisis", "documento", "documentos"],
    "usuario": ["usuario", "usuarios"],
    "producto": ["producto", "productos"],
    "venta": ["venta", "ventas"],
    "cliente": ["cliente", "clientes"],
}

_CHAT_INTENT_PATTERNS: dict[str, list[str]] = {
    "count": [
        r"\bcu[aá]ntos?\b", r"\bcu[aá]ntas?\b", r"\bcu[aá]nto\b",
        r"\btotal de\b", r"\bn[uú]mero de\b", r"\bcantidad\b",
        r"\bcu[aá]ntos\s+hay\b",
    ],
    "list": [
        r"\blist[ao]\w*\b", r"\bmu[ée]str[ae]\w*\b", r"\bdime\b",
        r"\bcu[aá]les son\b", r"\bqu[eé] hay\b", r"\bmu[ée]strame\b",
        r"\btodos\w*\s+los\b", r"\blos\s+\w+\s+registrados?\b",
    ],
    "search": [
        r"\bb[uú]squed[ai]\b", r"\bbusc[ao]\w*\b", r"\bencontr[ai]\w*\b",
    ],
    "filter": [
        r"\bfiltr[ai]\w*\b", r"\bfiltro\b", r"\bque\s+(fall[oó]|fallar[oó]|fallid[oas])\b",
        r"\bcon\s+error\b", r"\bactivos?\b", r"\binactivos?\b",
        r"\bcon\s+problemas?\b", r"\bpendientes?\b",
    ],
    "compare": [
        r"\bcompar[ai]\w*\b", r"\bcomparaci[oó]n\b", r"\bvs\b",
        r"\bversus\b", r"\bdiferencias?\b", r"\bdistint[oas]\b",
    ],
    "top": [
        r"\btop\b", r"\bm[aá]s\s+(grande|alto|caro|vendido|com[úu]n|frecuente)\b",
        r"\bmayor(es)?\b", r"\bprimeros?\b", r"\bprincipales?\b",
        r"\bsuperior(es)?\b",
    ],
    "bottom": [
        r"\bmenos\s+(grande|alto|caro|vendido|com[úu]n|frecuente)\b",
        r"\bmenor(es)?\b", r"\bpeor(es)?\b", r"\binferior(es)?\b",
        r"\bm[íi]nimo\b", r"\bm[íi]nimos?\b",
    ],
    "trend": [
        r"\btendenci[ai]\b", r"\bevoluci[oó]n\b", r"\bcambi[oó]\b",
        r"\bcrecimient[oó]\b", r"\bdisminuci[oó]n\b",
        r"\baument[oó]\b", r"\bgr[aá]fic[oai]\b",
    ],
    "average": [
        r"\bpromedi[oó]\b", r"\bmedi[ao]\b", r"\bmedia aritm[ée]tica\b",
        r"\bpromedio de\b",
    ],
    "sum": [
        r"\bsum[ao]\b", r"\bsumatoria\b", r"\bsumar\b",
        r"\bcu[aá]nto\s+(cuesta|vale|suma|gan[ao])\b",
        r"\bingres[oó]\b", r"\bingresos?\b",
    ],
    "max": [
        r"\bm[aá]xim[oas]\b", r"\bel\s+m[aá]s\s+(grande|alto|caro|largo|nuevo|reciente)\b",
        r"\br[ée]cord\b",
        r"\bm[aá]s\s+car[oao]\b",
    ],
    "min": [
        r"\bm[íi]nim[oas]\b", r"\bel\s+menos\s+(grande|alto|caro|largo|nuevo|reciente)\b",
        r"\bbarat[oao]\b",
    ],
    "latest": [
        r"\b[uú]ltim[oas]\b", r"\breciente(s)?\b", r"\breci[eé]n\b",
        r"\bnuev[oas]\b",
    ],
    "oldest": [
        r"\bprimer[oa]\s+(registro|venta|producto|cliente|formulario|importaci[oó]n)\b",
        r"\bm[aá]s\s+antigu[oas]\b", r"\bantigu[oas]\b",
        r"\bprimeros?\s+registro\w*\b",
    ],
    "exists": [
        r"\bexiste?\b", r"\bhay\s+(un|una|alg[uú]n|alguna)\b",
        r"\btengo\s+(alg[uú]n|alguna|un)\b", r"\btiene\b",
        r"\bexiste\s+alg[uú]n\b",
    ],
    "statistics": [
        r"\bestad[ií]stic[ao]?\b", r"\bkpi\b", r"\bindicador(es)?\b",
        r"\bpanel\b", r"\bresumen?\b", r"\breporte?\b",
        r"\bdashboard\b",
    ],
    "group": [
        r"\bagrup[ai]\w*\b", r"\bgrupo\b", r"\bgrupos\b",
        r"\bpor tipo\b", r"\bpor categor[ií]a\b",
        r"\bagrupad[oas]\b", r"\bclasific[ai]\w*\b",
    ],
}


def _match_keywords_word_boundary(keywords: list[str], q: str) -> bool:
    """Check if any keyword matches the question using word boundaries.
    
    Prevents false positives from substring matching (e.g., "import" inside "importe").
    Uses \b word boundaries with re.escape for safety.
    """
    for kw in sorted(keywords, key=len, reverse=True):
        if re.search(r'\b' + re.escape(kw) + r'\b', q, re.IGNORECASE):
            return True
    return False


def _safe_int_match(q: str, pattern: str, default: int = 0) -> int:
    """Extract first integer from regex match in question."""
    m = re.search(pattern, q, re.IGNORECASE)
    return int(m.group(1)) if m else default


# ======================================================================
# Palabras clave de encabezados de columna que indican que NO se necesita IA
# ======================================================================

_STANDARD_HEADERS: set[str] = {
    # Español
    "nombre", "descripción", "descripcion", "precio", "valor", "costo",
    "cantidad", "stock", "existencia", "unidad", "medida",
    "código", "codigo", "id", "identificador", "sku", "referencia",
    "fecha", "hora", "fecha_hora", "fechahora",
    "categoría", "categoria", "tipo", "clase", "grupo",
    "estado", "activo", "activo?", "habilitado",
    "email", "correo", "teléfono", "telefono", "celular",
    "dirección", "direccion", "ciudad", "departamento", "país", "pais",
    "notas", "observaciones", "comentarios",
    "total", "subtotal", "iva", "descuento",
    # Inglés
    "name", "description", "price", "value", "cost", "quantity",
    "code", "identifier", "sku", "reference",
    "date", "time", "datetime", "category", "type",
    "status", "active", "enabled", "email", "phone",
    "address", "city", "country", "notes", "comments",
    "total", "subtotal", "tax", "discount",
}

# Encabezados que indican datos financieros (no necesitan IA para detectar tipo)
_FINANCIAL_HEADERS: set[str] = {
    "precio", "price", "valor", "value", "costo", "cost",
    "total", "subtotal", "iva", "tax", "descuento", "discount",
    "salario", "salary", "ingreso", "income", "gasto", "expense",
}

# Extensiones que TÍPICAMENTE necesitan IA
_AI_REQUIRED_EXTS: set[str] = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff",
}

# Extensiones que NUNCA necesitan IA
_NO_AI_EXTS: set[str] = {".csv", ".json", ".xml", ".yaml", ".yml", ".tsv"}

# Patrones de seguimiento — preguntas que heredan contexto de la anterior
# NOTA: Se usan con re.search() para soportar patrones regex completos
_FOLLOWUP_PATTERNS: list[str] = [
    r"pero cu[aá]l", r"cu[aá]l de ell[oa]s", r"cu[aá]l de los",
    r"^es[eo]$", r"^es[eo] mism[oa]$", r"el anterior", r"el [uú]ltim[oa]",
    r"el primero", r"mu[ée]stral[oa]", r"expl[ií]cal[oa]",
    r"contin[uú]a", r"dame m[aá]s detalle", r"d[aá]me m[aá]s",
    r"y ahora", r"tambi[eé]n", r"cu[aá]nto",
    r"cu[aá]l[es]?",
    r"cu[aá]l fue", r"cu[aá]l es", r"cu[aá]les son",
    r"explica eso", r"explica de nuevo",
    r"siguiente", r"anterior", r"lo mism[oa]",
    r"adelante", r"prosigue", r"sigue",
    r"desarrolla eso", r"desarr[oó]llalo", r"a ver",
    r"expl[ií]came", r"de que se trata", r"cu[ée]ntame m[aá]s",
    # Demostrativos de referencia (solo con sustantivo para evitar falsos positivos)
    r"\bese\s+formulario\b", r"\bes[ea]\s+formulario\b",
    r"\bese\s+mism[oa]\b",
    r"\bdich[oa]\s+formulario\b", r"\bdich[oa]\s+dato\b",
    r"\beste\s+formulario\b", r"\besta\s+informaci[oó]n\b",
    r"\bel\s+mencionad[oa]\b",
    r"\btiene\s+registros?\b",
]


@dataclass
class DecisionResult:
    """Resultado de la decisión: ¿usar IA o no?"""
    use_ai: bool
    reason: str = ""
    confidence: float = 1.0
    suggested_provider: str = ""
    suggested_task_type: str = ""
    estimated_tokens: int = 0
    alternatives: list[str] = field(default_factory=list)


class AIDecisionEngine:
    """
    Decide si una tarea necesita IA o puede resolverse con heurísticas.

    Reglas FREE-FIRST:
      1. Si se puede resolver sin IA → hacerlo sin IA
      2. Si hay duda → intentar sin IA primero, validar después
      3. Solo usar IA cuando sea estrictamente necesario

    Usage:
        engine = AIDecisionEngine()
        decision = engine.decide(
            file_name="productos.xlsx",
            headers=["Nombre", "Precio", "Stock"],
            sample_rows=[["Laptop", "1500000", "10"]],
        )
        if decision.use_ai:
            # llamar IA
        else:
            # usar heurísticas locales
    """

    def decide(
        self,
        file_name: str = "",
        headers: Optional[list[str]] = None,
        sample_rows: Optional[list[list[str]]] = None,
        raw_text: str = "",
        task: str = "",
        detected_type: str = "",
    ) -> DecisionResult:
        """
        Decide si se necesita IA para esta tarea.

        Args:
            file_name: Nombre del archivo.
            headers: Encabezados de columna (si aplica).
            sample_rows: Filas de ejemplo (si aplica).
            raw_text: Texto extraído del documento.
            task: Descripción de la tarea.
            detected_type: Tipo de documento ya detectado.

        Returns:
            DecisionResult con recomendación.
        """
        ext = Path(file_name).suffix.lower() if file_name else ""

        # ── REGLA 1: Extensiones que REQUIEREN IA (imágenes, fotos) ──
        if ext in _AI_REQUIRED_EXTS:
            return DecisionResult(
                use_ai=True,
                reason=f"Imagen ({ext}) — requiere OCR/IA para extraer texto",
                suggested_provider="gemini",
                suggested_task_type="ocr",
                confidence=0.95,
            )

        # ── REGLA 2: Tipos ya detectados que REQUIEREN IA ──
        if detected_type == "image":
            return DecisionResult(
                use_ai=True,
                reason="Documento tipo imagen — requiere IA para análisis visual",
                suggested_task_type="ocr",
                confidence=0.95,
            )

        # ── REGLA 3: Extensiones que NUNCA necesitan IA ──
        if ext in _NO_AI_EXTS:
            return DecisionResult(
                use_ai=False,
                reason=f"Formato estructurado ({ext}) — se puede procesar con heurísticas",
                confidence=0.95,
            )

        # ── REGLA 4: Encabezados claros → NO IA ──
        if headers and len(headers) >= 2:
            result = self._evaluate_headers(headers, sample_rows)
            if not result.use_ai:
                return result

        # ── REGLA 5: Texto estructurado (CSV-like, tablas) → NO IA ──
        if raw_text:
            result = self._evaluate_text(raw_text)
            if not result.use_ai:
                return result

        # ── REGLA 6: Tarea específica del usuario ──
        if task:
            result = self._evaluate_task(task)
            return result

        # ── DEFAULT: Usar IA (seguro) ──
        return DecisionResult(
            use_ai=True,
            reason="No se pudo determinar si es procesable sin IA. Usando IA por seguridad.",
            confidence=0.5,
            suggested_task_type="general",
        )

    def _evaluate_headers(
        self,
        headers: list[str],
        sample_rows: Optional[list[list[str]]],
    ) -> DecisionResult:
        """Evalúa si los encabezados son suficientemente claros para NO usar IA."""
        clean_headers = [h.lower().strip() for h in headers]

        # Contar cuántos encabezados son "estándar" (conocidos)
        standard_count = sum(1 for h in clean_headers if h in _STANDARD_HEADERS)
        ratio = standard_count / len(headers) if headers else 0

        # Si ≥70% son estándar → NO necesitamos IA
        if ratio >= 0.7:
            # Detectar tipo de datos automáticamente
            financial = any(h in _FINANCIAL_HEADERS for h in clean_headers)
            return DecisionResult(
                use_ai=False,
                reason=f"{standard_count}/{len(headers)} encabezados son estándar ({ratio:.0%}). "
                       "Se puede inferir tipos con heurísticas.",
                confidence=0.85 + (ratio - 0.7) * 0.3,
                alternatives=["Usar FieldDetector.heuristic_detect()"],
            )

        # Si ≥50% son estándar → probablemente no necesitamos IA
        if ratio >= 0.5:
            return DecisionResult(
                use_ai=False,
                reason=f"{standard_count}/{len(headers)} encabezados son estándar. "
                       "Intento con heurísticas primero, IA como fallback.",
                confidence=0.65,
                alternatives=[
                    "Usar FieldDetector.heuristic_detect() primero",
                    "Si confianza < 0.5, llamar IA",
                ],
            )

        # Muchos encabezados no estándar → podría necesitar IA
        return DecisionResult(
            use_ai=True,
            reason=f"Solo {standard_count}/{len(headers)} encabezados son estándar. "
                   "Los nombres no estándar requieren análisis semántico.",
            confidence=0.6,
            suggested_task_type="field_detection",
            estimated_tokens=max(500, len(headers) * 100),
        )

    def _evaluate_text(self, raw_text: str) -> DecisionResult:
        """Evalúa si el texto estructurado necesita IA."""
        lines = raw_text.strip().split("\n")

        # Si tiene menos de 3 líneas, probablemente no es tabla
        if len(lines) < 3:
            return DecisionResult(
                use_ai=True,
                reason="Texto muy corto — podría necesitar IA para interpretar",
                confidence=0.4,
                suggested_task_type="general",
            )

        # Si tiene delimitadores consistentes (|, ;, \t), probablemente es tabla
        first_line = lines[0].strip() if lines else ""
        delimiters = ["|", ";", "\t", ","]
        delim_count = sum(1 for d in delimiters if d in first_line)

        if delim_count >= 1:
            return DecisionResult(
                use_ai=False,
                reason="Texto con estructura tabular detectada. Procesable con heurísticas.",
                confidence=0.8,
                alternatives=["Parsear con split por delimitador"],
            )

        # Texto largo sin estructura clara → probablemente necesita IA
        return DecisionResult(
            use_ai=True,
            reason="Texto sin estructura tabular clara — requiere análisis semántico.",
            confidence=0.5,
            suggested_task_type="general",
        )

    def _evaluate_task(self, task: str) -> DecisionResult:
        """Evalúa si la tarea del usuario necesita IA."""
        task_lower = task.lower()

        # Tareas que definitivamente necesitan IA
        ai_keywords = [
            "analiza", "analizar", "interpreta", "interpretar",
            "resume", "resumen", "sintetiza", "describe",
            "recomienda", "sugiere", "compara", "compara",
            "genera", "crea", "propón", "propon",
            "qué opinas", "qué piensas", "cómo ves",
        ]
        if any(kw in task_lower for kw in ai_keywords):
            return DecisionResult(
                use_ai=True,
                reason="La tarea requiere análisis semántico/IA",
                confidence=0.9,
                suggested_task_type="general",
            )

        # Tareas que NO necesitan IA
        no_ai_keywords = [
            "extraer", "exportar", "importar", "listar",
            "ordenar", "filtrar", "buscar", "contar",
            "mostrar", "calcular", "sumar", "promedio",
        ]
        if any(kw in task_lower for kw in no_ai_keywords):
            return DecisionResult(
                use_ai=False,
                reason="La tarea es procedimental — no requiere IA",
                confidence=0.85,
            )

        # Indeterminado
        return DecisionResult(
            use_ai=True,
            reason="No se pudo clasificar la tarea. Usando IA por seguridad.",
            confidence=0.5,
            suggested_task_type="general",
        )


    # ════════════════════════════════════════════════════════════════
    # Chat Intent Classification (Phase 7)
    # ════════════════════════════════════════════════════════════════

    def classify_chat(self, question: str, previous_context: Optional[ChatIntent] = None) -> ChatIntent:
        """
        Clasifica una pregunta del chat en un intent estructurado.

        Retorna ChatIntent con tipo, subtipo, modelo objetivo, alias
        de formulario, parámetros y confianza.

        Si se proporciona previous_context (de una pregunta anterior) y la
        pregunta actual es un seguimiento (follow-up), se heredan el intent,
        sub_intent, modelo, alias, filtros y agregación del contexto anterior
        en lugar de reclasificar desde cero.
        """
        q = question.lower().strip()
        result = ChatIntent(explanation="Intento no detectado")

        # ── STEP 0: Detectar follow-up y heredar contexto ──
        # Usar re.search() en lugar de substring para soportar patrones regex
        is_follow_up = any(re.search(p, q) for p in _FOLLOWUP_PATTERNS)
        if is_follow_up and previous_context is not None:
            logger.info(
                "Follow-up detected (q='%s'), inheriting context: intent=%s sub_intent=%s model=%s alias=%s",
                q[:50], previous_context.intent_type, previous_context.sub_intent,
                previous_context.target_model, previous_context.form_alias,
            )
            result.intent_type = previous_context.intent_type
            result.sub_intent = previous_context.sub_intent
            result.target_model = previous_context.target_model
            result.form_alias = previous_context.form_alias
            result.params = dict(previous_context.params)
            result.confidence = min(previous_context.confidence + 0.1, 0.95)
            result.can_answer_without_ai = previous_context.can_answer_without_ai
            result.explanation = f"Follow-up heredado de: {previous_context.explanation}"
            result.follow_up = True
            return result

        # ── STEP 0: Detectar si es pregunta de datos genérica ──
        is_data_question = any(re.search(r'\b' + re.escape(p) + r'\b', q) for p in _GENERIC_DATA_PATTERNS)

        # ── STEP 1: Detectar sub_intent (más específico) ──
        matched_intents = []
        for intent_name, patterns in _CHAT_INTENT_PATTERNS.items():
            if any(re.search(p, q) for p in patterns):
                matched_intents.append(intent_name)

        # ── STEP 2: Detectar target model (word-boundary aware) ──
        target_model = ""
        matched_models: dict[str, int] = {}
        for model_key, keywords in _CHAT_MODEL_KEYWORDS.items():
            if _match_keywords_word_boundary(keywords, q):
                matched_models[model_key] = sum(len(kw) for kw in keywords if re.search(r'\b' + re.escape(kw) + r'\b', q, re.IGNORECASE))
        if matched_models:
            # Conflict resolution: "documento" in question → prefer "analisis" over other models
            if len(matched_models) > 1 and "analisis" in matched_models:
                if re.search(r'\bdocumento\w*\b', q, re.IGNORECASE):
                    target_model = "analisis"
            if not target_model:
                target_model = max(matched_models, key=matched_models.get)
        # Level 2 fallback: verb stem matching for Spanish conjugations
        # "importe", "importaste", "importaron", "importaria" → "importacion"
        if not target_model and re.search(r'\bimport\w*\b', q, re.IGNORECASE):
            target_model = "importacion"

        # ── STEP 3: Detectar form alias ──
        form_alias_found = ""
        if not target_model:
            for alias, fname in _FORM_ALIASES.items():
                if re.search(r'\b' + re.escape(alias) + r'\b', q):
                    form_alias_found = fname
                    target_model = "registro"
                    break

        # ── STEP 4: Extraer parámetros ──
        params = {}
        if form_alias_found:
            params["form_filter"] = form_alias_found

        # Limit detection
        limit = _safe_int_match(q, r"(?:top|primeros?|[uú]ltimos?|primer[oa]s?)\s*(\d+)")
        if limit:
            params["limit"] = limit

        # Combined filter detection — supports multiple simultaneous filters
        filters = []

        # Failure/error filter
        for fail_word in ["falló", "fallo", "fallido", "fallaron", "error", "errores", "failed"]:
            if fail_word in q:
                filters.append({"field": "success", "op": "exact", "value": False})
                break

        # Active/inactive filter
        activo_in_q = "activo" in q or "activos" in q
        inactivo_in_q = "inactivo" in q or "inactivos" in q
        if activo_in_q and not inactivo_in_q:
            if form_alias_found:
                filters.append({"field": "activo", "op": "exact", "value": "Sí"})
            else:
                params["filter_activo"] = True
        elif inactivo_in_q:
            if form_alias_found:
                filters.append({"field": "activo", "op": "exact", "value": "No"})

        # Escaped comma filter — "con problemas", "pendientes"
        for status_word in ["pendientes", "pendiente"]:
            if status_word in q:
                params["pending"] = True
                break

        if filters:
            params["filters"] = filters

        # Date filter
        if "este mes" in q or "del mes" in q or "mensual" in q:
            params["date_range"] = "month"
        elif "esta semana" in q or "de la semana" in q:
            params["date_range"] = "week"
        elif "hoy" in q:
            params["date_range"] = "today"
        elif "este año" in q or "anual" in q:
            params["date_range"] = "year"

        # Order / sort detection
        if "más registros" in q or "más campos" in q:
            params["order"] = "-count"
        if "menos registros" in q or "menos campos" in q:
            params["order"] = "count"

        # Aggregation field detection (for sum, average, max, min)
        for word in ["precio", "precios", "total", "totales", "stock",
                      "valor", "valores", "cantidad", "costos", "costo",
                      "ingreso", "ingresos", "ventas", "venta"]:
            if word in q:
                if "sum" in matched_intents or "average" in matched_intents:
                    params["aggregate_field"] = word
                break

        # Implicit date range for trend/compare/latest
        if "trend" in matched_intents or "compare" in matched_intents:
            if "date_range" not in params:
                params["date_range"] = "month"
        if "latest" in matched_intents or "last" in matched_intents:
            if "limit" not in params:
                params["limit"] = 5
        if "oldest" in matched_intents:
            if "limit" not in params:
                params["limit"] = 5

        # ── STEP 5: Determinar intent_type ──
        intent_type = "unknown"
        can_answer_without_ai = False

        # Form creation
        if re.search(r"\b(crea?|genera?|nuev[oa])\b.*\b(formulario|form)\b", q):
            intent_type = "form_creation"
            result.explanation = "Detección de creación de formulario"
            result.confidence = 0.85
            result.params = params
            result.form_alias = form_alias_found
            return result

        # Document question
        if re.search(r"\b(resume?|resumir|analiza|analizar|eval[uú]a|explica|interpreta)\b", q):
            intent_type = "document_question"
            result.explanation = "Pregunta sobre análisis/documento"
            result.confidence = 0.75
            result.params = params
            result.form_alias = form_alias_found
            return result

        # Data query detection
        has_form_alias = bool(form_alias_found)
        has_model = bool(target_model)
        has_sub_intent = len(matched_intents) > 0

        if has_model and has_sub_intent:
            # Strong signal: explicit model + explicit intent
            intent_type = "data_query"
            can_answer_without_ai = True
            result.confidence = 0.9
            result.explanation = f"Modelo '{target_model}' + intent '{matched_intents[0]}'"
        elif is_data_question and has_model:
            intent_type = "data_query"
            can_answer_without_ai = True
            result.confidence = 0.8
            result.explanation = f"Pregunta genérica de datos + modelo '{target_model}'"
        elif is_data_question and has_sub_intent and target_model:
            intent_type = "data_query"
            can_answer_without_ai = True
            result.confidence = 0.7
            result.explanation = f"Pregunta genérica de datos + intent '{matched_intents[0]}'"
        elif has_form_alias and has_sub_intent:
            intent_type = "data_query"
            can_answer_without_ai = True
            result.confidence = 0.75
            target_model = "registro"
            result.explanation = f"Alias '{form_alias_found}' + intent '{matched_intents[0]}'"
        elif is_data_question and target_model:
            intent_type = "data_query"
            can_answer_without_ai = True
            result.confidence = 0.6
            result.explanation = f"Pregunta genérica de datos para '{target_model}'"
        # Umbral mínimo: si no hay modelo objetivo ni alias, no forzar data_query
        # Esto evita responder datos incorrectos con baja confianza

        # Search (fallback de data_query que busca en todo)
        if intent_type == "unknown" and "busca" in q or "encuentra" in q or "dónde" in q or "cómo encuentro" in q:
            intent_type = "search"
            can_answer_without_ai = True
            result.confidence = 0.65
            target_model = "registro"
            result.explanation = "Búsqueda genérica"

        # ── STEP 6: Determinar sub_intent final ──
        if matched_intents:
            # Priority ordering
            intent_priority = [
                "exists", "count", "sum", "average", "max", "min",
                "top", "bottom", "compare", "trend", "statistics",
                "latest", "oldest", "list", "search", "group",
            ]
            for prio in intent_priority:
                if prio in matched_intents:
                    result.sub_intent = prio
                    break
            if not result.sub_intent and matched_intents:
                result.sub_intent = matched_intents[0]
        elif is_data_question:
            result.sub_intent = "list"

        # ── STEP 7: Set target model default ──
        if not target_model and result.sub_intent in ("count", "list", "statistics"):
            target_model = "registro"

        result.intent_type = intent_type
        result.target_model = target_model
        result.form_alias = form_alias_found
        result.params = params
        result.can_answer_without_ai = can_answer_without_ai

        if intent_type == "unknown":
            result.intent_type = "general_chat"
            result.confidence = 0.3
            result.explanation = "Intento no detectado → general_chat"
            result.can_answer_without_ai = False

        return result


# Singleton
_default_decision: Optional[AIDecisionEngine] = None


def get_decision_engine() -> AIDecisionEngine:
    """Return the default AIDecisionEngine instance (singleton)."""
    global _default_decision
    if _default_decision is None:
        _default_decision = AIDecisionEngine()
    return _default_decision
