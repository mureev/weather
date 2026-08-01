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
    """Bounded, because the keys are not.

    Entries are keyed by place slug, and a slug is whatever the URL can
    express: every city the text search can name, plus one per distinct GPS
    fix -- coordinates rounded to two decimals, so about a kilometre apart,
    which over a country is a great many. Nothing here ever removed anything,
    so each one left a whole `Weather` object resident for the life of the
    process. Not a leak in the classic sense, since every entry was once
    legitimately wanted; just a set that only ever grows, on a box with a
    fixed amount of memory.

    Two rules, in order. Anything past the grace window is dropped -- it can
    never be served again, so keeping it is pure cost. If that leaves more than
    `max_entries`, the oldest go. `max_entries` is generous next to the handful
    of cities anyone actually uses; it exists to bound the pathological case,
    not to ration the ordinary one.
    """

    def __init__(self, ttl_s: int, grace_s: int, max_entries: int = 64) -> None:
        self.ttl_s = ttl_s
        self.grace_s = grace_s
        self.max_entries = max_entries
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
            now = time.time()
            self._d[key] = Entry(value=value, stored_at=now)
            self._evict(now)

    def _evict(self, now: float) -> None:
        """Caller holds the lock.

        `now` is passed in rather than read again, and the comparison is
        strict. Both matter at `grace_s=0`: reading the clock a second time
        puts the cutoff a few microseconds *after* the entry that was just
        stored, so the value you just wrote is evicted before it is ever
        served. A configuration nobody would choose on purpose, found by the
        test that was written to check the opposite thing.
        """
        cutoff = now - self.grace_s
        for k in [k for k, e in self._d.items() if e.stored_at < cutoff]:
            del self._d[k]
        if len(self._d) > self.max_entries:
            oldest = sorted(self._d.items(), key=lambda kv: kv[1].stored_at)
            for k, _ in oldest[: len(self._d) - self.max_entries]:
                del self._d[k]

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
