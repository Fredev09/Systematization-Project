"""
mapping_memory.py — Memoria persistente de mapeos de columnas.

Almacena y recupera mapeos exitosos anteriores para reutilizarlos
en futuras importaciones del mismo formulario con el mismo patrón
de encabezados.

Cada entrada se identifica por (formulario_id, headers_hash) donde
headers_hash es un SHA256 de los nombres de columna normalizados.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from .column_matching import normalizar_columna

logger = logging.getLogger(__name__)


def _headers_hash(headers: list[str]) -> str:
    """Genera un hash SHA256 de los encabezados normalizados."""
    normalized = [normalizar_columna(h) for h in headers if h]
    key = '|'.join(normalized)
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def _compute_confidence_avg(mapping_json: dict) -> float:
    """Calcula la confianza promedio de un mapeo almacenado (placeholder)."""
    return 0.95  # Los mapeos guardados son mapeos confirmados por el usuario


class MappingMemoryManager:
    """
    Gestiona la memoria persistente de mapeos.

    Lee del modelo MappingMemory, aplica mapeos previos y
    guarda mapeos confirmados para reutilización futura.
    """

    @staticmethod
    def load(
        formulario_id: int,
        encabezados: list[str],
    ) -> Optional[dict[int, str]]:
        """
        Carga un mapeo previo para este formulario+encabezados.

        Args:
            formulario_id: ID del formulario destino.
            encabezados: Lista de nombres de columna del Excel.

        Returns:
            Dict {col_idx: campo_nombre} si existe, None si no.
        """
        from .models import MappingMemory

        h = _headers_hash(encabezados)
        try:
            memory = MappingMemory.objects.get(
                formulario_id=formulario_id,
                headers_hash=h,
            )
            mapping = json.loads(memory.mapping_json)
            logger.info(
                f'MappingMemory: encontrado para form_id={formulario_id}, '
                f'hash={h[:12]}, usado {memory.times_used} veces'
            )
            # Actualizar contador de uso
            MappingMemory.objects.filter(id=memory.id).update(
                times_used=models.F('times_used') + 1,
            )
            return {int(k): v for k, v in mapping.items()}
        except MappingMemory.DoesNotExist:
            logger.info(
                f'MappingMemory: no encontrado para form_id={formulario_id}, '
                f'hash={h[:12]}'
            )
            return None
        except Exception as e:
            logger.warning(f'MappingMemory: error cargando: {e}')
            return None

    @staticmethod
    def save(
        formulario_id: int,
        encabezados: list[str],
        mapping: dict[int, str],
        confidence_avg: float = 0.95,
    ) -> bool:
        """
        Guarda o actualiza un mapeo en la memoria persistente.

        Args:
            formulario_id: ID del formulario destino.
            encabezados: Lista de nombres de columna del Excel.
            mapping: Dict {col_idx: campo_nombre}.
            confidence_avg: Confianza promedio del mapeo.

        Returns:
            True si se guardó correctamente.
        """
        from .models import MappingMemory

        h = _headers_hash(encabezados)
        mapping_json = json.dumps(mapping, ensure_ascii=False)
        headers_text = json.dumps(encabezados, ensure_ascii=False)

        try:
            obj, created = MappingMemory.objects.update_or_create(
                formulario_id=formulario_id,
                headers_hash=h,
                defaults={
                    'headers_text': headers_text,
                    'mapping_json': mapping_json,
                    'confidence_avg': confidence_avg,
                },
            )
            if created:
                logger.info(
                    f'MappingMemory: creado para form_id={formulario_id}, '
                    f'hash={h[:12]}'
                )
            else:
                logger.info(
                    f'MappingMemory: actualizado para form_id={formulario_id}, '
                    f'hash={h[:12]}'
                )
            return True
        except Exception as e:
            logger.warning(f'MappingMemory: error guardando: {e}')
            return False

    @staticmethod
    def apply_memory_to_results(
        memory_mapping: dict[int, str],
        match_results: list,
        encabezados: list[str],
    ) -> list:
        """
        Aplica un mapeo memorizado a los resultados de ColumnMatcher,
        pero solo si el resultado actual no tiene un match mejor.

        Args:
            memory_mapping: Dict {col_idx: campo_nombre} del mapeo previo.
            match_results: Lista de ColumnMatchResult.
            encabezados: Lista de nombres de columna.

        Returns:
            Lista de ColumnMatchResult actualizada.
        """
        for r in match_results:
            if r.column_index in memory_mapping:
                campo_memorizado = memory_mapping[r.column_index]
                # Solo aplicar si el match actual es peor (none o fuzzy bajo)
                if (not r.matched_to or r.confidence < 0.70):
                    r.matched_to = campo_memorizado
                    r.method = 'memory'
                    r.confidence = 0.92
                    r.explanation = (
                        f'Coincidencia por memoria de importación previa: '
                        f'"{r.column_name}" → "{campo_memorizado}".'
                    )
        return match_results

    @staticmethod
    def forget(formulario_id: int, encabezados: list[str]) -> bool:
        """
        Elimina un mapeo memorizado (útil si el usuario corrige).

        Args:
            formulario_id: ID del formulario.
            encabezados: Lista de encabezados.

        Returns:
            True si existía y fue eliminado.
        """
        from .models import MappingMemory

        h = _headers_hash(encabezados)
        deleted, _ = MappingMemory.objects.filter(
            formulario_id=formulario_id,
            headers_hash=h,
        ).delete()
        if deleted:
            logger.info(f'MappingMemory: eliminado para hash={h[:12]}')
        return deleted > 0


# To avoid circular imports in the manager's load/save methods
from django.db import models as models
