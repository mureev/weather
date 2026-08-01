"""Open-Meteo: the referee.

Its job is to **disagree**. It is not a co-equal source and it does not get a
vote on what the weather is; it gets a vote on whether our scraper has quietly
started reading the wrong cell. It only becomes the *displayed* source when the
scrape has failed or been rejected -- and when that happens, the UI says so in
Russian rather than passing Open-Meteo off as Yandex.

The one place it is primary by design is hourly, because the scrape has no
reliable hourly series to take.

No key, no quota, documented and versioned. The ideal second opinion: it shares
no code, no model and no vendor with the thing it is checking.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import settings
from ..models import Current, Day, Hour, Place

log = logging.getLogger(__name__)

# WMO 4677-ish codes as Open-Meteo emits them, in the vocabulary Yandex uses,
# so a fallback render doesn't visibly change language mid-app.
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
    "precipitation_probability_max"
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
        "timezone": place.tz,
        "wind_speed_unit": "ms",
        "forecast_days": 10,
        "forecast_hours": 24,
    }
    try:
        r = await client.get(settings.openmeteo_url, params=params,
                             timeout=settings.upstream_timeout_s)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("open-meteo fetch failed: %s", e)
        return None


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
    )


def to_hourly(raw: dict[str, Any], limit: int = 24) -> list[Hour]:
    h = (raw or {}).get("hourly") or {}
    times = h.get("time") or []
    out: list[Hour] = []
    for i, t in enumerate(times[:limit]):
        cond, icon = _cond(_at(h, "weather_code", i))
        out.append(Hour(
            time=t,
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
        out.append(Day(
            date=date,
            temp_min_c=_num(_at(d, "temperature_2m_min", i)),
            temp_max_c=_num(_at(d, "temperature_2m_max", i)),
            condition=cond,
            icon=icon,
            precip_prob=_num(_at(d, "precipitation_probability_max", i)),
        ))
    return out


def _at(block: dict[str, Any], key: str, i: int) -> Any:
    seq = block.get(key)
    if isinstance(seq, list) and i < len(seq):
        return seq[i]
    return None


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None
