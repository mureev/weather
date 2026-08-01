"""Source orchestration.

Three sources, fetched concurrently, all three returned. The switcher in the UI
is a client-side choice between readings that were all taken at the same
moment — which is the only way a comparison between them means anything.

What changed when the third source arrived, and why:

The two-source design made Open-Meteo a *referee*. Its job was to disagree, and
a wide disagreement caused the app to reject Yandex and substitute Open-Meteo
automatically. That was the right call when you could only ever see one number
and had no way to judge it yourself.

It is the wrong call now. With three readings side by side you can see the
disagreement directly, and an app that silently swaps your explicitly-chosen
source for a different one is doing the thing this codebase avoids everywhere
else: making a decision quietly on your behalf. So the divergence is still
computed, and still recorded in `health.divergence_c` for `/api/health`, and it
no longer overrides anything.

**Per-source validation is untouched**, because it answers a different
question. "These two sources disagree" is a judgement call. "This source
returned 743 in a temperature field" is a broken parser, and that value gets
dropped — never clamped — exactly as before.

The failure ladder, per source, independently::

    a field fails a contract  -> drop that field, serve the rest, say so
    the source is unusable    -> that tab is disabled with a reason
    every source is unusable  -> serve the last good payload, marked stale
    nothing cached either     -> 503 with an honest error
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

import httpx

from .cache import TTLCache
from .config import settings
from .http import client
from .models import Health, ParseError, Place, SourceView, Status, Weather
from .routing import fetch_gismeteo, label_route, sticky_route
from .series import align_to_now
from .sources import openmeteo, yandex_html
from .sun import hour_times, is_night, local_now, nightify
from .validation import (
    Report,
    check_coherence,
    check_continuity,
    check_daily_series,
    check_series,
    validate_current,
    validate_days,
)

log = logging.getLogger(__name__)

_cache: TTLCache[Weather] = TTLCache(settings.cache_ttl_s, settings.stale_grace_s,
                                     settings.cache_max_entries)
_locks: dict[str, asyncio.Lock] = {}

# Preference order. The first available one is what a fresh install shows;
# after that the choice is the user's and lives in localStorage.
ORDER = ("yandex", "gismeteo", "openmeteo")
LABELS = {"yandex": "Яндекс", "gismeteo": "Gismeteo", "openmeteo": "Open-Meteo"}


def _lock(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


async def get_weather(place: Place, *, force: bool = False) -> Weather:
    key = place.slug
    if not force:
        fresh = _cache.get_fresh(key)
        if fresh is not None:
            fresh.value.health.age_s = fresh.age_s
            return _sunlit(fresh.value)

    async with _lock(key):
        if not force:
            fresh = _cache.get_fresh(key)
            if fresh is not None:
                fresh.value.health.age_s = fresh.age_s
                return _sunlit(fresh.value)
        return _sunlit(await _build(place, key))


def _sunlit(weather: Weather) -> Weather:
    """Put the right half of the sky behind every icon.

    None of the three sources can be relied on for this. Yandex ships a real
    day/night flag in its icon codes; Gismeteo has the information in its
    markup but we read conditions from the tooltips, which are just words;
    Open-Meteo's WMO codes have no concept of it at all. Reading Gismeteo's
    flag would fix one source, leave the other two wrong, and add a per-source
    detail that rots at their next redesign.

    So it is computed once, here, from the place and the clock -- see `sun.py`
    for why arithmetic rather than a fixed evening window. It runs on *serve*
    rather than on build, and is idempotent, because a payload cached at 19:50
    and served from the stale grace at 22:00 would otherwise still be sunny.

    Daily icons are deliberately left alone: a day's summary is a day.
    """
    place = weather.place
    now = local_now(place.tz)
    dark_now = is_night(place.lat, place.lon, now)
    for sv in weather.sources.values():
        if sv.current is not None:
            sv.current.icon = nightify(sv.current.icon, dark_now)
        if sv.hourly:
            when = hour_times([h.time for h in sv.hourly], place.tz, now)
            for hour, stamp in zip(sv.hourly, when, strict=True):
                if stamp is not None:
                    hour.icon = nightify(
                        hour.icon, is_night(place.lat, place.lon, stamp))
    return weather


async def _build(place: Place, key: str) -> Weather:
    now = dt.datetime.now(dt.UTC)
    previous = _cache.get_stale(key)

    # Gismeteo opens its own clients: its transport differs (HTTP/1.1 while the
    # others use whatever httpx negotiates) and it may have to try several
    # egress routes, each of which needs a client of its own.
    async with client() as c:
        ya, gm, om_raw = await asyncio.gather(
            _yandex(c, place), fetch_gismeteo(place), openmeteo.fetch(c, place),
            return_exceptions=False,
        )

    weather = Weather(place=place, fetched_at=now.isoformat(timespec="seconds"),
                      health=Health())

    # The place a source actually resolved is a better label than the one we
    # guessed -- particularly for a GPS fix, where we had no name at all.
    if ya[0] is not None and ya[0].ident.name and (place.ad_hoc or not place.name):
        place.name = ya[0].ident.name
    weather.place = place

    weather.sources["yandex"] = _view_from_scrape("yandex", ya, previous, place.tz)
    weather.sources["gismeteo"] = _view_from_scrape("gismeteo", gm, previous, place.tz)
    weather.sources["openmeteo"] = _view_from_openmeteo(om_raw)

    # Which door actually opened. Never rendered; it is the first thing you
    # want when Gismeteo is fine on your laptop and disabled on the server.
    route = sticky_route()
    if weather.sources["gismeteo"].available and route is not None:
        weather.health.detail.append(f"gismeteo via {label_route(route)}")

    available = [k for k in ORDER if weather.sources[k].available]
    if not available:
        return _all_down(weather, previous)

    weather.selected = available[0]
    _record_divergence(weather)

    worst = Status.OK
    for k in available:
        if weather.sources[k].warnings or weather.sources[k].dropped_fields:
            worst = Status.DEGRADED
    if len(available) < len(ORDER):
        worst = Status.DEGRADED
    weather.health.status = worst

    _cache.put(key, weather)
    return weather


# --- per-source assembly ---------------------------------------------------

async def _yandex(c: httpx.AsyncClient, place: Place):
    try:
        got, url = await yandex_html.load(c, place)
        log.info("yandex ok via %s", url)
        return got, None
    except ParseError as e:
        log.warning("yandex unusable: %s", e)
        return None, str(e)
    except Exception as e:
        log.warning("yandex fetch error: %s", e)
        return None, str(e)


def _view_from_scrape(key: str, result, previous, tz: str = "UTC") -> SourceView:
    got, error = result
    sv = SourceView(key=key, label=LABELS[key])
    if got is None:
        sv.available = False
        sv.reason = _reason(error)
        if error:
            sv.detail.append(error)
        return sv

    rep = Report()
    current = validate_current(got.current, rep)
    daily = validate_days(got.daily, rep)
    hourly = check_series(got.hourly, rep)
    check_daily_series(daily, rep)
    # Last, because it is the only layer that needs the others' output: it asks
    # whether these fields agree with each other, not whether each is possible.
    check_coherence(current, hourly, daily, rep, tz)
    # Every source begins its hourly series somewhere different -- the next
    # hour, midnight, or now. Normalise before it reaches the screen, or the
    # same strip means three different things depending on which tab is open.
    hourly = align_to_now(hourly, current,
                          current.observed_epoch if current else None, tz)

    if previous is not None:
        prev_view = previous.value.sources.get(key)
        if prev_view is not None and prev_view.current is not None:
            check_continuity(current.temp_c if current else None,
                             prev_view.current.temp_c, previous.age_s, rep)

    if current is None or current.temp_c is None:
        sv.available = False
        sv.reason = "не прочиталось"
        sv.detail.extend(rep.warnings)
        return sv

    sv.available = True
    sv.current = current
    sv.daily = daily
    sv.hourly = hourly
    sv.nowcast = got.nowcast
    sv.provenance = got.provenance
    sv.dropped_fields = rep.dropped
    sv.warnings = list(rep.warnings)

    if sv.fallback_profile:
        sv.warnings.append(
            f"{LABELS[key]}: все поля получены запасным способом — вероятно, "
            "вёрстка изменилась. Данные пока сходятся, но парсер стоит проверить."
        )
    return sv


# These land in a tab a third of a card wide, so they have to be short enough
# to read at a glance. The full text -- httpx's three-line message with its MDN
# link -- still goes to `detail`, where whoever is debugging wants it.
#
# 403 from Gismeteo has exactly one cause and it is not the headers: they block
# by IP. The same request gets 200 from a Russian address and 403 from this
# server, plain curl and stdlib urllib included.
_HTTP_REASONS = {
    "403": "заблокирован",
    "404": "не найдено",
    "429": "слишком часто",
    "500": "сбой источника",
    "502": "сбой источника",
    "503": "недоступен",
}


def _reason(error: str | None) -> str:
    """A short Russian line for the disabled tab.

    httpx's own message is three lines ending in a MDN link, which is useful in
    a log and useless on a phone. The full text still goes to `detail`.
    """
    if not error:
        return "недоступен"
    for code, text in _HTTP_REASONS.items():
        if code in error:
            return text
    if "timeout" in error.lower() or "timed out" in error.lower():
        return "нет ответа"
    if "wrong place" in error:
        return "другой город"
    if "нет данных" in error:
        return "нет города"
    return error if len(error) < 22 else "недоступен"


def _view_from_openmeteo(raw) -> SourceView:
    sv = SourceView(key="openmeteo", label=LABELS["openmeteo"])
    if not raw:
        sv.available = False
        sv.reason = "недоступен"
        return sv
    cur = openmeteo.to_current(raw)
    if cur is None or cur.temp_c is None:
        sv.available = False
        sv.reason = "нет данных"
        return sv

    rep = Report()
    sv.current = validate_current(cur, rep)
    sv.daily = validate_days(openmeteo.to_daily(raw), rep)
    sv.hourly = check_series(openmeteo.to_hourly(raw), rep)
    sv.available = sv.current is not None and sv.current.temp_c is not None
    sv.reason = None if sv.available else "нет данных"
    sv.dropped_fields = rep.dropped
    sv.warnings = list(rep.warnings)
    # A JSON API has no layout to fall back through, so provenance is flat.
    sv.provenance = {"temp_c": 1}
    return sv


def _record_divergence(w: Weather) -> None:
    """Pairwise temperature deltas, for the record and nothing else."""
    keys = [k for k in ORDER
            if w.sources[k].available and w.sources[k].current
            and w.sources[k].current.temp_c is not None]
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            delta = round(w.sources[a].current.temp_c
                          - w.sources[b].current.temp_c, 1)
            w.health.divergence_c[f"{a}/{b}"] = delta
            if abs(delta) >= settings.divergence_warn_c:
                w.health.detail.append(
                    f"{a} and {b} disagree by {abs(delta):.1f}°C")


def _all_down(w: Weather, previous) -> Weather:
    """Nothing worked. The last good payload, or an honest failure."""
    if previous is not None:
        stale = previous.value
        stale.health.status = Status.STALE
        stale.health.age_s = previous.age_s
        stale.health.warnings = [
            f"Данные устарели на {previous.age_s // 60} мин — "
            "ни один источник сейчас не отвечает"
        ]
        return stale

    w.health.status = Status.DOWN
    w.health.warnings.append("Ни один источник не отвечает, кэш пуст")
    for sv in w.sources.values():
        w.health.detail.extend(sv.detail)
    return w


def cache_stats() -> dict:
    return _cache.stats()


def invalidate(key: str | None = None) -> None:
    if key:
        _cache.drop(key)
    else:
        for k in _cache:
            _cache.drop(k)
