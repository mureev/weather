"""Text city search.

Two design notes worth stating, because both were choices rather than defaults.

**Why not Yandex's own search?** `yandex.ru/robots.txt` disallows
`/pogoda/search` specifically -- one of only four disallowed paths under
`/pogoda`. Scraping the thing they explicitly asked us not to scrape, in a
project whose legal footing rests on robots.txt permitting the rest, would be
silly.

**Why no reverse geocoder for GPS?** Because we don't need one. A GPS fix goes
to Yandex as lat/lon, and the Yandex page *tells us which city it thinks that
is*. Asking a fourth party to name the user's coordinates would add a data
recipient to a project whose entire point is reducing the number of parties who
learn where the phone is.

Results are cached, so the second search for "казань" costs nothing.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..cache import TTLCache
from ..cities import ad_hoc, slugify_ru
from ..config import settings
from ..models import Place

log = logging.getLogger(__name__)

_cache: TTLCache[list[dict[str, Any]]] = TTLCache(ttl_s=7 * 86400, grace_s=30 * 86400)

# Country codes we surface first. Not a filter -- a sort key. Searching for
# "Париж" should still find Paris.
_PREFERRED = ("RU", "BY", "KZ")


async def search(client: httpx.AsyncClient, q: str, limit: int = 8,
                 allow_fetch=lambda: True) -> list[Place] | None:
    """Places matching `q`, or None when `allow_fetch` refused a cache miss."""
    q = (q or "").strip()
    if len(q) < 2:
        return []

    key = q.casefold()
    hit = _cache.get_fresh(key) or _cache.get_stale(key)
    if hit is not None:
        return [_to_place(r) for r in hit.value][:limit]

    if not allow_fetch():
        return None
    params = {"name": q, "count": 20, "language": "ru", "format": "json"}
    try:
        r = await client.get(settings.geocode_url, params=params,
                             timeout=settings.upstream_timeout_s)
        r.raise_for_status()
        rows = (r.json() or {}).get("results") or []
    except Exception as e:
        log.warning("geocode failed for %r: %s", q, e)
        return []

    rows = [r for r in rows if r.get("latitude") is not None]
    rows.sort(key=_rank)
    _cache.put(key, rows)
    return [_to_place(r) for r in rows][:limit]


def _rank(row: dict[str, Any]) -> tuple[int, float]:
    cc = (row.get("country_code") or "").upper()
    pref = _PREFERRED.index(cc) if cc in _PREFERRED else len(_PREFERRED)
    # Bigger places first within a country band.
    return pref, -float(row.get("population") or 0)


def _to_place(row: dict[str, Any]) -> Place:
    name = row.get("name") or "?"
    admin = row.get("admin1") or ""
    country = row.get("country") or ""
    # Disambiguating label, because there are eleven Александровskys.
    label = name
    extra = ", ".join(x for x in (admin, country) if x and x != name)
    p = ad_hoc(row["latitude"], row["longitude"], name=label)
    p.slug = f"{slugify_ru(name)}@{p.lat:.2f},{p.lon:.2f}"
    p.tz = row.get("timezone") or "Europe/Moscow"
    # Stash the disambiguator where the UI can show it without it becoming the
    # displayed city name.
    p.__dict__["subtitle"] = extra
    return p


def subtitle(p: Place) -> str | None:
    return p.__dict__.get("subtitle")
