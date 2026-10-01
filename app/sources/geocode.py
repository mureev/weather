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

**Why two requests per search.** The geocoder answers in one language per
request, and the interface now speaks two. Asking only in the language the
phone prefers would tell a fourth party what that is -- the same signal as an
`Accept-Language` header, which invariant 5 keeps on the phone. So every
search asks in both, whoever is asking, and the two answers are joined by the
geocoder's own id. A Russian reader sees «Париж», an English one Paris, and
upstream cannot tell them apart.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..cache import TTLCache
from ..cities import ad_hoc, slugify_ru
from ..config import settings
from ..models import Place
from ..ru_text import latin

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
    ru, en = await asyncio.gather(_ask(client, q, "ru"), _ask(client, q, "en"))
    if ru is None:
        return []
    by_id = {r.get("id"): r for r in en or [] if r.get("id") is not None}
    for r in ru:
        twin = by_id.get(r.get("id")) or {}
        for k in ("name", "admin1", "country"):
            if twin.get(k):
                r[k + "_en"] = twin[k]

    rows = [r for r in ru if r.get("latitude") is not None]
    rows.sort(key=_rank)
    _cache.put(key, rows)
    return [_to_place(r) for r in rows][:limit]


async def _ask(client: httpx.AsyncClient, q: str, lang: str) -> list | None:
    params = {"name": q, "count": 20, "language": lang, "format": "json"}
    try:
        r = await client.get(settings.geocode_url, params=params,
                             timeout=settings.upstream_timeout_s)
        r.raise_for_status()
        return (r.json() or {}).get("results") or []
    except Exception as e:
        log.warning("geocode (%s) failed for %r: %s", lang, q, e)
        return None


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
    p.name_en = row.get("name_en") or latin(name)
    # Stash the disambiguator where the UI can show it without it becoming the
    # displayed city name.
    p.__dict__["subtitle"] = extra
    en = [row.get("admin1_en") or latin(admin), row.get("country_en") or latin(country)]
    p.__dict__["subtitle_en"] = ", ".join(x for x in en if x and x != p.name_en)
    return p


def subtitle(p: Place, lang: str = "ru") -> str | None:
    return p.__dict__.get("subtitle_en" if lang == "en" else "subtitle")
