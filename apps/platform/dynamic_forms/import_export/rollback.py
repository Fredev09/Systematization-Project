"""Rollback manager for reverting imports."""

from __future__ import annotations

import json
import logging
from typing import Any

from django.db import transaction

from apps.platform.dynamic_forms.models import ImportLog, ImportSnapshot, ImportAudit, Registro

logger = logging.getLogger(__name__)


class RollbackError(Exception):
    pass


class RollbackManager:
    """Manages import rollback: takes snapshots before writes, reverts on demand."""

    def take_snapshot(self, import_log: ImportLog, registros: list[Registro], valores_map: dict[int, dict[str, str]]):
        for reg in registros:
            vals = valores_map.get(reg.id, {})
            ImportSnapshot.objects.update_or_create(
                import_log=import_log,
                registro=reg,
                defaults={'valores_anteriores': json.dumps(vals)},
            )

    def revert(self, import_log_id: int) -> dict:
        try:
            import_log = ImportLog.objects.get(id=import_log_id)
        except ImportLog.DoesNotExist:
            raise RollbackError(f'ImportLog #{import_log_id} no encontrado')

        if import_log.estado == 'revertido':
            return {'status': 'already_reverted', 'message': 'Esta importación ya fue revertida'}

        snapshots = list(import_log.snapshots.select_related('registro').all())
        if not snapshots:
            raise RollbackError(f'No hay snapshots para la importación #{import_log_id}')

        reverted_count = 0
        errors: list[str] = []

        from apps.platform.dynamic_forms.services_dynamic import DynamicService as DS

        if import_log.modo == 'crear':
            with transaction.atomic():
                for snap in snapshots:
                    try:
                        snap.registro.delete()
                        reverted_count += 1
                        ImportAudit.objects.create(
                            import_log=import_log,
                            tipo='rollback',
                            registro_id=snap.registro_id,
                            mensaje='Registro eliminado (rollback de creación)',
                        )
                    except Exception as e:
                        errors.append(f'Error eliminando registro {snap.registro_id}: {e}')
                        logger.exception(f'Rollback delete error snapshot #{snap.id}')

        else:
            with transaction.atomic():
                for snap in snapshots:
                    try:
                        reg = snap.registro
                        valores_anteriores = json.loads(snap.valores_anteriores)
                        nuevos_valores = {}
                        for campo_nombre, valor in valores_anteriores.items():
                            nuevos_valores[campo_nombre] = valor

                        reg2 = DS.actualizar(reg, nuevos_valores)
                        if reg2:
                            reverted_count += 1

                        ImportAudit.objects.create(
                            import_log=import_log,
                            tipo='rollback',
                            registro_id=reg.id,
                            mensaje=f'Valores revertidos al snapshot de importación',
                            metadata_json=json.dumps({'campos_restaurados': len(valores_anteriores)}),
                        )
                    except Exception as e:
                        errors.append(f'Error revirtiendo snapshot #{snap.id}: {e}')
                        logger.exception(f'Rollback error for snapshot {snap.id}')

        import_log.estado = 'revertido'
        import_log.save(update_fields=['estado'])

        return {
            'status': 'reverted',
            'import_log_id': import_log_id,
            'total_snapshots': len(snapshots),
            'reverted_count': reverted_count,
            'errors': errors,
        }
