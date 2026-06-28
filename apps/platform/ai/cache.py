"""
cache.py — SHA256-based caching for AI responses.

If the exact same document/content has been analyzed before,
return the cached result instead of calling the AI provider again.

Cache key = SHA256(prompt_hash + content_hash + provider + model)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# Default cache TTL: 24 hours
CACHE_TTL_SECONDS = 86400


def _compute_hash(*args: str) -> str:
    """Compute SHA256 hash of concatenated arguments."""
    raw = "|".join(str(a) for a in args if a)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DiskCache:
    """
    Simple disk-based cache for AI responses.

    Each entry is stored as:
      CACHE_DIR/<hash>.json

    The JSON file contains:
      - key: SHA256 hash
      - data: the cached result
      - created_at: timestamp
      - provider: source provider
      - model: source model
    """

    def __init__(self, cache_dir: Optional[str] = None, ttl: int = CACHE_TTL_SECONDS):
        self.cache_dir = Path(cache_dir or getattr(
            settings, "AI_CACHE_DIR",
            Path(settings.BASE_DIR) / ".ai_cache"
        ))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(self, key: str) -> Optional[dict[str, Any]]:
        """Retrieve a cached entry. Returns None if missing or expired."""
        path = self._path(key)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                entry = json.load(f)
            age = time.time() - entry.get("created_at", 0)
            if age > self.ttl:
                path.unlink(missing_ok=True)
                logger.info(f"Cache expired for key={key[:12]} (age={age:.0f}s)")
                return None
            logger.info(f"Cache HIT for key={key[:12]} (age={age:.0f}s)")
            return entry.get("data")
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.warning(f"Cache read error for key={key[:12]}: {e}")
            path.unlink(missing_ok=True)
            return None

    def set(
        self,
        key: str,
        data: Any,
        provider: str = "",
        model: str = "",
    ) -> str:
        """Store an entry in the cache. Returns the key."""
        entry = {
            "key": key,
            "data": data,
            "created_at": time.time(),
            "provider": provider,
            "model": model,
        }
        path = self._path(key)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False, indent=2)
            logger.info(f"Cache SET for key={key[:12]}")
        except OSError as e:
            logger.warning(f"Cache write error for key={key[:12]}: {e}")
        return key

    def build_key(
        self,
        prompt_text: str,
        content_hash: str,
        provider: str = "",
        model: str = "",
    ) -> str:
        """Build a deterministic cache key from inputs."""
        return _compute_hash(prompt_text, content_hash, provider, model)

    def clear_expired(self) -> int:
        """Remove all expired entries. Returns count of removed files."""
        now = time.time()
        removed = 0
        for path in self.cache_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    entry = json.load(f)
                age = now - entry.get("created_at", 0)
                if age > self.ttl:
                    path.unlink(missing_ok=True)
                    removed += 1
            except (json.JSONDecodeError, OSError):
                path.unlink(missing_ok=True)
                removed += 1
        if removed:
            logger.info(f"Cache cleanup: removed {removed} expired entries")
        return removed

    def clear_all(self) -> int:
        """Remove ALL cache entries. Returns count of removed files."""
        count = 0
        for path in self.cache_dir.glob("*.json"):
            path.unlink(missing_ok=True)
            count += 1
        logger.info(f"Cache cleared: {count} entries removed")
        return count


# Singleton pattern
_default_cache: Optional[DiskCache] = None


def get_cache() -> DiskCache:
    """Return the default cache instance (singleton)."""
    global _default_cache
    if _default_cache is None:
        _default_cache = DiskCache()
    return _default_cache
