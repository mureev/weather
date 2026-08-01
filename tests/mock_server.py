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


GM_NOW = (pathlib.Path(__file__).parent / "fixtures" / "gm-current.html").read_text(
    encoding="utf-8", errors="replace")
GM_DAYS = (pathlib.Path(__file__).parent / "fixtures" / "gm-10days.html").read_text(
    encoding="utf-8", errors="replace")

if MODE == "winter":
    GM_NOW = re.sub(r'"(temperatureAir|temperatureFeelsLike)": ?\[(\d+)\]',
                    r'"\1":[-\2]', GM_NOW)
    GM_DAYS = re.sub(r'<temperature-value value="(\d+)"',
                     r'<temperature-value value="-\1"', GM_DAYS)


async def _gm_fetch(_client, url):
    """The real fixture through the real parser, so the Gismeteo tab in mock
    mode shows what the parser actually produces rather than something
    invented."""
    if MODE in ("degraded", "down"):
        raise RuntimeError("mock: Gismeteo unreachable")
    return GM_DAYS if url.rstrip("/").endswith("10-days") else GM_NOW


async def _om(_client, place):
    if MODE == "down":
        return None
    base = -14.0 if MODE == "winter" else 15.4
    return {
        "current": {"time": "2026-07-31T21:00", "temperature_2m": base,
                    "apparent_temperature": base - 1,
                    "relative_humidity_2m": 88, "surface_pressure": 993.0,
                    "wind_speed_10m": 1.2, "wind_direction_10m": 270,
                    "weather_code": 71 if MODE == "winter" else 0},
        "hourly": {
            "time": [f"2026-07-31T{h:02d}:00" for h in range(24)],
            "temperature_2m": [base + (h % 5) for h in range(24)],
            "weather_code": [3] * 24, "precipitation": [0.0] * 24,
            "precipitation_probability": [10] * 24},
        "daily": {
            "time": [f"2026-08-{d:02d}" for d in range(1, 11)],
            "temperature_2m_max": [base + 4 + d for d in range(10)],
            "temperature_2m_min": [base - 3 + d for d in range(10)],
            "weather_code": [61, 3, 0, 2, 71, 95, 3, 0, 1, 80],
            "precipitation_probability_max": [40, 10, 0, 20, 60, 80, 5, 0, 0, 55]},
    }


yandex_html.fetch_html = _fetch
gismeteo.fetch_html = _gm_fetch
openmeteo.fetch = _om
service.invalidate()

if __name__ == "__main__":
    import uvicorn

    from app.main import app

    port = int(os.environ.get("PORT", "8098"))
    print(f"mock [{MODE}] -> http://127.0.0.1:{port}/weather/")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
