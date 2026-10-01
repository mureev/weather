"""Open-Meteo: the third source, and the only one with an API.

It began as the referee. With two sources it was fetched to *disagree*: a wide
gap rejected the scrape and put Open-Meteo on screen in its place. That ended
when it became a tab of its own (`DECISIONS.md` §4). The three readings now sit
side by side, the gaps between them are recorded in `/api/health`, and nothing
here overrules anything. What made it a good referee still makes it a good
third opinion: it shares no code, no model and no vendor with the other two.

It is also the deepest source by the hour -- ten days of hourly values, which is
why this tab's day screen can draw a curve for any day you open -- and the only
one that is documented, versioned and needs no key.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import httpx

from ..config import settings
from ..models import Current, Day, Hour, Place

log = logging.getLogger(__name__)

# WMO 4677-ish codes as Open-Meteo emits them, in the vocabulary Yandex uses,
# so switching tabs does not change the words the sky is described in.
WMO: dict[int, tuple[str, str]] = {
    0: ("Ясно", "clear"),
    1: ("Малооблачно", "partly"),
    2: ("Облачно с прояснениями", "partly"),
    3: ("Пасмурно", "overcast"),
    45: ("Туман", "fog"), 48: ("Туман с изморозью", "fog"),
    51: ("Слабая морось", "drizzle"), 53: ("Морось", "drizzle"),
    55: ("Сильная морось", "drizzle"),
    56: ("Ледяная морось", "freezing"), 57: ("Сильная ледяная морось", "freezing"),
    61: ("Небольшой дождь", "rain"), 63: ("Дождь", "rain"),
    65: ("Сильный дождь", "heavy-rain"),
    66: ("Ледяной дождь", "freezing"), 67: ("Сильный ледяной дождь", "freezing"),
    71: ("Небольшой снег", "snow"), 73: ("Снег", "snow"),
    75: ("Сильный снег", "heavy-snow"), 77: ("Снежные зёрна", "snow"),
    80: ("Небольшой ливень", "rain"), 81: ("Ливень", "heavy-rain"),
    82: ("Сильный ливень", "heavy-rain"),
    85: ("Снегопад", "snow"), 86: ("Сильный снегопад", "heavy-snow"),
    95: ("Гроза", "thunder"),
    96: ("Гроза с градом", "thunder"), 99: ("Сильная гроза с градом", "thunder"),
}

_CURRENT = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,"
    "surface_pressure,wind_speed_10m,wind_direction_10m,weather_code"
)
_HOURLY = "temperature_2m,weather_code,precipitation,precipitation_probability"
_DAILY = (
    "temperature_2m_max,temperature_2m_min,weather_code,"
    "precipitation_probability_max,precipitation_sum,"
    "apparent_temperature_max,apparent_temperature_min,"
    "wind_speed_10m_max,wind_direction_10m_dominant,"
    "uv_index_max,sunrise,sunset,daylight_duration"
)

_DIRS = ("северный", "северо-восточный", "восточный", "юго-восточный",
         "южный", "юго-западный", "западный", "северо-западный")


def _bearing_to_ru(deg: float | None) -> str | None:
    if deg is None:
        return None
    return _DIRS[int((float(deg) + 22.5) % 360 // 45)]


def _cond(code: Any) -> tuple[str | None, str | None]:
    try:
        return WMO[int(code)]
    except (TypeError, ValueError, KeyError):
        return None, None


async def fetch(client: httpx.AsyncClient, place: Place) -> dict[str, Any] | None:
    params = {
        "latitude": f"{place.lat:.4f}",
        "longitude": f"{place.lon:.4f}",
        "current": _CURRENT,
        "hourly": _HOURLY,
        "daily": _DAILY,
        # A GPS fix or a searched place has no zone of its own -- `ad_hoc`
        # places are born "Europe/Moscow" -- so ask Open-Meteo to resolve it,
        # and the service adopts the answer. Otherwise Novosibirsk's days were
        # Moscow's days, its sunrise was printed in Moscow time, and the
        # client's «сейчас» column was four hours out.
        "timezone": "auto" if place.ad_hoc else place.tz,
        "wind_speed_unit": "ms",
        "forecast_days": 10,
        # No `forecast_hours`. It was capping the hourly array at 24 entries,
        # which is why the only source that can draw an Apple-style curve for
        # *any* day of the forecast was only ever asked about today. The cap
        # cost nothing to remove and was the single largest gap between what
        # this app showed and what it already had access to.
        #
        # 240 entries rather than 24. The payload is extremely repetitive, so
        # gzip absorbs nearly all of it -- and there is a test asserting the
        # compressed cold load stays inside its budget, which is the right
        # place for that argument to be settled.
    }
    try:
        r = await client.get(settings.openmeteo_url, params=params,
                             timeout=settings.upstream_timeout_s)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("open-meteo fetch failed: %s", e)
        return None


def _epoch(stamp: Any, offset_s: Any) -> int | None:
    """`"2026-08-01T14:00"` plus the response's UTC offset -> a UTC epoch.

    Open-Meteo formats every timestamp in the *requested* timezone and reports
    the offset it used in `utc_offset_seconds`, so the conversion is exact
    arithmetic on values from the same response. No clock is read and no
    timezone database is consulted -- which matters, because this is the number
    the whole app uses to decide which entry describes "now", and a series
    aligned against a guess is the bug `series.py` exists to prevent.
    """
    if not isinstance(stamp, str) or not isinstance(offset_s, (int, float)):
        return None
    try:
        naive = dt.datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return int(naive.replace(tzinfo=dt.UTC).timestamp()) - int(offset_s)


def to_current(raw: dict[str, Any]) -> Current | None:
    c = (raw or {}).get("current") or {}
    if "temperature_2m" not in c:
        return None
    cond, icon = _cond(c.get("weather_code"))
    hpa = c.get("surface_pressure")
    return Current(
        temp_c=_num(c.get("temperature_2m")),
        feels_like_c=_num(c.get("apparent_temperature")),
        condition=cond,
        icon=icon,
        humidity_pct=_num(c.get("relative_humidity_2m")),
        pressure_mmhg=round(hpa * 0.750062, 1) if isinstance(hpa, (int, float)) else None,
        wind_ms=_num(c.get("wind_speed_10m")),
        wind_dir=_bearing_to_ru(c.get("wind_direction_10m")),
        observed_at=c.get("time"),
        observed_epoch=_epoch(c.get("time"), (raw or {}).get("utc_offset_seconds")),
    )


def to_hourly(raw: dict[str, Any], limit: int | None = None) -> list[Hour]:
    """Every hour the response carries, not the first day of them.

    There used to be a 24 here, and it was the reason the one source that can
    draw an hour-by-hour curve for *any* day of the forecast was only ever
    asked about today. The day-detail screen slices this list by date, so the
    cap was the feature's only real obstacle -- see the note in `fetch` about
    where the size argument gets settled.
    """
    h = (raw or {}).get("hourly") or {}
    times = h.get("time") or []
    offset = (raw or {}).get("utc_offset_seconds")
    out: list[Hour] = []
    for i, t in enumerate(times if limit is None else times[:limit]):
        cond, icon = _cond(_at(h, "weather_code", i))
        out.append(Hour(
            time=t,
            at=_epoch(t, offset),
            temp_c=_num(_at(h, "temperature_2m", i)),
            condition=cond,
            icon=icon,
            precip_mm=_num(_at(h, "precipitation", i)),
            precip_prob=_num(_at(h, "precipitation_probability", i)),
        ))
    return out


def to_daily(raw: dict[str, Any]) -> list[Day]:
    d = (raw or {}).get("daily") or {}
    dates = d.get("time") or []
    out: list[Day] = []
    for i, date in enumerate(dates):
        cond, icon = _cond(_at(d, "weather_code", i))
        seconds = _num(_at(d, "daylight_duration", i))
        out.append(Day(
            date=date,
            temp_min_c=_num(_at(d, "temperature_2m_min", i)),
            temp_max_c=_num(_at(d, "temperature_2m_max", i)),
            condition=cond,
            icon=icon,
            precip_prob=_num(_at(d, "precipitation_probability_max", i)),
            precip_mm=_num(_at(d, "precipitation_sum", i)),
            feels_min_c=_num(_at(d, "apparent_temperature_min", i)),
            feels_max_c=_num(_at(d, "apparent_temperature_max", i)),
            wind_ms=_num(_at(d, "wind_speed_10m_max", i)),
            wind_dir=_bearing_to_ru(_at(d, "wind_direction_10m_dominant", i)),
            uv_index=_num(_at(d, "uv_index_max", i)),
            sunrise=_clock(_at(d, "sunrise", i)),
            sunset=_clock(_at(d, "sunset", i)),
            daylight=_duration(seconds),
        ))
    return out


def _clock(stamp: Any) -> str | None:
    """`2026-08-01T03:48` -> `03:48`. The date is already the row's key."""
    return stamp[11:16] if isinstance(stamp, str) and len(stamp) >= 16 else None


def _duration(seconds: float | None) -> str | None:
    """Seconds of daylight as «16 ч 12 мин», matching how Yandex words it --
    so the detail screen reads the same whichever tab you are on."""
    if seconds is None:
        return None
    minutes = round(seconds / 60)
    return f"{minutes // 60} ч {minutes % 60} мин"


def _at(block: dict[str, Any], key: str, i: int) -> Any:
    seq = block.get(key)
    if isinstance(seq, list) and i < len(seq):
        return seq[i]
    return None


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None
