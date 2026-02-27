from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Any


@dataclass
class _Entry:
    expires_at: float
    value: Any
    created_at: float


class TTLCache:
    def __init__(self, ttl_seconds: int, max_entries: int = 512):
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._store: dict[str, _Entry] = {}
        self._lock = RLock()

    def _prune_expired(self, now: float) -> None:
        expired = [key for key, ent in self._store.items() if now >= ent.expires_at]
        for key in expired:
            self._store.pop(key, None)

    def _evict_if_needed(self) -> None:
        if self.max_entries <= 0:
            self._store.clear()
            return
        overflow = len(self._store) - self.max_entries
        if overflow <= 0:
            return
        oldest_keys = sorted(self._store, key=lambda key: self._store[key].created_at)[:overflow]
        for key in oldest_keys:
            self._store.pop(key, None)

    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            ent = self._store.get(key)
            if not ent:
                return None
            if now >= ent.expires_at:
                self._store.pop(key, None)
                return None
            return ent.value

    def set(self, key: str, value: Any) -> None:
        now = time.time()
        with self._lock:
            self._prune_expired(now)
            self._store[key] = _Entry(expires_at=now + self.ttl, value=value, created_at=now)
            self._evict_if_needed()

    def get_or_set(self, key: str, fn: Callable[[], Any]) -> Any:
        now = time.time()
        with self._lock:
            ent = self._store.get(key)
            if ent and now < ent.expires_at:
                return ent.value
            if ent and now >= ent.expires_at:
                self._store.pop(key, None)

        value = fn()

        with self._lock:
            now = time.time()
            self._prune_expired(now)
            ent = self._store.get(key)
            if ent and now < ent.expires_at:
                return ent.value
            self._store[key] = _Entry(expires_at=now + self.ttl, value=value, created_at=now)
            self._evict_if_needed()
            return value
