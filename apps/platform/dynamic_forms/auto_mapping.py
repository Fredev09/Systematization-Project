"""
auto_mapping.py — Clasificación automática de mapeo de columnas.

Analiza los resultados de ColumnMatcher y clasifica cada columna en
tres categorías según su nivel de confianza:

  - auto (>=90%): Asignación automática, no requiere intervención.
  - review (70-90%): Asignación automática pero marcada para revisión.
  - manual (<70% o sin match): Requiere selección manual del usuario.

Además determina si se puede saltar la pantalla de mapeo.

Orquestación completa:
  1. ColumnMatcher.match_all() — matching clásico 4 niveles.
  2. MappingMemoryManager — recupera mapeos previos.
  3. AIMatcher — matching semántico para columnas no resueltas.
  4. AutoMappingAnalyzer.analyze() — clasificación final.
  5. decidir_accion() — único punto de decisión: mapeo vs preview.

INSTRUMENTACIÓN:
  - analyze_full() registra por columna el resultado en cada fase.
  - La auditoría se guarda en summary.audit_log como lista de dicts.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from .column_matching import ColumnMatchResult, ColumnMatcher

logger = logging.getLogger(__name__)

# Umbrales de confianza
CONFIANZA_AUTO: float = 0.90
"""Columnas con confianza >= 90% se asignan automáticamente sin revisión."""

CONFIANZA_REVIEW: float = 0.70
"""Columnas con confianza >= 70% se asignan automáticamente pero se marcan como 'revisar'."""

CONFIANZA_MINIMA: float = 0.0
"""Columnas por debajo de este umbral no tienen asignación."""

# Umbrales para decisión de saltar mapeo (más permisivos que el clasificador)
CONFIANZA_SALTAR_MAPEO: float = 0.92
"""Confianza promedio mínima para saltar la pantalla de mapeo."""


@dataclass
class AuditEntry:
    """Traza de una columna a través de todas las fases del pipeline."""
    column_index: int
    column_name: str
    phase1_matcher: Optional[str] = None       # matched_to tras ColumnMatcher
    phase1_confidence: float = 0.0
    phase1_method: Optional[str] = None
    phase2_memory: Optional[str] = None        # matched_to tras MappingMemory
    phase2_applied: bool = False
    phase3_ai: Optional[str] = None            # matched_to tras AIMatcher
    phase3_applied: bool = False
    phase3_ai_confidence: float = 0.0
    final_matched_to: Optional[str] = None     # matched_to final
    final_confidence: float = 0.0
    final_method: Optional[str] = None
    final_category: str = 'manual'             # auto / review / manual
    conflicts: list[str] = field(default_factory=list)
    unmapped_form_field: bool = False          # True si es campo del form sin mapear


@dataclass
class ColumnClassification:
    """
    Clasificación de una columna individual después del análisis.
    """
    column_index: int
    column_name: str
    matched_to: Optional[str] = None
    confidence: float = 0.0
    method: Optional[str] = None
    category: str = 'manual'
    """Categoría: 'auto', 'review', o 'manual'."""
    explanation: str = ''
    suggestion: Optional[str] = None
    alternatives: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class MappingSummary:
    """
    Resumen completo del análisis de mapeo automático.
    """
    total: int = 0
    auto: int = 0
    review: int = 0
    manual: int = 0
    columnas: list[ColumnClassification] = field(default_factory=list)

    # --- Control de decisión (único punto) ---
    puede_saltar_mapeo: bool = False
    """True si el sistema puede saltar la pantalla de mapeo."""
    motivo_no_saltar: list[str] = field(default_factory=list)
    """Razones por las que NO se puede saltar el mapeo. Vacío si puede_saltar."""

    necesita_revision: bool = False
    """True si hay columnas en categoría 'review'."""
    necesita_manual: bool = False
    """True si hay columnas en categoría 'manual'."""
    confianza_promedio: float = 0.0

    # --- Enriquecimiento ---
    memoria_usada: bool = False
    ai_usada: bool = False
    memory_mapping: Optional[dict[int, str]] = None

    # --- Validación ---
    campos_obligatorios_faltantes: list[str] = field(default_factory=list)
    conflictos_presentes: bool = False
    """True si alguna columna tiene conflictos detectados."""
    columnas_extra: int = 0
    """Columnas del Excel sin ninguna relación con el formulario (se ignoran)."""

    # --- Trazabilidad ---
    audit_log: list[dict] = field(default_factory=list)
    """Lista de AuditEntry serializados para depuración."""


class AutoMappingAnalyzer:
    """
    Analiza los resultados de ColumnMatcher y produce una clasificación
    detallada del estado de cada columna.

    Clasificación:
      - auto:   matched_to está asignado y confidence >= 0.90
      - review: matched_to está asignado y 0.70 <= confidence < 0.90
      - manual: matched_to es None, o confidence < 0.70
    """

    def __init__(
        self,
        threshold_auto: float = CONFIANZA_AUTO,
        threshold_review: float = CONFIANZA_REVIEW,
        threshold_skip: float = CONFIANZA_SALTAR_MAPEO,
    ):
        self.threshold_auto = threshold_auto
        self.threshold_review = threshold_review
        self.threshold_skip = threshold_skip

    def classify_column(self, result: ColumnMatchResult) -> ColumnClassification:
        """Clasifica una columna individual según su confianza."""
        if result.matched_to and result.confidence >= self.threshold_auto:
            category = 'auto'
        elif result.matched_to and result.confidence >= self.threshold_review:
            category = 'review'
        else:
            category = 'manual'

        return ColumnClassification(
            column_index=result.column_index,
            column_name=result.column_name,
            matched_to=result.matched_to,
            confidence=result.confidence,
            method=result.method,
            category=category,
            explanation=result.explanation,
            suggestion=result.suggestion,
            alternatives=result.alternatives,
        )

    def analyze(
        self,
        match_results: list[ColumnMatchResult],
    ) -> MappingSummary:
        """
        Analiza todos los resultados de matching y produce un resumen.

        Args:
            match_results: Lista de ColumnMatchResult de ColumnMatcher.

        Returns:
            MappingSummary con clasificación detallada.
        """
        columnas: list[ColumnClassification] = []
        counts = {'auto': 0, 'review': 0, 'manual': 0}
        conf_acumulada = 0.0

        for r in match_results:
            if not r.column_name:
                continue
            cc = self.classify_column(r)
            columnas.append(cc)
            counts[cc.category] += 1
            conf_acumulada += cc.confidence

        total = len(columnas)
        conf_promedio = conf_acumulada / total if total > 0 else 0.0

        return MappingSummary(
            total=total,
            auto=counts['auto'],
            review=counts['review'],
            manual=counts['manual'],
            columnas=columnas,
            # NOTA: puede_saltar_mapeo NO se calcula aquí.
            # Se recalcula exclusivamente en decidir_accion(),
            # que es el ÚNICO punto de decisión.
            # Inicializamos en False para evitar confusiones.
            puede_saltar_mapeo=False,
            necesita_revision=counts['review'] > 0,
            necesita_manual=counts['manual'] > 0,
            confianza_promedio=conf_promedio,
        )

    # ==================================================================
    # ÚNICO PUNTO DE DECISIÓN
    # ==================================================================

    def decidir_accion(
        self,
        summary: MappingSummary,
        formulario,
        campos_activos,
        excluded_types: Optional[set[str]] = None,
    ) -> MappingSummary:
        """
        Decide si se puede saltar la pantalla de mapeo.

        Reglas (ordenadas):
          1. Si hay campos obligatorios sin mapear → NO saltar.
          2. Si hay conflictos entre columnas similares → NO saltar.
          3. Si la confianza promedio < threshold_skip → NO saltar.
          4. Si hay columnas 'manual' sin resolver → NO saltar.
          5. Si todo lo anterior está bien → SALTAR (incluso si hay
             columnas opcionales sin mapear en el Excel).

        Esto reemplaza la lógica anterior que exigía 100% de todas
        las columnas (incluyendo opcionales extra del Excel).

        Args:
            summary: MappingSummary del análisis.
            formulario: Instancia de Formulario.
            campos_activos: QuerySet de campos activos.
            excluded_types: Tipos excluidos del mapeo.

        Returns:
            MappingSummary actualizado con puede_saltar_mapeo y
            motivo_no_saltar.
        """
        motivos: list[str] = []
        excluded = excluded_types or {'calculado', 'imagen', 'archivo'}

        # =============================================================
        # FASE 0: Diagnosticar columnas extra del Excel
        # (DEBE ocurrir antes de las reglas para que la confianza
        #  promedio corregida esté disponible para la Regla 3)
        # =============================================================
        manual_con_sugerencia = [
            cc for cc in summary.columnas
            if cc.category == 'manual'
            and (cc.suggestion or cc.alternatives)
        ]
        manual_sin_relacion = [
            cc for cc in summary.columnas
            if cc.category == 'manual'
            and not cc.suggestion
            and not cc.alternatives
            and not cc.matched_to
        ]

        # Actualizar conteo de 'manual' (solo las que necesitan atención)
        summary.columnas_extra = len(manual_sin_relacion)
        summary.manual = len(manual_con_sugerencia)

        if manual_sin_relacion:
            logger.info(
                f'[DECISION] {len(manual_sin_relacion)} columna(s) extra del Excel '
                f'sin relación con el formulario: '
                f'{[cc.column_name for cc in manual_sin_relacion]} — ignoradas'
            )

        # Recalcular confianza promedio excluyendo columnas extra
        # (ANTES de la Regla 3 para que use el valor corregido)
        cols_relevantes = [
            cc for cc in summary.columnas
            if not (cc.category == 'manual'
                    and not cc.suggestion
                    and not cc.alternatives
                    and not cc.matched_to)
        ]
        if cols_relevantes:
            summary.confianza_promedio = (
                sum(cc.confidence for cc in cols_relevantes)
                / len(cols_relevantes)
            )

        # =============================================================
        # REGLA 1: Campos obligatorios faltantes
        # =============================================================
        campos_mapeados_set = {
            cc.matched_to for cc in summary.columnas
            if cc.matched_to
        }
        for campo in campos_activos:
            if campo.obligatorio and campo.tipo not in excluded:
                if campo.nombre not in campos_mapeados_set:
                    motivos.append(
                        f'Campo obligatorio "{campo.nombre}" no está mapeado'
                    )

        # =============================================================
        # REGLA 2: Conflictos entre columnas
        # =============================================================
        if summary.conflictos_presentes:
            motivos.append(
                'Se detectaron conflictos entre columnas similares. '
                'Requiere revisión manual.'
            )

        # =============================================================
        # REGLA 3: Confianza global (usa valor corregido, sin columnas extra)
        # =============================================================
        if summary.confianza_promedio < self.threshold_skip:
            motivos.append(
                f'Confianza promedio ({summary.confianza_promedio:.1%}) '
                f'inferior al umbral ({self.threshold_skip:.0%})'
            )

        # =============================================================
        # REGLA 4: Columnas manuales con sugerencia (baja confianza)
        # =============================================================
        if manual_con_sugerencia:
            names = [cc.column_name for cc in manual_con_sugerencia]
            if len(names) <= 3:
                motivos.append(
                    f'Columnas con baja confianza: {", ".join(names)}'
                )
            else:
                motivos.append(
                    f'{len(names)} columnas con baja confianza'
                )

        # =============================================================
        # DECISIÓN FINAL
        # =============================================================
        summary.puede_saltar_mapeo = len(motivos) == 0
        summary.motivo_no_saltar = motivos

        logger.info(
            f'[DECISION] puede_saltar={summary.puede_saltar_mapeo}, '
            f'motivos={len(motivos)}'
        )
        for m in motivos:
            logger.info(f'[DECISION]   → {m}')

        return summary

    # ==================================================================
    # ORQUESTACIÓN COMPLETA (con instrumentación)
    # ==================================================================

    def analyze_full(
        self,
        formulario,
        encabezados: list[str],
        campos_activos,
        field_names: Optional[list[str]] = None,
        excluded_types: Optional[set[str]] = None,
    ) -> MappingSummary:
        """
        Orquestación completa del análisis de mapeo:
          1. ColumnMatcher.match_all() — matching clásico 4 niveles.
          2. MappingMemoryManager.load() — recupera mapeos previos.
          3. MappingMemoryManager.apply_memory_to_results() — aplica memoria.
          4. AIMatcher — matching semántico para columnas no resueltas.
          5. AutoMappingAnalyzer.analyze() — clasificación final.
          6. decidir_accion() — decisión unificada.

        Con instrumentación: cada columna tiene trazabilidad por fase
        en summary.audit_log.

        Args:
            formulario: Instancia de Formulario.
            encabezados: Lista de nombres de columna del Excel.
            campos_activos: QuerySet de campos activos del formulario.
            field_names: Lista opcional de nombres de campo.
            excluded_types: Tipos de campo a excluir del mapeo.

        Returns:
            MappingSummary completo con decisión y auditoría.
        """
        _t0 = time.perf_counter()

        if field_names is None:
            field_names = [c.nombre for c in campos_activos]
        if excluded_types is None:
            excluded_types = {'calculado', 'imagen', 'archivo'}

        field_names_filtrados = [
            fn for fn in field_names
            if fn not in (
                c.nombre for c in campos_activos
                if c.tipo in excluded_types
            )
        ]

        # Inicializar auditoría: una entrada por columna del Excel
        audit_map: dict[int, AuditEntry] = {
            idx: AuditEntry(
                column_index=idx,
                column_name=name,
            )
            for idx, name in enumerate(encabezados)
            if name  # ignorar columnas sin nombre
        }

        logger.info(
            f'[AUTO] analyze_full: {len(encabezados)} encabezados, '
            f'{len(field_names_filtrados)} campos activos (filtrados)'
        )

        # =============================================================
        # Fase 1: ColumnMatcher — Matching clásico 4 niveles
        # =============================================================
        _t1 = time.perf_counter()
        matcher = ColumnMatcher(formulario=formulario)
        match_results = matcher.match_all(encabezados)

        # Registrar fase 1 en auditoría
        for r in match_results:
            if r.column_index in audit_map:
                entry = audit_map[r.column_index]
                entry.phase1_matcher = r.matched_to
                entry.phase1_confidence = r.confidence
                entry.phase1_method = r.method
                entry.conflicts = r.conflicts

        elapsed1 = (time.perf_counter() - _t1) * 1000
        logger.info(
            f'[AUTO] Fase 1 — ColumnMatcher: {elapsed1:.1f}ms, '
            f'{sum(1 for r in match_results if r.matched_to)}/{len(match_results)} matched'
        )

        # =============================================================
        # Fase 2: MappingMemory — Recuperar mapeos previos
        # =============================================================
        _t2 = time.perf_counter()
        memoria_usada = False
        memory_mapping = None
        try:
            from .mapping_memory import MappingMemoryManager
            memory_mapping = MappingMemoryManager.load(
                formulario.id, encabezados
            )
            if memory_mapping:
                match_results = MappingMemoryManager.apply_memory_to_results(
                    memory_mapping, match_results, encabezados
                )
                memoria_usada = True

                # Registrar fase 2 en auditoría
                for r in match_results:
                    if r.column_index in audit_map:
                        entry = audit_map[r.column_index]
                        if r.method == 'memory':
                            entry.phase2_memory = r.matched_to
                            entry.phase2_applied = True

                logger.info(
                    f'[AUTO] Fase 2 — MappingMemory: aplicado con '
                    f'{len(memory_mapping)} entradas'
                )
        except Exception as e:
            logger.warning(f'[AUTO] Fase 2 — MappingMemory error: {e}')
        elapsed2 = (time.perf_counter() - _t2) * 1000
        logger.info(f'[AUTO] Fase 2 — MappingMemory: {elapsed2:.1f}ms')

        # =============================================================
        # Fase 3: AIMatcher — Matching semántico (solo no resueltas)
        # =============================================================
        _t3 = time.perf_counter()
        ai_usada = False
        unresolved = [
            (r.column_index, r.column_name)
            for r in match_results
            if not r.matched_to and r.column_name
        ]
        logger.info(
            f'[AUTO] Fase 3 — AIMatcher: {len(unresolved)} columnas no resueltas: '
            f'{[name for _, name in unresolved]}'
        )
        if unresolved:
            try:
                from .ai_matcher import AIMatcher
                ai_matcher = AIMatcher()
                if ai_matcher.available:
                    ai_results = ai_matcher.match_unresolved(
                        unresolved, field_names_filtrados
                    )
                    ai_map = {r.column_index: r for r in ai_results}
                    for i, r in enumerate(match_results):
                        if r.column_index in ai_map and ai_map[r.column_index].matched_to:
                            ai_r = ai_map[r.column_index]
                            match_results[i] = ai_r
                            ai_usada = True

                            # Registrar fase 3 en auditoría
                            if r.column_index in audit_map:
                                entry = audit_map[r.column_index]
                                entry.phase3_ai = ai_r.matched_to
                                entry.phase3_applied = True
                                entry.phase3_ai_confidence = ai_r.confidence

                    if ai_usada:
                        logger.info(
                            f'[AUTO] Fase 3 — AIMatcher: {len(unresolved)} enviadas, '
                            f'{sum(1 for r in ai_results if r.matched_to)} resueltas'
                        )
                else:
                    logger.info('[AUTO] Fase 3 — AIMatcher: no disponible (sin API key)')
            except Exception as e:
                logger.warning(f'[AUTO] Fase 3 — AIMatcher error: {e}')
        else:
            logger.info('[AUTO] Fase 3 — AIMatcher: no hay columnas no resueltas')
        elapsed3 = (time.perf_counter() - _t3) * 1000
        logger.info(f'[AUTO] Fase 3 — AIMatcher: {elapsed3:.1f}ms')

        # =============================================================
        # Fase 4: Clasificación final
        # =============================================================
        _t4 = time.perf_counter()
        summary = self.analyze(match_results)
        summary.memoria_usada = memoria_usada
        summary.ai_usada = ai_usada
        summary.memory_mapping = memory_mapping

        # Detectar conflictos globales
        summary.conflictos_presentes = any(
            r.conflicts for r in match_results
        )

        # Registrar clasificación final en auditoría
        for cc in summary.columnas:
            if cc.column_index in audit_map:
                entry = audit_map[cc.column_index]
                entry.final_matched_to = cc.matched_to
                entry.final_confidence = cc.confidence
                entry.final_method = cc.method
                entry.final_category = cc.category

        # Calcular campos del formulario que NO están mapeados (para auditoría)
        campos_mapeados_set = {
            cc.matched_to for cc in summary.columnas if cc.matched_to
        }
        for campo in campos_activos:
            if campo.tipo not in (excluded_types or set()):
                if campo.nombre not in campos_mapeados_set:
                    # Buscar si alguna columna del Excel debería mapear esto
                    for entry in audit_map.values():
                        if campo.nombre == entry.final_matched_to:
                            break
                    else:
                        # Este campo del formulario no tiene correspondencia
                        # Registrar en audit (no hay columna, creamos entrada virtual)
                        pass  # No hay columna que lo referencie, es campo sin mapear

        # =============================================================
        # Fase 5: Decisión unificada
        # =============================================================
        summary = self.decidir_accion(
            summary=summary,
            formulario=formulario,
            campos_activos=campos_activos,
            excluded_types=excluded_types,
        )

        elapsed4 = (time.perf_counter() - _t4) * 1000
        elapsed_total = (time.perf_counter() - _t0) * 1000

        # Volcar auditoría al summary
        summary.audit_log = [asdict(e) for e in audit_map.values()]

        logger.info(
            f'[AUTO] Fase 4-5 — Clasificación+Decisión: {elapsed4:.1f}ms | '
            f'Auto: {summary.auto}, Review: {summary.review}, '
            f'Manual: {summary.manual}, Saltar: {summary.puede_saltar_mapeo} | '
            f'Total: {elapsed_total:.1f}ms'
        )

        # Log per-column trace (fase 1→2→3→final)
        logger.info('[AUTO] === TRAZA POR COLUMNA ===')
        for entry in audit_map.values():
            logger.info(
                f'[AUTO]   [{entry.column_index}] \"{entry.column_name}\" | '
                f'F1={entry.phase1_matcher or "—"}({entry.phase1_confidence:.0%}) '
                f'F2_mem={entry.phase2_memory or "—"}({entry.phase2_applied}) '
                f'F3_ai={entry.phase3_ai or "—"}({entry.phase3_applied}) '
                f'→ FINAL={entry.final_matched_to or "—"} '
                f'[{entry.final_category}] ({entry.final_confidence:.0%}) '
                f'conflictos={len(entry.conflicts)}'
            )
        logger.info('[AUTO] === FIN TRAZA ===')

        return summary

    # ==================================================================
    # MÉTODOS LEGACY (compatibilidad hacia atrás)
    # ==================================================================

    def build_mapping_from_summary(
        self,
        summary: MappingSummary,
        user_overrides: Optional[dict[int, str]] = None,
    ) -> dict[int, str]:
        """
        Construye el mapping final combinando asignaciones automáticas
        con sobrescrituras del usuario.
        """
        mapeo: dict[int, str] = {}

        for cc in summary.columnas:
            if user_overrides and cc.column_index in user_overrides:
                mapeo[cc.column_index] = user_overrides[cc.column_index]
            elif cc.matched_to:
                mapeo[cc.column_index] = cc.matched_to

        return mapeo

    def get_fields_sin_mapear(
        self,
        summary: MappingSummary,
        all_field_names: list[str],
        excluded_types: Optional[set[str]] = None,
    ) -> list[str]:
        """
        Retorna los campos del formulario que no tienen
        correspondencia en el mapping.
        """
        campos_mapeados = set()
        for cc in summary.columnas:
            if cc.matched_to:
                campos_mapeados.add(cc.matched_to)

        sin_mapear = [
            fn for fn in all_field_names
            if fn not in campos_mapeados
        ]
        if excluded_types:
            sin_mapear = [
                fn for fn in sin_mapear
                if fn not in excluded_types
            ]
        return sin_mapear
