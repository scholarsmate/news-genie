from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class _Entry:
    expires_at: float
    value: Any


class TTLCache:
    def __init__(self, ttl_seconds: int):
        self.ttl = ttl_seconds
        self._store: dict[str, _Entry] = {}

    def get(self, key: str) -> Any | None:
        ent = self._store.get(key)
        if not ent:
            return None
        if time.time() >= ent.expires_at:
            self._store.pop(key, None)
            return None
        return ent.value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = _Entry(expires_at=time.time() + self.ttl, value=value)

    def get_or_set(self, key: str, fn: Callable[[], Any]) -> Any:
        v = self.get(key)
        if v is not None:
            return v
        v = fn()
        self.set(key, v)
        return v
