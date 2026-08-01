"""TTL cache with a stale-serving grace period.

Two separate lifetimes, and the distinction matters. `ttl` is how long a value
is *fresh* -- serve it and don't refetch. `grace` is how long a stale value is
still better than nothing, which on a weather app is a long time: a
four-hour-old temperature with an honest timestamp beats a 503.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class Entry(Generic[T]):
    value: T
    stored_at: float

    @property
    def age_s(self) -> int:
        return int(time.time() - self.stored_at)


class TTLCache(Generic[T]):
    def __init__(self, ttl_s: int, grace_s: int) -> None:
        self.ttl_s = ttl_s
        self.grace_s = grace_s
        self._d: dict[str, Entry[T]] = {}
        self._lock = threading.Lock()

    def get_fresh(self, key: str) -> Entry[T] | None:
        e = self._peek(key)
        if e is not None and e.age_s <= self.ttl_s:
            return e
        return None

    def get_stale(self, key: str) -> Entry[T] | None:
        """The last good value, if it is still inside the grace window."""
        e = self._peek(key)
        if e is not None and e.age_s <= self.grace_s:
            return e
        return None

    def _peek(self, key: str) -> Entry[T] | None:
        with self._lock:
            return self._d.get(key)

    def put(self, key: str, value: T) -> None:
        with self._lock:
            self._d[key] = Entry(value=value, stored_at=time.time())

    def drop(self, key: str) -> None:
        with self._lock:
            self._d.pop(key, None)

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._d)

    def __iter__(self):
        return iter(self.keys())

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {k: {"age_s": e.age_s} for k, e in self._d.items()}
