"""
column_matching.py — Intelligent column detection for Dynamic Forms.

Completely decoupled from import_service.py (no openpyxl dependency).
Reusable for Excel, CSV, APIs, and synchronization.

Architecture:
  - ColumnMatcher: main class, receives field names or a Formulario.
  - ColumnMatchResult: dataclass with match details (method, confidence).
  - normalizar_columna(): standalone normalization function.
  - 4 niveles de matching: exacto, normalizado, sinónimo, similitud (RapidFuzz).
  - Detección de fila de encabezados y hoja óptima.
  - Detección de conflictos entre columnas similares (FASE 4).
  - Explicación detallada del matching (FASE 4).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ======================================================================
# DIAGNÓSTICO — Helpers de instrumentación temporal
# ======================================================================
def _diag_log(stage: str, start: float, detail: str = ''):
    """Registra duración de un paso. Warning si >500ms."""
    elapsed_ms = (time.perf_counter() - start) * 1000
    msg = f'[DIAG] {stage}: {elapsed_ms:.1f}ms'
    if detail:
        msg += f' | {detail}'
    if elapsed_ms > 500:
        logger.warning(f'[DIAG] ⚠ {stage} EXCEDE 500ms: {elapsed_ms:.1f}ms | {detail}')
    else:
        logger.info(msg)
    return time.perf_counter()


def _diag_start(stage: str):
    """Marca inicio de una etapa de diagnóstico."""
    logger.info(f'[DIAG] >>> {stage}')
    return time.perf_counter()

# ---------------------------------------------------------------------------
# Carga opcional de RapidFuzz
# ---------------------------------------------------------------------------
try:
    from rapidfuzz import fuzz as _fuzz
    from rapidfuzz import process as _process
    _HAS_RAPIDFUZZ = True
except ImportError:
    _fuzz = None
    _process = None
    _HAS_RAPIDFUZZ = False

# ---------------------------------------------------------------------------
# Constantes de umbral
# ---------------------------------------------------------------------------
CONFIANZA_AUTO = 90
"""Columnas con confianza >= 90% se asignan automáticamente sin revisión."""

CONFIANZA_REVIEW = 70
"""Columnas con 70% <= confianza < 90% se asignan pero se marcan como 'revisar'."""

CONFIANZA_SUGERIR = 75
"""Umbral legacy para sugerencias (mantenido por compatibilidad)."""

CONFIANZA_MINIMA = 0

# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------

_ACCENT_MAP = {
    'á': 'a', 'à': 'a', 'ä': 'a', 'â': 'a', 'ã': 'a', 'å': 'a',
    'é': 'e', 'è': 'e', 'ë': 'e', 'ê': 'e',
    'í': 'i', 'ì': 'i', 'ï': 'i', 'î': 'i',
    'ó': 'o', 'ò': 'o', 'ö': 'o', 'ô': 'o', 'õ': 'o',
    'ú': 'u', 'ù': 'u', 'ü': 'u', 'û': 'u',
    'ñ': 'n', 'ç': 'c',
}

_TRANSLATION_TABLE = str.maketrans({
    **{k: v for k, v in _ACCENT_MAP.items()},
    **{k.upper(): v.upper() for k, v in _ACCENT_MAP.items()},
})


def normalizar_columna(texto: str) -> str:
    """Normaliza un string de encabezado para comparación flexible."""
    texto = texto.strip().lower()
    texto = texto.translate(_TRANSLATION_TABLE)
    texto = re.sub(r'[/\-_,.]+', ' ', texto)
    texto = re.sub(r'[^a-z0-9 ]', '', texto)
    texto = re.sub(r'\s+', ' ', texto)
    texto = texto.replace(' ', '_')
    return texto.strip('_')


# ---------------------------------------------------------------------------
# Fila helpers (FASE 6: Detección inteligente)
# ---------------------------------------------------------------------------


def _es_fila_vacia(fila: list[Any]) -> bool:
    return not fila or all(c is None or str(c).strip() == '' for c in fila)


def _es_fila_separacion(fila: list[Any]) -> bool:
    if not fila:
        return True
    celdas = [str(c).strip() for c in fila if c is not None and str(c).strip()]
    if not celdas:
        return True
    separadores = {'-', '_', '=', '•', '*', '·', '.', '~', '#', '|'}
    for celda in celdas:
        if not all(c in separadores for c in celda.strip()):
            return False
    return True


def _es_fila_ruido(fila: list[Any]) -> bool:
    if not fila:
        return True
    celdas_con_datos = [c for c in fila if c is not None and str(c).strip()]
    if len(celdas_con_datos) < 2:
        return True
    primero = str(fila[0]).strip().lower() if fila[0] is not None else ''
    patrones_ruido = [
        'empresa:', 'reporte:', 'exportado por:', 'resumen:', 'totales:',
        'notas:', 'fecha:', 'creado:', 'generado:', 'página:', 'pagina:',
        'impreso:', 'filtro:', 'buscar:', 'criterio:', 'selección:', 'seleccion:',
        'parámetros:', 'parametros:', 'desde:', 'hasta:', 'compañía:', 'compania:',
        'dirección:', 'direccion:', 'teléfono:', 'telefono:', 'nit:', 'documento:',
        'cliente:', 'proveedor:', 'gracias', 'atentamente', 'nota:', 'observación:',
        'observacion:', 'company:', 'report:', 'exported by:', 'summary:', 'totals:',
        'notes:', 'date:', 'created:', 'generated:', 'page:', 'printed:', 'filter:',
        'search:', 'criteria:', 'selection:', 'parameters:', 'from:', 'to:',
        'address:', 'phone:', 'thank you', 'sincerely', 'note:', 'remark:',
        'printed by', 'created by', 'generated by', 'exported by',
        'run date', 'run by', 'user:', 'usuario:',
    ]
    for patron in patrones_ruido:
        if primero.startswith(patron):
            return True
    return False


def _es_fila_titulo_repetido(fila: list[Any], headers: list[str]) -> bool:
    if not fila or not headers:
        return False
    primero = str(fila[0]).strip().lower() if fila[0] else ''
    for h in headers:
        if h and h.lower() == primero:
            return True
    return False


def _es_fila_sumario(fila: list[Any]) -> bool:
    if not fila:
        return True
    primero = str(fila[0]).strip().lower() if fila[0] else ''
    if not primero:
        return False
    patrones_sumario = [
        'total:', 'total ', 'subtotal:', 'subtotal ',
        'suma:', 'suma ', 'gran total:', 'grand total:',
        'neto:', 'neto ', 'bruto:', 'bruto ',
        'promedio:', 'promedio ', 'average:', 'average ',
    ]
    for p in patrones_sumario:
        if primero.startswith(p):
            return True
    return False


def _es_fila_logo_texto(fila: list[Any]) -> bool:
    """Detecta filas que parecen texto de logo/encabezado corporativo.
    Ej: "Mi Empresa S.A.S." como primera celda y el resto vacío."""
    if not fila:
        return False
    celdas = [c for c in fila if c is not None and str(c).strip()]
    if len(celdas) == 1 and len(str(celdas[0]).strip()) > 3:
        primero = str(fila[0]).strip().lower()
        # Probablemente nombre de empresa si tiene mayúsculas mezcladas
        if not any(c in ',.:;' for c in primero) and len(primero.split()) <= 5:
            return True
    return False


def _es_fila_nota(fila: list[Any]) -> bool:
    """Detecta filas de notas, comentarios o leyendas."""
    if not fila:
        return False
    primero = str(fila[0]).strip().lower() if fila[0] else ''
    if not primero:
        return False
    patrones_nota = [
        'nota:', 'note:', '*', 'importante:', 'important:', 'leer antes',
        'read before', 'leyenda:', 'legend:', 'convenciones:', 'conventions:',
        'observación:', 'observacion:', 'aclaración:', 'aclaracion:',
    ]
    for p in patrones_nota:
        if primero.startswith(p) or primero == p.rstrip(':'):
            return True
    return False


# ---------------------------------------------------------------------------
# Synonyms loader
# ---------------------------------------------------------------------------

def _cargar_sinonimos() -> dict[str, str]:
    ruta = Path(__file__).resolve().parent / 'data' / 'column_synonyms.json'
    if not ruta.exists():
        logger.warning('Archivo de sinónimos no encontrado: %s', ruta)
        return {}
    try:
        with open(ruta, 'r', encoding='utf-8') as f:
            raw: dict[str, dict[str, list[str]]] = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error('Error cargando sinónimos desde %s: %s', ruta, e)
        return {}
    mapa: dict[str, str] = {}
    for canonical, lang_synonyms in raw.items():
        for _lang, synonyms in lang_synonyms.items():
            for syn in synonyms:
                norm = normalizar_columna(syn)
                if norm and norm not in mapa:
                    mapa[norm] = canonical
    return mapa


_SYNONYM_MAP: dict[str, str] = _cargar_sinonimos()
_ALL_SYNONYM_KEYS: list[str] = sorted(_SYNONYM_MAP.keys()) if _SYNONYM_MAP else []


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class ColumnMatchResult:
    """
    Resultado del matching de una columna.

    Attributes:
        column_index: Índice posicional (0-based) en el array de encabezados.
        column_name: Nombre original del encabezado (sin normalizar).
        matched_to: Nombre del campo en el formulario, o None si no hay match.
        method: Método usado: 'exact', 'normalized', 'synonym', 'fuzzy',
                'manual' o None.
        confidence: Confianza 0.0 – 1.0 (1.0 = coincidencia exacta).
        suggestion: Campo sugerido cuando confidence < threshold_auto.
        explanation: Explicación legible de por qué se eligió este match.
        alternatives: Lista de (campo_nombre, confianza) con alternativas viables.
        conflicts: Lista de nombres de campo que son muy similares y
                   podrían causar confusión.
    """
    column_index: int = -1
    column_name: str = ''
    matched_to: Optional[str] = None
    method: Optional[str] = None
    confidence: float = 0.0
    suggestion: Optional[str] = None
    explanation: str = ''
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ColumnMatcher
# ---------------------------------------------------------------------------


class ColumnMatcher:
    """
    Motor inteligente de matching de columnas para Dynamic Forms.

    Puede inicializarse con:
      - formulario: Instancia de Formulario (usa .campos activos).
      - field_names: Iterable de strings (nombres de campo).

    Cuatro niveles de matching:
      1. Exacto (case-insensitive contra nombres de campo)
      2. Normalizado (normalizar_columna ambas partes)
      3. Sinónimo (diccionario column_synonyms.json)
      4. Similitud (RapidFuzz, umbral configurable)

    Además:
      - Detecta conflictos entre campos muy similares (FASE 4).
      - Proporciona explicación detallada del matching (FASE 4).
      - Lista alternativas viables cuando la confianza es media (FASE 4).
    """

    def __init__(
        self,
        formulario: Any = None,
        field_names: Optional[list[str]] = None,
        threshold_auto: int = CONFIANZA_AUTO,
        threshold_review: int = CONFIANZA_REVIEW,
        threshold_suggest: int = CONFIANZA_SUGERIR,
    ):
        if formulario and field_names:
            raise ValueError('Usar formulario O field_names, no ambos.')

        self._threshold_auto = threshold_auto
        self._threshold_review = threshold_review
        self._threshold_suggest = threshold_suggest

        if formulario is not None:
            if hasattr(formulario, 'campos'):
                qs = formulario.campos.filter(activo=True)
                self._field_names = [c.nombre for c in qs]
            else:
                self._field_names = []
        elif field_names is not None:
            self._field_names = list(field_names)
        else:
            self._field_names = []

        self._field_names_set: set[str] = set(self._field_names)
        self._field_names_norm: dict[str, str] = {
            normalizar_columna(n): n for n in self._field_names
        }
        self._field_names_norm_list: list[str] = list(self._field_names_norm.keys())

        # Cache de normalizados para detección de conflictos
        self._field_names_norm_set: set[str] = set(self._field_names_norm.keys())

    @property
    def field_names(self) -> list[str]:
        return list(self._field_names)

    # ------------------------------------------------------------------
    # Nivel 1: Coincidencia exacta
    # ------------------------------------------------------------------

    def _match_exacto(self, nombre_original: str) -> Optional[str]:
        _t0 = time.perf_counter()
        lower = nombre_original.strip().lower()
        for fn in self._field_names:
            if fn.lower() == lower:
                _diag_log('_match_exacto: HIT', _t0, f'"{nombre_original}" → "{fn}"')
                return fn
        return None

    # ------------------------------------------------------------------
    # Nivel 2: Normalizado
    # ------------------------------------------------------------------

    def _match_normalizado(self, nombre_normalizado: str) -> Optional[str]:
        _t0 = time.perf_counter()
        result = self._field_names_norm.get(nombre_normalizado)
        if result:
            _diag_log('_match_normalizado: HIT', _t0, f'norm="{nombre_normalizado}" → "{result}"')
        return result

    # ------------------------------------------------------------------
    # Nivel 3: Sinónimo
    # ------------------------------------------------------------------

    def _match_sinonimo(self, nombre_normalizado: str) -> Optional[str]:
        _t0 = time.perf_counter()
        canonical = _SYNONYM_MAP.get(nombre_normalizado)
        if canonical and canonical in self._field_names_set:
            _diag_log('_match_sinonimo: HIT', _t0, f'norm="{nombre_normalizado}" → canonical="{canonical}"')
            return canonical
        return None

    # ------------------------------------------------------------------
    # Nivel 4: Similitud (RapidFuzz) — POTENCIAL CUELLO DE BOTELLA
    # ------------------------------------------------------------------

    def _match_fuzzy(self, nombre_normalizado: str) -> Optional[tuple[str, float]]:
        _t0 = time.perf_counter()

        if not _HAS_RAPIDFUZZ or not self._field_names_norm_list:
            if not _HAS_RAPIDFUZZ:
                logger.info('[DIAG] _match_fuzzy: RapidFuzz no disponible')
            return None

        _t_extract1 = _diag_start(f'_match_fuzzy: extractOne(field_names, n={len(self._field_names_norm_list)})')
        result = _process.extractOne(
            nombre_normalizado,
            self._field_names_norm_list,
            scorer=_fuzz.ratio,
            score_cutoff=CONFIANZA_MINIMA,
        )
        _diag_log('_match_fuzzy: extractOne(field_names)', _t_extract1, f'result={result[0] if result else None}, score={result[1] if result else "N/A"}')
        if result:
            choice_norm, score, _idx = result
            if score >= self._threshold_suggest:
                campo_original = self._field_names_norm[choice_norm]
                _diag_log('_match_fuzzy: HIT via field_names', _t0, f'"{nombre_normalizado}" → "{campo_original}" ({score})')
                return campo_original, score / 100.0

        if _ALL_SYNONYM_KEYS:
            _t_extract2 = _diag_start(f'_match_fuzzy: extractOne(synonyms, n={len(_ALL_SYNONYM_KEYS)})')
            result2 = _process.extractOne(
                nombre_normalizado,
                _ALL_SYNONYM_KEYS,
                scorer=_fuzz.ratio,
                score_cutoff=CONFIANZA_MINIMA,
            )
            _diag_log('_match_fuzzy: extractOne(synonyms)', _t_extract2, f'result={result2[0] if result2 else None}, score={result2[1] if result2 else "N/A"}')
            if result2:
                syn_norm, score, _idx = result2
                if score >= self._threshold_suggest:
                    canonical = _SYNONYM_MAP.get(syn_norm)
                    if canonical and canonical in self._field_names_set:
                        _diag_log('_match_fuzzy: HIT via synonyms', _t0, f'"{nombre_normalizado}" → "{canonical}" ({score})')
                        return canonical, score / 100.0

        _diag_log('_match_fuzzy: NO MATCH', _t0, f'"{nombre_normalizado}"')
        return None

    # ------------------------------------------------------------------
    # Explicación y alternativas (FASE 4)
    # ------------------------------------------------------------------

    def _generar_explicacion(
        self, column_name: str, method: Optional[str], matched_to: Optional[str],
        confidence: float
    ) -> str:
        if not matched_to:
            return 'No se encontró una coincidencia suficiente con ningún campo del formulario.'
        map_explicacion = {
            'exact': f'Coincidencia exacta: el nombre "{column_name}" coincide exactamente con el campo "{matched_to}".',
            'normalized': f'Coincidencia normalizada: "{column_name}" → "{matched_to}" (sin acentos/mayúsculas/separadores).',
            'synonym': f'Coincidencia por sinónimo: "{column_name}" es un sinónimo reconocido del campo "{matched_to}".',
            'fuzzy': f'Coincidencia por similitud: "{column_name}" tiene un {confidence:.0%} de semejanza con "{matched_to}".',
            'manual': f'Asignación manual del usuario: "{column_name}" → "{matched_to}".',
        }
        return map_explicacion.get(method or '', 'Coincidencia desconocida.')

    def _detectar_conflictos(self, nombre_normalizado: str) -> list[str]:
        """Detecta campos del formulario muy similares que podrían
        causar ambigüedad con el nombre normalizado dado (FASE 4)."""
        conflictos = []
        for fn_norm, fn_original in self._field_names_norm.items():
            if fn_norm == nombre_normalizado:
                continue
            if fn_norm.startswith(nombre_normalizado) or nombre_normalizado.startswith(fn_norm):
                conflictos.append(fn_original)
            elif _HAS_RAPIDFUZZ:
                ratio = _fuzz.ratio(nombre_normalizado, fn_norm)
                if 80 <= ratio < 100:
                    conflictos.append(fn_original)
            elif fn_norm[:3] == nombre_normalizado[:3] and len(fn_norm) > 3:
                conflictos.append(fn_original)
        return conflictos[:5]

    def _obtener_alternativas(self, nombre_normalizado: str, min_pct: int = 60) -> list[tuple[str, float]]:
        """Obtiene alternativas viables para una columna (FASE 4)."""
        if not _HAS_RAPIDFUZZ or not self._field_names_norm_list:
            return []
        alternativas = _process.extract(
            nombre_normalizado,
            self._field_names_norm_list,
            scorer=_fuzz.ratio,
            score_cutoff=min_pct,
            limit=5,
        )
        result = []
        for choice_norm, score, _idx in alternativas:
            campo = self._field_names_norm.get(choice_norm)
            if campo:
                result.append((campo, score / 100.0))
        return result

    # ------------------------------------------------------------------
    # Match completo (4 niveles) con explicación y conflictos (FASE 4)
    # ------------------------------------------------------------------

    def match_column(self, column_name: str) -> ColumnMatchResult:
        """
        Ejecuta los 4 niveles de matching en secuencia,
        con detección de conflictos y alternativas.

        Args:
            column_name: Nombre del encabezado de columna.

        Returns:
            ColumnMatchResult con la mejor coincidencia encontrada,
            explicación, alternativas y conflictos.
        """
        _t0 = time.perf_counter()
        original = column_name.strip()
        if not original:
            return ColumnMatchResult(
                column_name=original,
                matched_to=None, method=None, confidence=0.0,
                explanation='Columna sin nombre.',
            )

        norm = normalizar_columna(original)

        # Detectar conflictos para la columna
        _t_conflict = _diag_start(f'match_column: detectar_conflictos [{original}]')
        conflictos = self._detectar_conflictos(norm)
        _diag_log('match_column: detectar_conflictos', _t_conflict, f'conflictos={len(conflictos)}')

        # Nivel 1: Exacto
        _t_l1 = _diag_start(f'match_column: nivel1_exacto [{original}]')
        matched = self._match_exacto(original)
        _diag_log('match_column: nivel1_exacto', _t_l1, f'matched={"SÍ" if matched else "NO"}')
        if matched:
            alternativas = self._obtener_alternativas(norm, min_pct=60)
            _diag_log('match_column: COMPLETO', _t0, f'"{original}" → "{matched}" [exacto]')
            return ColumnMatchResult(
                column_name=original,
                matched_to=matched,
                method='exact',
                confidence=1.0,
                explanation=self._generar_explicacion(original, 'exact', matched, 1.0),
                alternatives=[a for a in alternativas if a[0] != matched][:3],
                conflicts=conflictos,
            )

        # Nivel 2: Normalizado
        _t_l2 = _diag_start(f'match_column: nivel2_normalizado [{original}]')
        matched = self._match_normalizado(norm)
        _diag_log('match_column: nivel2_normalizado', _t_l2, f'matched={"SÍ" if matched else "NO"}')
        if matched:
            alternativas = self._obtener_alternativas(norm, min_pct=60)
            _diag_log('match_column: COMPLETO', _t0, f'"{original}" → "{matched}" [normalizado]')
            return ColumnMatchResult(
                column_name=original,
                matched_to=matched,
                method='normalized',
                confidence=0.95,
                explanation=self._generar_explicacion(original, 'normalized', matched, 0.95),
                alternatives=[a for a in alternativas if a[0] != matched][:3],
                conflicts=conflictos,
            )

        # Nivel 3: Sinónimo
        _t_l3 = _diag_start(f'match_column: nivel3_sinonimo [{original}]')
        matched = self._match_sinonimo(norm)
        _diag_log('match_column: nivel3_sinonimo', _t_l3, f'matched={"SÍ" if matched else "NO"}')
        if matched:
            alternativas = self._obtener_alternativas(norm, min_pct=60)
            _diag_log('match_column: COMPLETO', _t0, f'"{original}" → "{matched}" [sinonimo]')
            return ColumnMatchResult(
                column_name=original,
                matched_to=matched,
                method='synonym',
                confidence=0.90,
                explanation=self._generar_explicacion(original, 'synonym', matched, 0.90),
                alternatives=[a for a in alternativas if a[0] != matched][:3],
                conflicts=conflictos,
            )

        # Nivel 4: Fuzzy — POTENCIAL CUELLO DE BOTELLA
        _t_l4 = _diag_start(f'match_column: nivel4_fuzzy [{original}]')
        fuzzy_result = self._match_fuzzy(norm)
        _diag_log('match_column: nivel4_fuzzy', _t_l4, f'matched={"SÍ" if fuzzy_result else "NO"}')
        if fuzzy_result:
            matched, conf = fuzzy_result
            pct = int(conf * 100)
            _t_alt = _diag_start(f'match_column: obtener_alternativas [{original}]')
            alternativas = self._obtener_alternativas(norm, min_pct=60)
            _diag_log('match_column: obtener_alternativas', _t_alt)
            _diag_log('match_column: COMPLETO', _t0, f'"{original}" → "{matched}" [fuzzy, conf={conf:.3f}]')
            if pct >= self._threshold_auto:
                return ColumnMatchResult(
                    column_name=original,
                    matched_to=matched,
                    method='fuzzy',
                    confidence=conf,
                    explanation=self._generar_explicacion(original, 'fuzzy', matched, conf),
                    alternatives=[a for a in alternativas if a[0] != matched][:3],
                    conflicts=conflictos,
                )
            elif pct >= self._threshold_review:
                return ColumnMatchResult(
                    column_name=original,
                    matched_to=matched,
                    method='fuzzy_review',
                    confidence=conf,
                    explanation=f'Similitud del {pct}% con "{matched}". Requiere revisión.',
                    alternatives=[a for a in alternativas if a[0] != matched][:3],
                    conflicts=conflictos,
                )
            else:
                return ColumnMatchResult(
                    column_name=original,
                    matched_to=None,
                    method=None,
                    confidence=conf,
                    suggestion=matched,
                    explanation=f'Similitud del {pct}% con "{matched}", pero no supera el umbral mínimo del {self._threshold_review}%.',
                    alternatives=[a for a in alternativas if a[0] != matched][:3],
                    conflicts=conflictos,
                )

        # Sin coincidencia — mostrar alternativas si las hay
        _t_alt_final = _diag_start(f'match_column: obtener_alternativas_final [{original}]')
        alternativas = self._obtener_alternativas(norm, min_pct=40)
        if alternativas:
            top_alt = alternativas[0]
            return ColumnMatchResult(
                column_name=original,
                matched_to=None,
                method=None,
                confidence=0.0,
                suggestion=top_alt[0],
                explanation=f'No se encontró una coincidencia aceptable. '
                           f'La alternativa más cercana es "{top_alt[0]}" con {top_alt[1]:.0%} de similitud.',
                alternatives=alternativas[:3],
                conflicts=conflictos,
            )

        return ColumnMatchResult(
            column_name=original,
            matched_to=None,
            method=None,
            confidence=0.0,
            explanation='No se encontró ninguna coincidencia con los campos del formulario.',
        )

    def match_all(self, column_names: list[str]) -> list[ColumnMatchResult]:
        """Aplica match_column a todos los encabezados."""
        _t0 = time.perf_counter()
        logger.info(f'[DIAG] >>> match_all: {len(column_names)} columnas: {column_names}')
        results = []
        for idx, name in enumerate(column_names):
            _t_col = time.perf_counter()
            r = self.match_column(name)
            r.column_index = idx
            col_ms = (time.perf_counter() - _t_col) * 1000
            if col_ms > 500:
                logger.warning(f'[DIAG] ⚠ match_all: columna[{idx}]="{name}" tomó {col_ms:.1f}ms')
            results.append(r)
        _diag_log('match_all: COMPLETO', _t0, f'{len(column_names)} columnas, {sum(1 for r in results if r.matched_to)} matched')
        return results

    # ------------------------------------------------------------------
    # Build mapping
    # ------------------------------------------------------------------

    def build_mapping(
        self,
        headers: list[str],
        user_overrides: Optional[dict[int, str]] = None,
    ) -> tuple[dict[int, str], list[str], list[ColumnMatchResult]]:
        results = self.match_all(headers)

        if user_overrides:
            for idx, campo_nombre in user_overrides.items():
                if 0 <= idx < len(results):
                    results[idx].matched_to = campo_nombre
                    results[idx].method = 'manual'
                    results[idx].confidence = 1.0
                    results[idx].explanation = (
                        f'Asignación manual del usuario: "{headers[idx]}" → "{campo_nombre}".'
                    )

        mapeo = {}
        for r in results:
            if r.matched_to:
                mapeo[r.column_index] = r.matched_to

        mapeados = set(mapeo.values())
        sin_mapear = [fn for fn in self._field_names if fn not in mapeados]

        return mapeo, sin_mapear, results

    # ------------------------------------------------------------------
    # Detección de fila de encabezados
    # ------------------------------------------------------------------

    @staticmethod
    def _calcular_puntaje_header(
        fila: list[Any],
        field_names_norm: set[str],
    ) -> float:
        _t0 = time.perf_counter()
        if not fila:
            return 0.0
        valores = [str(c).strip() for c in fila if c is not None]
        if len(valores) < 2:
            return 0.0
        coincidencias = 0
        for v in valores:
            if v and normalizar_columna(v) in field_names_norm:
                coincidencias += 1
        if 3 <= len(valores) <= 25:
            coincidencias += 0.5
        if _es_fila_ruido(fila):
            coincidencias -= 2
        result = max(coincidencias / max(len(valores), 1), 0.0)
        # No log every call — this runs for every row; only log if slow
        elapsed_ms = (time.perf_counter() - _t0) * 1000
        if elapsed_ms > 100:
            logger.info(f'[DIAG] _calcular_puntaje_header: {elapsed_ms:.1f}ms | valores={len(valores)}, score={result:.4f}')
        return result

    def detect_best_header_row(
        self,
        raw_rows: list[list[Any]],
        max_rows: int = 20,
        min_match_pct: float = 0.15,
    ) -> tuple[Optional[int], list[str], float]:
        _t0 = time.perf_counter()
        if not raw_rows:
            return 0, [], 0.0

        field_norm_set = set(self._field_names_norm.keys())
        rows_to_check = raw_rows[:max_rows]
        best_idx = 0
        best_score = -1.0
        best_headers: list[str] = []

        logger.info(f'[DIAG] detect_best_header_row: revisando {len(rows_to_check)} filas de {len(raw_rows)} totales')

        for idx, row in enumerate(rows_to_check):
            if row is None:
                continue
            row_str = [str(c).strip() if c is not None else '' for c in row]
            _t_score = time.perf_counter()
            score = self._calcular_puntaje_header(row_str, field_norm_set)
            score_ms = (time.perf_counter() - _t_score) * 1000
            if score > best_score:
                best_score = score
                best_idx = idx
                best_headers = row_str
            if score_ms > 50:
                logger.info(f'[DIAG] detect_best_header_row: fila[{idx}] score={score:.4f} ({score_ms:.1f}ms)')

        if best_score < min_match_pct:
            logger.warning(f'[DIAG] detect_best_header_row: best_score={best_score:.4f} < min={min_match_pct}, falling back to row 0')
            best_idx = 0
            best_score = 0.0
            best_headers = [str(c).strip() if c is not None else ''
                            for c in raw_rows[0]] if raw_rows else []

        _diag_log('detect_best_header_row', _t0, f'best_row={best_idx}, score={best_score:.4f}')
        return best_idx, best_headers, best_score

    # ------------------------------------------------------------------
    # Detección de primera fila de datos (FASE 6 mejorada)
    # ------------------------------------------------------------------

    def detect_data_start_row(
        self,
        raw_rows: list[list[Any]],
        header_row_idx: int,
        headers: list[str],
    ) -> int:
        _t0 = time.perf_counter()
        if not raw_rows or header_row_idx >= len(raw_rows) - 1:
            return header_row_idx + 1

        rows_checked = 0
        for idx in range(header_row_idx + 1, len(raw_rows)):
            row = raw_rows[idx]
            if row is None:
                continue
            row_str = [str(c).strip() if c is not None else '' for c in row]

            if all(not c for c in row_str):
                rows_checked += 1
                continue
            if _es_fila_separacion(row):
                rows_checked += 1
                continue
            if _es_fila_logo_texto(row):
                rows_checked += 1
                continue
            if _es_fila_nota(row):
                rows_checked += 1
                continue
            if _es_fila_ruido(row):
                rows_checked += 1
                continue
            if _es_fila_titulo_repetido(row, headers):
                rows_checked += 1
                continue
            if _es_fila_sumario(row):
                rows_checked += 1
                continue

            celdas_datos = sum(1 for c in row_str if c)
            rows_checked += 1
            if celdas_datos >= 2:
                _diag_log('detect_data_start_row', _t0, f'found at idx={idx}, skipped={rows_checked - 1} rows')
                return idx

        _diag_log('detect_data_start_row', _t0, f'not found (scanned {rows_checked} rows), returning header_row_idx+1')
        return header_row_idx + 1

    # ------------------------------------------------------------------
    # Puntaje de hoja
    # ------------------------------------------------------------------

    def score_sheet(
        self,
        sheet_name: str,
        raw_rows: list[list[Any]],
    ) -> float:
        _t0 = time.perf_counter()
        _row_idx, _headers, header_score = self.detect_best_header_row(raw_rows)

        sheet_norm = normalizar_columna(sheet_name)
        bonus = 0.0
        if sheet_norm:
            for fn in self._field_names_norm:
                if sheet_norm in fn or fn in sheet_norm:
                    bonus = 0.15
                    break

        penalizacion = 0.0
        sheet_lower = sheet_name.lower().strip()
        hojas_resumen = [
            'resumen', 'summary', 'dashboard', 'instrucciones',
            'instructions', 'readme', 'notas', 'notes', 'índice',
            'index', 'cover', 'portada', 'glosario', 'glossary',
            'configuración', 'configuration', 'config', 'settings',
        ]
        for hr in hojas_resumen:
            if hr == sheet_lower or sheet_lower.startswith(hr):
                penalizacion = 0.5
                break

        if len(raw_rows) < 3:
            penalizacion = max(penalizacion, 0.3)

        result = max(min(header_score + bonus - penalizacion, 1.0), 0.0)
        _diag_log('score_sheet', _t0, f'sheet="{sheet_name}", header_score={header_score:.4f}, bonus={bonus}, penalty={penalizacion}, final={result:.4f}')
        return result

    # ------------------------------------------------------------------
    # Calidad del archivo (FASE 7)
    # ------------------------------------------------------------------

    def calcular_calidad(
        self,
        results: list[ColumnMatchResult],
        total_columns: int,
    ) -> dict:
        """
        Calcula métricas de calidad del matching.

        Returns:
            dict con:
              - score: 0.0 – 1.0
              - estrellas: int (1-5)
              - etiqueta: str
              - recomendaciones: list[str]
              - metricas: dict con desglose
        """
        if total_columns == 0:
            return {
                'score': 0.0, 'estrellas': 1, 'etiqueta': 'Muy mala',
                'recomendaciones': ['No se detectaron columnas.'],
                'metricas': {},
            }

        matched = [r for r in results if r.matched_to]
        pct_matched = len(matched) / total_columns
        conf_promedio = (sum(r.confidence for r in matched) / len(matched)) if matched else 0.0

        # Penalizar fuzzy matches
        n_fuzzy = sum(1 for r in matched if r.method == 'fuzzy')
        fuzzy_penalizacion = (n_fuzzy / len(matched)) * 0.15 if matched else 0

        # Penalizar columnas sin match
        sin_match = total_columns - len(matched)
        sin_match_penalizacion = (sin_match / total_columns) * 0.3

        score_base = (pct_matched * 0.5 + conf_promedio * 0.5)
        score = max(0.0, min(1.0, score_base - fuzzy_penalizacion - sin_match_penalizacion))

        estrellas = max(1, min(5, round(score * 5)))
        etiquetas = {5: 'Excelente', 4: 'Buena', 3: 'Regular', 2: 'Mala', 1: 'Muy mala'}

        recomendaciones = []
        if sin_match > 0:
            recomendaciones.append(
                f'{sin_match} columna(s) sin mapear. Revisa el mapeo manual.'
            )
        if n_fuzzy > 0:
            recomendaciones.append(
                f'{n_fuzzy} columna(s) mapeadas por similitud difusa. '
                'Verifica que los campos sean correctos.'
            )
        if conf_promedio < 0.85:
            recomendaciones.append(
                'La confianza promedio es baja. Considera renombrar las columnas '
                'del Excel para que coincidan con los nombres del formulario.'
            )

        return {
            'score': round(score, 2),
            'estrellas': estrellas,
            'etiqueta': etiquetas[estrellas],
            'recomendaciones': recomendaciones,
            'metricas': {
                'total_columnas': total_columns,
                'mapeadas': len(matched),
                'sin_mapear': sin_match,
                'exactas': sum(1 for r in matched if r.method == 'exact'),
                'normalizadas': sum(1 for r in matched if r.method == 'normalized'),
                'sinonimos': sum(1 for r in matched if r.method == 'synonym'),
                'fuzzy': n_fuzzy,
                'manuales': sum(1 for r in matched if r.method == 'manual'),
                'confianza_promedio': round(conf_promedio, 2),
            },
        }
