"""ImportPipeline — orchestrates the full import workflow."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from django.db import transaction

from apps.platform.dynamic_forms.models import Formulario, ImportLog, ImportAudit
from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS
from apps.platform.dynamic_forms.column_matching import ColumnMatcher

from .formats import ExcelParser, ParseResult
from .detector import DataDetector
from .quality import QualityAnalyzer
from .conflict import ConflictDetector
from .rollback import RollbackManager
from .audit import AuditLogger

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    formulario_id: int
    filepath: str
    filename: str
    modo: str = 'crear'
    usuario_id: int | None = None
    mapping_override: dict[str, str] | None = None
    sheet_name: str | None = None
    header_row: int | None = None
    skip_audit: bool = False
    callback: Callable | None = None


@dataclass
class PipelineResult:
    success: bool
    import_log_id: int | None = None
    total_filas: int = 0
    creados: int = 0
    actualizados: int = 0
    ignorados: int = 0
    errores: int = 0
    tiempo_seg: float = 0.0
    resumen: str = ''
    quality: dict | None = None
    conflicts: dict | None = None
    errors_detail: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    resultado_detalle: list[dict] = field(default_factory=list)


class ImportPipeline:
    """Full pipeline: detect → parse → match → analyze → validate → import → audit."""

    def __init__(self):
        self.detector = DataDetector()
        self.quality = QualityAnalyzer()
        self.conflict = ConflictDetector()
        self.matcher = ColumnMatcher()
        self.rollback = RollbackManager()
        self.audit = AuditLogger()

    def run(self, config: PipelineConfig) -> PipelineResult:
        t0 = time.time()
        result = PipelineResult()

        try:
            formulario = Formulario.objects.get(id=config.formulario_id)
        except Formulario.DoesNotExist:
            return PipelineResult(success=False, resumen=f'Formulario #{config.formulario_id} no encontrado')

        file_hash = self._file_hash(config.filepath)

        parser = ExcelParser(config.filepath, filename=config.filename)
        field_names = list(formulario.campos.filter(activo=True).values_list('nombre', flat=True))

        parse_result = parser.parse(
            sheet_name=config.sheet_name,
            header_row=config.header_row,
            field_names=field_names,
        )

        if config.mapping_override:
            mapping = config.mapping_override
        else:
            match_results = self.matcher.match_all(parse_result.headers, field_names)
            mapping = self.matcher.build_mapping(parse_result.headers, field_names, match_results)

        quality_report = self.quality.analyze(parse_result.headers, parse_result.rows, match_results if not config.mapping_override else None)
        conflict_result = self.conflict.detect(parse_result.headers, field_names, match_results if not config.mapping_override else None)

        import_log = ImportLog.objects.create(
            formulario=formulario,
            usuario_id=config.usuario_id,
            archivo_nombre=config.filename,
            archivo_tamano=os.path.getsize(config.filepath) if os.path.exists(config.filepath) else 0,
            archivo_hash=file_hash,
            modo=config.modo,
            total_filas=len(parse_result.rows),
            hoja_detectada=parse_result.sheet_name,
            confianza_global=quality_report.score,
            calidad_estrellas=quality_report.stars,
            estado='completado',
        )
        result.import_log_id = import_log.id

        with transaction.atomic():
            hook_original = formulario.hook_post_crear if config.modo in ('crear', 'upsert') else None
            if hook_original and DS._hook_local.activo:
                formulario.hook_post_crear = None
                formulario.save(update_fields=['hook_post_crear'])

            try:
                creados, actualizados, ignorados, errores_list = self._process_rows(
                    formulario=formulario,
                    rows=parse_result.rows,
                    mapping=mapping,
                    modo=config.modo,
                    import_log=import_log,
                )

                import_log.creados = creados
                import_log.actualizados = actualizados
                import_log.ignorados = ignorados
                import_log.errores = len(errores_list)

                result.creados = creados
                result.actualizados = actualizados
                result.ignorados = ignorados
                result.errores = len(errores_list)
                result.total_filas = len(parse_result.rows)
                result.errors_detail = errores_list

                if errores_list:
                    import_log.estado = 'parcial' if creados > 0 else 'completado'

                warnings = quality_report.warnings + conflict_result.warnings
                result.warnings = warnings[:20]

                if config.modo == 'validar':
                    import_log.estado = 'completado'

            finally:
                if hook_original:
                    formulario.hook_post_crear = hook_original
                    formulario.save(update_fields=['hook_post_crear'])

        t1 = time.time()
        import_log.tiempo_seg = round(t1 - t0, 2)
        result.tiempo_seg = import_log.tiempo_seg

        resumen = self._build_resumen(creados, actualizados, ignorados, errores_list)
        import_log.resumen = resumen
        import_log.resultado_json = self._build_resultado_json(
            quality_report, conflict_result, errores_list, warnings
        )
        import_log.save(update_fields=[
            'creados', 'actualizados', 'ignorados', 'errores',
            'tiempo_seg', 'resumen', 'resultado_json', 'estado',
        ])

        self._finalize_result(result, resumen, quality_report, conflict_result)

        if config.callback:
            try:
                config.callback(result)
            except Exception as e:
                logger.exception(f'Pipeline callback error: {e}')

        return result

    def _build_resumen(
        self, creados: int, actualizados: int, ignorados: int, errores_list: list
    ) -> str:
        """Construye el resumen textual de la importación."""
        resumen_parts = []
        if creados:
            resumen_parts.append(f'{creados} creados')
        if actualizados:
            resumen_parts.append(f'{actualizados} actualizados')
        if ignorados:
            resumen_parts.append(f'{ignorados} ignorados')
        if errores_list:
            resumen_parts.append(f'{len(errores_list)} errores')
        return ', '.join(resumen_parts) or 'Sin cambios'

    def _build_resultado_json(
        self, quality_report, conflict_result, errores_list, warnings
    ) -> str:
        """Construye el JSON de resultado para ImportLog."""
        return json.dumps({
            'quality': quality_report.to_dict(),
            'conflicts': {
                'has_conflicts': conflict_result.has_conflicts,
                'count': len(conflict_result.conflicts),
            },
            'errors_detail': errores_list[:50],
            'warnings': warnings[:20],
        }, ensure_ascii=False)

    def _finalize_result(self, result, resumen, quality_report, conflict_result):
        """Establece los campos finales de PipelineResult."""
        result.resumen = resumen
        result.quality = quality_report.to_dict()
        result.conflicts = {
            'has_conflicts': conflict_result.has_conflicts,
            'conflicts': [c['message'] for c in conflict_result.conflicts[:10]],
        }
        result.success = True

    def _file_hash(self, filepath: str) -> str:
        try:
            sha = hashlib.sha256()
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(65536), b''):
                    sha.update(chunk)
            return sha.hexdigest()
        except Exception:
            return ''

    def _build_valores_dict(
        self, row: list[Any], mapping: dict[str, str]
    ) -> dict[str, str]:
        """Convierte una fila del Excel a un dict campo→valor según el mapping."""
        valores: dict[str, str] = {}
        for col_idx, header in enumerate(mapping):
            if col_idx < len(row):
                field_name = mapping[header]
                if field_name and row[col_idx]:
                    valores[field_name] = str(row[col_idx]).strip()
        return valores

    def _process_crear_row(
        self, formulario, valores: dict, import_log: ImportLog, row_idx: int
    ) -> dict:
        """Procesa una fila en modo 'crear'."""
        reg = DS.crear(formulario, valores, usuario_id=import_log.usuario_id)
        if reg:
            AuditLogger.log_creacion(import_log, reg.id, valores)
            return {'result': 'creado', 'id': reg.id, 'campos': list(valores.keys())}
        return {'result': 'error', 'error': 'No se pudo crear el registro'}

    def _process_actualizar_row(
        self, formulario, valores: dict, import_log: ImportLog, row_idx: int, id_field
    ) -> dict:
        """Procesa una fila en modo 'actualizar'."""
        id_value = valores.pop(id_field.nombre, None)
        if not id_value:
            AuditLogger.log(import_log, 'ignorado', f'Fila {row_idx + 1}: sin identificador principal')
            return {'result': 'ignorado'}

        existing = DS.buscar_por_identificador(formulario, id_value)
        if not existing:
            AuditLogger.log(import_log, 'ignorado', f'Fila {row_idx + 1}: "{id_value}" no encontrado')
            return {'result': 'ignorado'}

        anteriores = DS.obtener_valores(existing)
        reg = DS.actualizar(existing, valores, usuario_id=import_log.usuario_id)
        if reg:
            cambios = {}
            for k, v in valores.items():
                if anteriores.get(k) != v:
                    cambios[k] = (anteriores.get(k, ''), v)
            if cambios:
                AuditLogger.log_actualizacion(import_log, reg.id, cambios)
            return {'result': 'actualizado', 'id': reg.id}
        return {'result': 'ignorado'}

    def _process_upsert_row(
        self, formulario, valores: dict, import_log: ImportLog, row_idx: int, id_field
    ) -> dict:
        """Procesa una fila en modo 'upsert'."""
        reg, fue_creado = DS.upsert_por_identificador(
            formulario, valores, usuario_id=import_log.usuario_id
        )
        if reg:
            if fue_creado:
                AuditLogger.log_creacion(import_log, reg.id, valores)
                return {'result': 'creado', 'id': reg.id}
            else:
                AuditLogger.log(import_log, 'actualizacion', f'Registro #{reg.id} actualizado vía upsert')
                return {'result': 'actualizado', 'id': reg.id}
        return {'result': 'error', 'error': 'Upsert falló'}

    def _process_validar_row(
        self, formulario, valores: dict, import_log: ImportLog, row_idx: int
    ) -> dict:
        """Procesa una fila en modo 'validar' (dry-run)."""
        from apps.platform.dynamic_forms.validators import validar_campos
        val_result = validar_campos(formulario, valores)
        if val_result:
            return {'result': 'valid'}
        return {'result': 'error', 'error': 'Validación fallida'}

    def _process_rows(
        self,
        formulario: Formulario,
        rows: list[list[Any]],
        mapping: dict[str, str],
        modo: str,
        import_log: ImportLog,
    ) -> tuple[int, int, int, list[dict]]:
        creados = 0
        actualizados = 0
        ignorados = 0
        errores: list[dict] = []

        id_field = DS.obtener_identificador_principal(formulario)

        for row_idx, row in enumerate(rows):
            valores = self._build_valores_dict(row, mapping)

            if not valores:
                ignorados += 1
                AuditLogger.log(
                    import_log, 'ignorado',
                    f'Fila {row_idx + 1}: sin datos válidos',
                    metadata={'fila': row_idx + 1},
                )
                continue

            try:
                if modo == 'crear':
                    r = self._process_crear_row(formulario, valores, import_log, row_idx)
                elif modo == 'actualizar' and id_field:
                    r = self._process_actualizar_row(formulario, valores, import_log, row_idx, id_field)
                elif modo == 'upsert' and id_field:
                    r = self._process_upsert_row(formulario, valores, import_log, row_idx, id_field)
                elif modo == 'validar':
                    r = self._process_validar_row(formulario, valores, import_log, row_idx)
                else:
                    r = {'result': 'error', 'error': f'Modo no soportado: {modo}'}

                if r['result'] == 'creado':
                    creados += 1
                elif r['result'] == 'actualizado':
                    actualizados += 1
                elif r['result'] == 'ignorado':
                    ignorados += 1
                elif r['result'] == 'error':
                    errores.append({
                        'fila': row_idx + 2,
                        'mensaje': r.get('error', 'Error desconocido'),
                        'valores': valores,
                    })

            except Exception as e:
                err_msg = str(e)[:200]
                errores.append({
                    'fila': row_idx + 2,
                    'mensaje': err_msg,
                    'valores': valores,
                })
                AuditLogger.log_error(
                    import_log, err_msg,
                    fila=row_idx + 2,
                    metadata={'valores': valores},
                )
                logger.warning(f'Error fila {row_idx + 2}: {err_msg}')

        AuditLogger.flush()
        return creados, actualizados, ignorados, errores
