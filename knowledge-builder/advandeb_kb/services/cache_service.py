"""
CacheService — LRU in-memory cache with optional Redis backend.

Used by HybridRetrievalService to avoid redundant embedding + search calls
for identical queries within a short TTL window.

Cache key = SHA-256 of (query, top_k, domain_filter) → JSON-serialised results.

Usage:
    cache = CacheService(max_size=512, ttl_seconds=300)
    hit = cache.get("my query", top_k=10)
    if hit is None:
        results = await retrieval_svc.retrieve(...)
        cache.set("my query", top_k=10, value=results)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-process LRU cache
# ---------------------------------------------------------------------------

class _LRUStore:
    """Thread-safe LRU dict with per-entry TTL."""

    def __init__(self, max_size: int, ttl: float):
        self._max = max_size
        self._ttl = ttl
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, val = entry
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        # Move to end (most recently used)
        self._store.move_to_end(key)
        return val

    def set(self, key: str, value: Any) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (time.monotonic(), value)
        if len(self._store) > self._max:
            oldest = next(iter(self._store))
            del self._store[oldest]

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

    def stats(self) -> dict:
        now = time.monotonic()
        alive = sum(1 for ts, _ in self._store.values() if now - ts <= self._ttl)
        return {"size": len(self._store), "alive": alive, "max": self._max, "ttl": self._ttl}


# ---------------------------------------------------------------------------
# CacheService
# ---------------------------------------------------------------------------

class CacheService:
    """
    Query result cache with LRU eviction and optional Redis backend.

    Args:
        max_size:    Maximum number of cached entries (LRU eviction).
        ttl_seconds: Time-to-live for each entry.
        redis_url:   If set, use Redis as the backend instead of in-process.
        namespace:   Key prefix for Redis (avoids collisions with other apps).
    """

    def __init__(
        self,
        max_size: int = 512,
        ttl_seconds: int = 300,
        redis_url: Optional[str] = None,
        namespace: str = "advandeb_cache",
    ):
        self._ttl = ttl_seconds
        self._namespace = namespace
        self._hits = 0
        self._misses = 0

        if redis_url:
            self._backend = "redis"
            self._redis_url = redis_url
            self._redis = None  # lazy connect
        else:
            self._backend = "lru"
            self._lru = _LRUStore(max_size=max_size, ttl=float(ttl_seconds))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(
        self,
        query: str,
        top_k: int = 10,
        domain_filter: Optional[str] = None,
    ) -> Optional[Any]:
        """Return cached result or None on miss."""
        key = self._make_key(query, top_k, domain_filter)
        val = self._backend_get(key)
        if val is None:
            self._misses += 1
            return None
        self._hits += 1
        logger.debug("Cache HIT  key=%s", key[:16])
        return val

    def set(
        self,
        query: str,
        top_k: int = 10,
        domain_filter: Optional[str] = None,
        value: Any = None,
    ) -> None:
        """Store a retrieval result."""
        key = self._make_key(query, top_k, domain_filter)
        self._backend_set(key, value)
        logger.debug("Cache SET  key=%s", key[:16])

    def invalidate(self, query: str, top_k: int = 10, domain_filter: Optional[str] = None) -> None:
        key = self._make_key(query, top_k, domain_filter)
        self._backend_delete(key)

    def clear(self) -> None:
        if self._backend == "lru":
            self._lru.clear()
        else:
            self._redis_flush_namespace()
        self._hits = self._misses = 0

    def stats(self) -> dict:
        total = self._hits + self._misses
        hit_rate = self._hits / total if total else 0.0
        base = {
            "backend": self._backend,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 3),
            "ttl_seconds": self._ttl,
        }
        if self._backend == "lru":
            base.update(self._lru.stats())
        return base

    # ------------------------------------------------------------------
    # Key generation
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(query: str, top_k: int, domain_filter: Optional[str]) -> str:
        raw = json.dumps(
            {"q": query.strip().lower(), "k": top_k, "d": domain_filter or ""},
            sort_keys=True,
        ).encode()
        return hashlib.sha256(raw).hexdigest()

    # ------------------------------------------------------------------
    # Backend dispatch
    # ------------------------------------------------------------------

    def _backend_get(self, key: str) -> Optional[Any]:
        if self._backend == "lru":
            return self._lru.get(key)
        # Redis backend
        r = self._get_redis()
        raw = r.get(f"{self._namespace}:{key}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def _backend_set(self, key: str, value: Any) -> None:
        if self._backend == "lru":
            self._lru.set(key, value)
            return
        r = self._get_redis()
        try:
            r.setex(f"{self._namespace}:{key}", self._ttl, json.dumps(value))
        except Exception as exc:
            logger.warning("Redis cache set failed: %s", exc)

    def _backend_delete(self, key: str) -> None:
        if self._backend == "lru":
            self._lru.delete(key)
        else:
            r = self._get_redis()
            r.delete(f"{self._namespace}:{key}")

    def _get_redis(self):
        if self._redis is None:
            import redis as redis_lib
            self._redis = redis_lib.from_url(self._redis_url)
        return self._redis

    def _redis_flush_namespace(self) -> None:
        try:
            r = self._get_redis()
            keys = r.keys(f"{self._namespace}:*")
            if keys:
                r.delete(*keys)
        except Exception as exc:
            logger.warning("Redis flush failed: %s", exc)
