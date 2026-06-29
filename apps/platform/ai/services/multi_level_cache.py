"""
multi_level_cache.py — Multi-Level Cache (FASE 4, v4.0 FREE-FIRST).

Extiende el DiskCache existente con múltiples niveles:

  Niveles de caché:
    - document: SHA del documento completo
    - image: SHA de la imagen (base64)
    - ocr: SHA del texto OCR extraído
    - prompt: SHA del prompt exacto
    - response: SHA de la respuesta AI
    - form: SHA de la propuesta de formulario
    - columns: SHA del conjunto de columnas

Cada nivel tiene TTL configurable independientemente.
FREE-FIRST: Maximiza reutilización de caché para evitar llamadas AI.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import re
import time

from django.conf import settings

from apps.platform.ai.cache import DiskCache, get_cache
from apps.platform.ai.utils import compute_content_hash, compute_file_hash

logger = logging.getLogger(__name__)


# ======================================================================
# Configuración de TTL por nivel (en segundos)
# ======================================================================

_DEFAULT_TTLS: dict[str, int] = {
    "document": 86400 * 7,    # 7 días (documentos no cambian)
    "image": 86400 * 30,      # 30 días (imágenes rara vez cambian)
    "ocr": 86400 * 7,         # 7 días (OCR del mismo doc = mismo resultado)
    "prompt": 86400,           # 1 día (prompts pueden variar)
    "response": 86400 * 3,    # 3 días (respuestas AI reutilizables)
    "form": 86400 * 7,        # 7 días (propuestas de formulario)
    "columns": 86400 * 30,    # 30 días (columnas no cambian frecuentemente)
    "analysis": 86400,         # 1 día (análisis completos)
}


@dataclass
class CacheEntry:
    """Entrada en el multi-level cache."""
    level: str
    key: str
    data: Any
    created_at: float
    ttl: int
    hits: int = 0

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl


class MultiLevelCache:
    """
    Cache multinivel con TTL configurable por nivel.

    Cada nivel corresponde a un tipo de dato diferente:
      - document: Resultado de análisis de documento completo
      - image: OCR / análisis de imagen
      - ocr: Texto extraído vía OCR
      - prompt: Prompt generado para AI
      - response: Respuesta de AI
      - form: Propuesta de formulario generada
      - columns: Detección de columnas / encabezados
      - analysis: Análisis completo (todo el pipeline)

    Usage:
        mlc = MultiLevelCache()
        
        # Guardar en caché
        mlc.set("document", doc_hash, {"fields": [...], "confidence": 0.9})
        
        # Recuperar
        result = mlc.get("document", doc_hash)
        if result:
            print(result.data)
        
        # Verificar si un nivel tiene caché
        if mlc.exists("ocr", image_hash):
            print("OCR ya cacheado, saltar llamada AI")
    """

    def __init__(self):
        self._disk_cache: DiskCache = get_cache()
        self._ttls: dict[str, int] = {}
        self._load_ttls()
        self._stats: dict[str, dict[str, int]] = {
            "hits": {},
            "misses": {},
        }

    def _load_ttls(self) -> None:
        """Carga TTLs desde settings con defaults FREE-FIRST."""
        for level, default in _DEFAULT_TTLS.items():
            self._ttls[level] = getattr(
                settings, f"AI_CACHE_TTL_{level.upper()}", default
            )

    def _level_key(self, level: str, content_hash: str) -> str:
        """Construye clave única: level::hash."""
        return f"{level}::{content_hash}"

    # ── API Principal ──

    def get(self, level: str, content_hash: str) -> Optional[CacheEntry]:
        """
        Recupera una entrada de caché por nivel y hash.

        Args:
            level: Nivel de caché (document, image, ocr, etc.).
            content_hash: SHA256 del contenido.

        Returns:
            CacheEntry si existe y no ha expirado, None en otro caso.
        """
        key = self._level_key(level, content_hash)
        raw = self._disk_cache.get(key)
        
        if raw is None:
            self._stats.setdefault("misses", {})
            self._stats["misses"][level] = self._stats["misses"].get(level, 0) + 1
            return None

        # Validar expiración
        entry = CacheEntry(
            level=level,
            key=key,
            data=raw.get("data"),
            created_at=raw.get("created_at", 0),
            ttl=self._ttls.get(level, 86400),
            hits=raw.get("hits", 0) + 1,
        )

        if entry.is_expired:
            self._disk_cache._path(key).unlink(missing_ok=True)
            self._stats.setdefault("misses", {})
            self._stats["misses"][level] = self._stats["misses"].get(level, 0) + 1
            return None

        # Actualizar contador de hits
        self._update_hits(key, entry.hits)

        self._stats.setdefault("hits", {})
        self._stats["hits"][level] = self._stats["hits"].get(level, 0) + 1
        return entry

    def set(
        self,
        level: str,
        content_hash: str,
        data: Any,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Guarda una entrada en caché.

        Args:
            level: Nivel de caché.
            content_hash: SHA256 del contenido.
            data: Datos a cachear.
            metadata: Metadatos adicionales (proveedor, modelo, etc).

        Returns:
            Key de la entrada guardada.
        """
        key = self._level_key(level, content_hash)
        ttl = self._ttls.get(level, 86400)

        entry_data = {
            "data": data,
            "created_at": time.time(),
            "ttl": ttl,
            "hits": 0,
            "metadata": metadata or {},
        }

        self._disk_cache.set(
            key=key,
            data=entry_data,
            provider=(metadata or {}).get("provider", ""),
            model=(metadata or {}).get("model", ""),
        )
        return key

    def exists(self, level: str, content_hash: str) -> bool:
        """Verifica si existe una entrada en caché sin recuperarla."""
        return self.get(level, content_hash) is not None

    def delete(self, level: str, content_hash: str) -> bool:
        """Elimina una entrada de caché."""
        key = self._level_key(level, content_hash)
        path = self._disk_cache._path(key)
        try:
            if path.exists():
                path.unlink(missing_ok=True)
                return True
        except OSError as e:
            logger.warning("Cache delete failed for %s: %s", key, e)
        return False

    def clear_level(self, level: str) -> int:
        """Elimina TODAS las entradas de un nivel."""
        safe_level = re.escape(level)
        count = 0
        for path in self._disk_cache.cache_dir.glob(f"{safe_level}::*.json"):
            path.unlink(missing_ok=True)
            count += 1
        if count:
            logger.info("MultiLevelCache: cleared level '%s' (%d entries)", level, count)
        return count

    def clear_all(self) -> int:
        """Elimina TODAS las entradas de TODOS los niveles."""
        total = 0
        for level in self._ttls:
            total += self.clear_level(level)
        return total

    # ── Hash Builders ──

    def hash_content(self, content: str) -> str:
        """SHA256 de contenido de texto."""
        return compute_content_hash(content)

    def hash_file(self, file_path: str | Path) -> str:
        """SHA256 de un archivo completo."""
        try:
            return compute_file_hash(file_path)
        except (FileNotFoundError, IsADirectoryError, OSError) as e:
            logger.warning("hash_file failed for %s: %s", file_path, e)
            return ""

    def hash_dict(self, data: dict) -> str:
        """SHA256 de un diccionario JSON."""
        try:
            return compute_content_hash(json.dumps(data, sort_keys=True, ensure_ascii=False))
        except (TypeError, ValueError) as e:
            logger.warning("hash_dict failed: %s", e)
            return ""

    def hash_headers(self, headers: list[str]) -> str:
        """SHA256 de un conjunto de encabezados (para cache de columnas)."""
        return compute_content_hash("|".join(sorted(h.lower() for h in headers)))

    # ── Estadísticas ──

    def get_stats(self) -> dict[str, Any]:
        """Obtiene estadísticas de cache para el dashboard."""
        total_hits = sum(self._stats.get("hits", {}).values())
        total_misses = sum(self._stats.get("misses", {}).values())
        total = total_hits + total_misses

        return {
            "total_hits": total_hits,
            "total_misses": total_misses,
            "hit_rate": round(total_hits / total * 100, 1) if total else 0.0,
            "by_level": {
                level: {
                    "hits": self._stats.get("hits", {}).get(level, 0),
                    "misses": self._stats.get("misses", {}).get(level, 0),
                    "ttl_seconds": self._ttls.get(level, 86400),
                }
                for level in self._ttls
            },
        }

    def _update_hits(self, key: str, hits: int) -> None:
        """Actualiza el contador de hits en memoria (no escribe a disco en cada hit)."""
        # Los hits se mantienen en memoria en self._stats — no escribimos a disco
        # porque el I/O de escribir en cada hit es costoso.
        # Los hits totales se calculan desde _stats, no desde el archivo.
        pass


# Singleton
_default_mlc: Optional[MultiLevelCache] = None


def get_multi_level_cache() -> MultiLevelCache:
    global _default_mlc
    if _default_mlc is None:
        _default_mlc = MultiLevelCache()
    return _default_mlc
