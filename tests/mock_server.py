"""Run the real app against the recorded fixture, with no network at all.

    python -m tests.mock_server                 # healthy, summer
    YW_MOCK=winter   python -m tests.mock_server   # negative temperatures
    YW_MOCK=degraded python -m tests.mock_server   # scraper broken, OM fallback
    YW_MOCK=down     python -m tests.mock_server   # nothing works

The `degraded` scenario is worth looking at with your eyes. If it does not look
obviously wrong at a glance, the design has failed -- the entire point is that
a bad reading is impossible to mistake for a good one.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

MODE = os.environ.get("YW_MOCK", "ok")
FIX = pathlib.Path(__file__).parent / "fixtures" / "current.html"
RAW = FIX.read_text(encoding="utf-8", errors="replace")

if MODE == "winter":
    # Swap the sign on every rendered temperature *and* in the flight stream,
    # using U+2212 exactly as Yandex does. This is the scenario that catches a
    # parser written and tested in July.
    RAW = re.sub(r'"temperature(InCelsius)?":(\d+)', r'"temperature\1":-\2', RAW)
    RAW = re.sub(r'"feelsLike":(\d+)', r'"feelsLike":-\1', RAW)
    RAW = RAW.replace("+1", "−1").replace("+2", "−2").replace("+0", "−0")

from app import service  # noqa: E402
from app.sources import gismeteo, openmeteo, yandex_html  # noqa: E402


async def _fetch(_client, _url):
    if MODE in ("degraded", "down"):
        raise RuntimeError("mock: Yandex unreachable")
    return RAW


# All three from the `mf-` set, which is one recording session. Mixing vintages
# -- the landing page from one day, the hourly strip from another -- reproduces
# the coherence failure this app now detects, so the mock reported itself broken
# on every fetch while the parser was fine. Fixtures that describe different
# moments are not a smaller version of reality; they are a different reality.
_GM = pathlib.Path(__file__).parent / "fixtures"
GM_NOW = (_GM / "mf-current.html").read_text(encoding="utf-8", errors="replace")
GM_DAYS = (_GM / "mf-10days.html").read_text(encoding="utf-8", errors="replace")
GM_HOURLY = (_GM / "mf-hourly.html").read_text(encoding="utf-8", errors="replace")
GM_PARTS = (_GM / "mf-3days.html").read_text(encoding="utf-8", errors="replace")

if MODE == "winter":
    GM_NOW = re.sub(r'"(temperatureAir|temperatureFeelsLike)": ?\[(\d+)\]',
                    r'"\1":[-\2]', GM_NOW)
    GM_DAYS = re.sub(r'<temperature-value value="(\d+)"',
                     r'<temperature-value value="-\1"', GM_DAYS)


async def _gm_fetch(_client, url, **_kw):
    """The real fixture through the real parser, so the Gismeteo tab in mock
    mode shows what the parser actually produces rather than something
    invented.

    `**_kw` is not decoration. The real `fetch_html` grew a keyword-only
    `timeout=` so the route search could give each candidate a slice of its
    budget; this stub did not, so every mock fetch raised `TypeError`, the
    router logged it as an ordinary fetch error, and the Gismeteo tab was
    quietly disabled in every screenshot and browser test for as long as that
    had been true. A stub whose signature drifts from the thing it stands in
    for fails like a broken upstream, which is the one failure this app is
    designed to shrug off.
    """
    if MODE in ("degraded", "down"):
        raise RuntimeError("mock: Gismeteo unreachable")
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return {"10-days": GM_DAYS, "hourly": GM_HOURLY,
            "3-days": GM_PARTS}.get(tail, GM_NOW)


# The shape Open-Meteo actually returns, at the size it actually returns it.
#
# This used to be twenty-four hours and four daily arrays, hand-typed, and it
# quietly made two tests dishonest. The byte-budget test measured a payload a
# tenth of the real one, and the day-detail screen -- which slices the hourly
# series by date -- had no second date to slice to. A fixture smaller than
# reality is a test that agrees with you.
#
# Ten days, hourly throughout, every daily variable we ask for. Temperatures
# follow a diurnal curve rather than `h % 5`, because the validator rejects a
# series that steps more than 8° between adjacent hours and a sawtooth is
# indistinguishable from the row misalignment that check exists to catch.
_DAY0 = dt.date(2026, 7, 31)
_HOURS = 24 * 10


def _diurnal(base: float, i: int) -> float:
    """Warmest at 15:00, coldest at 03:00, drifting a little over the period."""
    return round(base + 5.0 * math.sin(2 * math.pi * (i % 24 - 9) / 24)
                 + 0.4 * (i // 24), 1)


async def _om(_client, place):
    if MODE == "down":
        return None
    base = -14.0 if MODE == "winter" else 15.4
    code = 71 if MODE == "winter" else 3
    stamps = [(dt.datetime(2026, 7, 31) + dt.timedelta(hours=i)).isoformat(
        timespec="minutes") for i in range(_HOURS)]
    dates = [(_DAY0 + dt.timedelta(days=d)).isoformat() for d in range(10)]
    return {
        # Every timestamp above is in this offset; the parser needs it to say
        # which instant any of them names.
        "utc_offset_seconds": 10800,
        "timezone": "Europe/Moscow",
        "current": {"time": "2026-07-31T21:00", "temperature_2m": base,
                    "apparent_temperature": base - 1,
                    "relative_humidity_2m": 88, "surface_pressure": 993.0,
                    "wind_speed_10m": 1.2, "wind_direction_10m": 270,
                    "weather_code": 71 if MODE == "winter" else 0},
        "hourly": {
            "time": stamps,
            "temperature_2m": [_diurnal(base, i) for i in range(_HOURS)],
            "weather_code": [code] * _HOURS,
            "precipitation": [round(0.4 * (i % 7 == 0), 1) for i in range(_HOURS)],
            "precipitation_probability": [10 + (i % 9) * 5 for i in range(_HOURS)]},
        "daily": {
            "time": dates,
            "temperature_2m_max": [base + 4 + d for d in range(10)],
            "temperature_2m_min": [base - 3 + d for d in range(10)],
            "weather_code": [61, 3, 0, 2, 71, 95, 3, 0, 1, 80],
            "precipitation_probability_max": [40, 10, 0, 20, 60, 80, 5, 0, 0, 55],
            "precipitation_sum": [3.2, 0.4, 0, 1.1, 6.0, 12.4, 0.2, 0, 0, 2.8],
            "apparent_temperature_max": [base + 3 + d for d in range(10)],
            "apparent_temperature_min": [base - 5 + d for d in range(10)],
            "wind_speed_10m_max": [2.1, 3.4, 1.8, 5.2, 4.0, 6.6, 2.2, 1.4, 3.0, 4.4],
            "wind_direction_10m_dominant": [270, 300, 45, 90, 180, 225, 315, 0, 135, 200],
            "uv_index_max": [5.1, 6.3, 7.0, 4.2, 3.8, 2.1, 6.9, 7.4, 5.5, 4.0],
            "sunrise": [f"{d}T03:5{i % 10}" for i, d in enumerate(dates)],
            "sunset": [f"{d}T20:1{i % 10}" for i, d in enumerate(dates)],
            "daylight_duration": [58200.0 - 120 * d for d in range(10)]},
    }


# The per-day page, recorded for 7 August 2026. Served for *whatever* day is
# asked for, with the date rewritten to match -- otherwise the parser's own
# check (it rejects a page describing a different day than the one requested,
# exactly as it rejects a page describing a different city) would refuse every
# request but one, and the mock would exercise the failure path instead of the
# feature.
YA_DAY = (_GM / "ya-day5.html").read_text(encoding="utf-8", errors="replace")


async def _ya_day(_client, url):
    if MODE in ("degraded", "down"):
        raise RuntimeError("mock: Yandex unreachable")
    m = re.search(r"/day-(\d+)", url)
    if not m:
        return await _fetch(_client, url)
    want = dt.date.today() + dt.timedelta(days=int(m.group(1)))
    return YA_DAY.replace("2026-08-07T", f"{want.isoformat()}T")


async def _route_yandex(client, url):
    return await (_ya_day(client, url) if "/day-" in url else _fetch(client, url))


yandex_html.fetch_html = _route_yandex
gismeteo.fetch_html = _gm_fetch
openmeteo.fetch = _om
service.invalidate()

if __name__ == "__main__":
    import uvicorn

    from app.main import app

    port = int(os.environ.get("PORT", "8098"))
    print(f"mock [{MODE}] -> http://127.0.0.1:{port}/weather/")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
