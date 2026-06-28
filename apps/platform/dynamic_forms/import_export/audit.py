"""Audit logger — detailed record of import decisions and actions."""

from __future__ import annotations

import json
from typing import Any

from apps.platform.dynamic_forms.models import ImportLog, ImportAudit


class AuditLogger:
    """Logs every decision and action during import with full context.

    Supports buffered mode via flush() for batch bulk_create,
    eliminating N+1 audit INSERTs during row processing.
    """

    _buffer: list[ImportAudit] = []

    @classmethod
    def _make(cls, import_log: ImportLog, tipo: str, mensaje: str,
              registro_id: int | None = None, campo_nombre: str = '',
              valor_anterior: str = '', valor_nuevo: str = '',
              metadata: dict | None = None) -> ImportAudit:
        return ImportAudit(
            import_log=import_log,
            tipo=tipo,
            registro_id=registro_id,
            campo_nombre=campo_nombre,
            valor_anterior=valor_anterior,
            valor_nuevo=valor_nuevo,
            mensaje=mensaje,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        )

    @classmethod
    def log(cls, import_log: ImportLog, tipo: str, mensaje: str,
            registro_id: int | None = None, campo_nombre: str = '',
            valor_anterior: str = '', valor_nuevo: str = '',
            metadata: dict | None = None):
        cls._buffer.append(
            cls._make(import_log, tipo, mensaje, registro_id, campo_nombre,
                      valor_anterior, valor_nuevo, metadata)
        )

    @classmethod
    def log_creacion(cls, import_log: ImportLog, registro_id: int, valores: dict[str, str]):
        cls._buffer.append(
            cls._make(
                import_log, 'creacion',
                f'Registro #{registro_id} creado con {len(valores)} valores',
                registro_id=registro_id,
                metadata=valores,
            )
        )

    @classmethod
    def log_actualizacion(cls, import_log: ImportLog, registro_id: int,
                          cambios: dict[str, tuple[str, str]]):
        for campo, (anterior, nuevo) in cambios.items():
            cls._buffer.append(
                cls._make(
                    import_log, 'actualizacion',
                    f'Campo "{campo}" actualizado: "{anterior}" → "{nuevo}"',
                    registro_id=registro_id, campo_nombre=campo,
                    valor_anterior=anterior, valor_nuevo=nuevo,
                )
            )

    @classmethod
    def log_error(cls, import_log: ImportLog, mensaje: str,
                  fila: int | None = None, metadata: dict | None = None):
        cls._buffer.append(
            cls._make(
                import_log, 'error', mensaje,
                metadata={'fila': fila, **(metadata or {})},
            )
        )

    @classmethod
    def log_decision(cls, import_log: ImportLog, mensaje: str, metadata: dict | None = None):
        cls._buffer.append(
            cls._make(import_log, 'decision', mensaje, metadata=metadata)
        )

    @classmethod
    def flush(cls):
        """Escribe todos los eventos bufferizados a la BD en un solo bulk_create."""
        if cls._buffer:
            ImportAudit.objects.bulk_create(cls._buffer)
            cls._buffer.clear()

    @staticmethod
    def get_resumen(import_log: ImportLog) -> list[dict]:
        return list(
            ImportAudit.objects.filter(import_log=import_log)
            .values('tipo', 'mensaje', 'campo_nombre', 'created_at')
            .order_by('created_at')
        )
