"""End-to-end through the API, with the upstreams stubbed.

No network is required or wanted here: the container this was built in has no
outbound route to Yandex, and a test suite that needs one is a test suite that
fails on a train.
"""


import dataclasses
import datetime as dt
import gzip
import re
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import routing, service, sun
from app.main import app
from app.sources import gismeteo, openmeteo, yandex_html
from tests.test_extract import NOW_C, RECORDED

# The stub agrees with the fixture rather than with a number typed in July.
# `NOW_C` is read straight out of the recorded page; the 0.6 is the *gap*,
# which is what the divergence assertions are actually about.
OM_NOW = round(NOW_C - 0.6, 1)
STAMP = f"{RECORDED.isoformat()}T22:00"

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client_(request, monkeypatch):
    fix = request.path.parent / "fixtures"
    raw = (fix / "current.html").read_text(encoding="utf-8", errors="replace")
    day_page = (fix / "ya-day5.html").read_text(encoding="utf-8", errors="replace")

    # One clock for the app and the stubs, pinned to the day the fixtures
    # describe -- as `tests/mock_server.py` does through YW_TODAY. Unpinned,
    # `date.today()` here was the runner's date (UTC on GitHub) while the app
    # asks Moscow's, so the day tests failed every night from 21:00 to 24:00
    # UTC; and about six months after a recording, year inference reorders
    # the ten days and the byte budget moves with the calendar (Feb 2027).
    real_now = sun.local_now

    def pinned_now(tz: str) -> dt.datetime:
        return real_now(tz).replace(
            year=RECORDED.year, month=RECORDED.month, day=RECORDED.day)

    monkeypatch.setattr(sun, "local_now", pinned_now)
    monkeypatch.setattr(service, "local_now", pinned_now)

    async def fake_fetch(_client, url):
        m = re.search(r"/day-(\d+)", url)
        if not m:
            return raw
        # The recorded page describes 7 August 2026. The parser rejects a page
        # about a different day than the one requested -- correctly -- so the
        # stub restamps it, otherwise every test here would exercise that
        # rejection instead of the feature.
        want = RECORDED + dt.timedelta(days=int(m.group(1)))
        return day_page.replace("2026-08-07T", f"{want.isoformat()}T")

    async def fake_om(_client, _place):
        # Close enough to agree with the fixture's +16°, so the referee stays
        # quiet and we are testing the happy path rather than the alarm.
        return {
            "current": {"time": STAMP, "temperature_2m": OM_NOW,
                        "apparent_temperature": 15.0, "relative_humidity_2m": 88,
                        "surface_pressure": 993.0, "wind_speed_10m": 1.2,
                        "wind_direction_10m": 270, "weather_code": 0},
            "hourly": {"time": [STAMP], "temperature_2m": [OM_NOW],
                       "weather_code": [0], "precipitation": [0.0],
                       "precipitation_probability": [0]},
            "daily": {"time": [RECORDED.isoformat()], "temperature_2m_max": [NOW_C + 8],
                      "temperature_2m_min": [NOW_C - 2], "weather_code": [61],
                      "precipitation_probability_max": [40]},
        }

    async def no_gismeteo(_client, _url, **_kw):
        # **_kw so the stub keeps matching `fetch_html` as it grows keywords.
        # It silently stopped matching once already, and the failure was
        # invisible: the route search swallowed the TypeError as a fetch error
        # and the test still passed, for the wrong reason.
        raise RuntimeError("stubbed out")

    monkeypatch.setattr(yandex_html, "fetch_html", fake_fetch)
    monkeypatch.setattr(gismeteo, "fetch_html", no_gismeteo)
    monkeypatch.setattr(openmeteo, "fetch", fake_om)
    service.invalidate()
    return TestClient(app)


def with_debug_token(monkeypatch, token: str = "s3cret-for-tests") -> dict[str, str]:
    """Configure a debug token for one test and return the header that carries
    it. Settings are a frozen dataclass read at import, so the instance
    `app.main` holds is swapped for a copy rather than edited."""
    from app import main

    monkeypatch.setattr(main, "settings",
                        dataclasses.replace(main.settings, debug_token=token))
    return {"X-Debug-Token": token}


class TestWeatherEndpoint:
    def test_default_city(self, client_):
        r = client_.get("/weather/api/weather")
        assert r.status_code == 200
        d = r.json()
        assert d["place"]["name"] == "Йошкар-Ола"
        ya = d["sources"]["yandex"]
        assert ya["current"]["temp_c"] == NOW_C
        assert len(ya["daily"]) == 10
        assert len(ya["hourly"]) == 24

    def test_every_source_ships_in_one_payload(self, client_):
        """Switching sources must not cost a request -- and, more to the point,
        the three readings have to be from the same moment or comparing them
        means nothing."""
        d = client_.get("/weather/api/weather").json()
        assert set(d["sources"]) == {"yandex", "gismeteo", "openmeteo"}
        assert d["sources"]["yandex"]["available"] is True
        assert d["sources"]["openmeteo"]["available"] is True

    def test_yandex_is_selected_by_default(self, client_):
        assert client_.get("/weather/api/weather").json()["selected"] == "yandex"

    def test_unavailable_source_says_why(self, client_):
        gm = client_.get("/weather/api/weather").json()["sources"]["gismeteo"]
        assert gm["available"] is False
        assert gm["reason"]
        # `.get`, not `[...]`: empty fields are pruned from the wire format, so
        # "no current reading" is now an absent key rather than a null one.
        # Both are the same answer -- in JavaScript `undefined != null` is
        # false, which is the comparison every reader in app.js makes.
        assert gm.get("current") is None

    def test_provenance_is_reported_per_source(self, client_):
        d = client_.get("/weather/api/weather").json()
        assert d["sources"]["yandex"]["provenance"]["temp_c"] == 1
        assert d["sources"]["yandex"]["fallback_profile"] is False

    def test_divergence_is_recorded_but_decides_nothing(self, client_):
        """The two disagree by 0.6°. Both are served, both are
        selectable, and the delta is on the record for whoever is debugging."""
        d = client_.get("/weather/api/weather").json()
        assert d["health"]["divergence_c"]["yandex/openmeteo"] == pytest.approx(0.6)
        assert d["selected"] == "yandex"

    def test_lat_lon_addressing(self, client_):
        r = client_.get("/weather/api/weather?lat=56.63&lon=47.9")
        assert r.status_code == 200
        assert r.json()["sources"]["yandex"]["current"]["temp_c"] == NOW_C

    def test_a_gps_fix_gets_its_own_time_zone(self, client_, monkeypatch):
        """Every ad-hoc place used to be "Europe/Moscow": the client's «сейчас»
        and «сегодня» follow `place.tz`, so Novosibirsk was four hours out."""
        async def om(_c, _place):
            return {"timezone": "Asia/Novosibirsk", "utc_offset_seconds": 25200,
                    "current": {"time": "2026-07-31T22:00", "temperature_2m": 9.0}}

        monkeypatch.setattr(openmeteo, "fetch", om)
        d = client_.get("/weather/api/weather?lat=55.03&lon=82.92").json()
        assert d["place"]["tz"] == "Asia/Novosibirsk"

    def test_open_meteo_is_asked_to_resolve_the_zone(self):
        import asyncio

        from app import cities
        seen: dict = {}

        class Recorder:
            async def get(self, _url, params=None, timeout=None):
                seen.update(params)
                raise RuntimeError("offline")

        asyncio.run(openmeteo.fetch(Recorder(), cities.ad_hoc(55.03, 82.92)))
        assert seen["timezone"] == "auto"

    def test_coordinates_out_of_range_are_refused(self, client_):
        assert client_.get("/weather/api/weather?lat=999&lon=0").status_code == 400

    def test_unknown_city_is_a_404_not_a_silent_default(self, client_):
        assert client_.get("/weather/api/weather?city=atlantis").status_code == 404

    def test_gps_near_a_registry_city_uses_the_registry_entry(self, client_):
        """A fix near Yoshkar-Ola should use the registry entry, which has a
        verified slug -- a more reliable way to ask than raw coordinates."""
        d = client_.get("/weather/api/weather?lat=56.64&lon=47.90").json()
        assert d["place"]["slug"] == "yoshkar-ola"
        assert d["place"]["ad_hoc"] is False


class TestForceTakesTheToken:
    """`force=1` skips the cache, and the cache is what holds this app to one
    fetch per source per city per ten minutes, however many people are asking.
    Honoured for anyone, it let any stranger spend the server's upstream
    requests -- from the server's address, which is the one thing Gismeteo has
    already shown it will block (DECISIONS.md §7) -- as fast as they could send
    them.

    So it takes the debug token now. Without it the request is still answered,
    from the cache, exactly as if `force` had not been asked for.
    """

    @pytest.fixture
    def asked(self, client_, monkeypatch):
        """Every URL Yandex is asked for, so a test can tell a cache hit from
        a refetch without reading timestamps."""
        urls: list[str] = []
        inner = yandex_html.fetch_html

        async def counting(c, url, **kw):
            urls.append(url)
            return await inner(c, url, **kw)

        monkeypatch.setattr(yandex_html, "fetch_html", counting)
        return urls

    def test_a_stranger_is_answered_from_the_cache(self, client_, asked,
                                                   monkeypatch):
        with_debug_token(monkeypatch)
        assert client_.get("/weather/api/weather").status_code == 200
        before = len(asked)
        assert before, "the first request should have fetched upstream"
        for headers in ({}, {"X-Debug-Token": "a-good-guess"}):
            r = client_.get("/weather/api/weather?force=1", headers=headers)
            assert r.status_code == 200
        assert len(asked) == before, \
            "force=1 without the debug token went upstream anyway"

    def test_the_token_still_forces_a_refetch(self, client_, asked, monkeypatch):
        token = with_debug_token(monkeypatch)
        client_.get("/weather/api/weather")
        before = len(asked)
        client_.get("/weather/api/weather?force=1", headers=token)
        assert len(asked) > before

    def test_no_token_configured_means_nobody_has_one(self, client_, asked,
                                                      monkeypatch):
        """Unset is the default, and an empty header compared against an empty
        setting is equal -- so without an explicit check, every box that never
        configured a token would have handed `force` back to everyone."""
        empty = with_debug_token(monkeypatch, "")
        client_.get("/weather/api/weather")
        before = len(asked)
        client_.get("/weather/api/weather?force=1", headers=empty)
        assert len(asked) == before


class TestTheServersNotesAreForTheToken:
    """`detail` -- the URLs tried, the exceptions, the validator's verdicts and
    the route that reached Gismeteo, proxy and all -- rode in every payload to
    every phone, and to anyone who asked /api/health. Nothing in `static/`
    reads it. It goes to whoever holds the debug token now (DECISIONS.md §38),
    and everything the app, `make status` and the canary do read stays."""

    def test_a_stranger_gets_the_verdict_and_none_of_the_notes(self, client_):
        r = client_.get("/weather/api/weather")
        d = r.json()
        assert "detail" not in d["health"]
        assert [k for k, sv in d["sources"].items() if "detail" in sv] == []
        assert d["health"]["status"] in ("ok", "degraded")
        assert {"warnings", "age_s", "divergence_c"} <= set(d["health"])
        for sv in d["sources"].values():
            assert {"available", "provenance", "fallback_profile",
                    "dropped_fields", "warnings"} <= set(sv)
        assert d["sources"]["gismeteo"]["reason"]   # stubbed out, and says so
        assert r.headers["cache-control"] == "no-cache"

    def test_the_token_gets_the_notes_and_no_cache_keeps_them(self, client_,
                                                              monkeypatch):
        r = client_.get("/weather/api/weather", headers=with_debug_token(monkeypatch))
        d = r.json()
        assert "detail" in d["health"]
        assert all("detail" in sv for sv in d["sources"].values())
        assert d["sources"]["gismeteo"]["detail"]
        # A shared cache that kept this would hand it to the next stranger.
        assert r.headers["cache-control"] == "no-store"

    def test_a_proxy_never_reaches_a_stranger(self, client_, monkeypatch):
        """The finding this answers, end to end. Gismeteo reached through a
        proxy puts the proxy in `health.detail`, and every payload carried it
        to whoever asked. `_mask` always took the password out; the address
        stayed, because it is what a maintainer needs to see."""
        proxy = "http://scout:tiger@203.0.113.9:3128"
        monkeypatch.setitem(routing._sticky, "route",
                            ("https://meteofor.lv/ru", proxy))

        async def through_the_proxy(place, today=None):
            # Gismeteo's parser is not what is under test: any reading will do.
            got, _url = await yandex_html.load(None, place, today=today)
            return got, None

        monkeypatch.setattr(service, "fetch_gismeteo", through_the_proxy)
        stranger = client_.get("/weather/api/weather")
        assert stranger.json()["sources"]["gismeteo"]["available"] is True
        assert "203.0.113.9" not in stranger.text

        own = client_.get("/weather/api/weather",
                          headers=with_debug_token(monkeypatch))
        assert [x for x in own.json()["health"]["detail"]
                if x.startswith("gismeteo via")] == \
            ["gismeteo via https://meteofor.lv/ru via http://203.0.113.9:3128"]
        assert "tiger" not in own.text


class TestDegradation:
    def test_yandex_down_selects_the_next_available_source(
            self, request, monkeypatch):
        async def boom(_client, _url):
            raise RuntimeError("connection refused")

        async def fake_om(_client, _place):
            return {"current": {"time": STAMP,
                                "temperature_2m": OM_NOW, "weather_code": 0}}

        monkeypatch.setattr(yandex_html, "fetch_html", boom)
        monkeypatch.setattr(gismeteo, "fetch_html", boom)
        monkeypatch.setattr(openmeteo, "fetch", fake_om)
        service.invalidate()

        d = TestClient(app).get("/weather/api/weather").json()
        assert d["selected"] == "openmeteo"
        assert d["sources"]["openmeteo"]["current"]["temp_c"] == OM_NOW
        assert d["sources"]["yandex"]["available"] is False
        assert d["health"]["status"] == "degraded"

    def test_everything_down_with_no_cache_is_an_honest_503(self, monkeypatch):
        async def boom(*_a, **_k):
            raise RuntimeError("no route to host")

        async def no_om(_client, _place):
            return None

        monkeypatch.setattr(yandex_html, "fetch_html", boom)
        monkeypatch.setattr(gismeteo, "fetch_html", boom)
        monkeypatch.setattr(openmeteo, "fetch", no_om)
        service.invalidate()

        r = TestClient(app).get("/weather/api/weather")
        assert r.status_code == 503
        assert r.json()["health"]["status"] == "down"

    def test_wide_divergence_no_longer_overrides_the_selection(
            self, request, monkeypatch):
        """Deliberate behaviour change from the two-source design.

        Back when you could only see one number, a 28° disagreement caused the
        app to reject Yandex and silently substitute Open-Meteo. With three
        readings on screen that override is both unnecessary and the wrong
        shape: the app would be quietly discarding an explicit choice. Now the
        disagreement is visible on the tabs, recorded in health, and decides
        nothing.
        """
        raw = (request.path.parent / "fixtures" / "current.html").read_text(
            encoding="utf-8", errors="replace")

        async def fake_fetch(_c, _u):
            return raw

        async def boom(_c, _u):
            raise RuntimeError("stubbed out")

        async def cold_om(_c, _p):
            return {"current": {"time": STAMP,
                                "temperature_2m": -12.0, "weather_code": 0}}

        monkeypatch.setattr(yandex_html, "fetch_html", fake_fetch)
        monkeypatch.setattr(gismeteo, "fetch_html", boom)
        monkeypatch.setattr(openmeteo, "fetch", cold_om)
        service.invalidate()

        d = TestClient(app).get("/weather/api/weather").json()
        assert d["selected"] == "yandex"
        assert d["sources"]["yandex"]["current"]["temp_c"] == NOW_C
        assert d["sources"]["openmeteo"]["current"]["temp_c"] == -12.0
        # The gap, computed rather than typed: the point of this test is that
        # a wide divergence is *recorded and does not decide*, not that it is
        # any particular width.
        assert d["health"]["divergence_c"]["yandex/openmeteo"] == \
            pytest.approx(NOW_C - (-12.0))

    def test_a_wrong_city_is_not_rescued_by_asking_another_way(
            self, request, monkeypatch):
        """Kazan by slug comes back as Yoshkar-Ola and is rejected. Asking
        again by lat/lon until some page agrees is the plausible wrong fix
        (DECISIONS §12), and it used to serve Yoshkar-Ola under «Казань»."""
        fix = request.path.parent / "fixtures"
        by_slug = (fix / "current.html").read_text(encoding="utf-8", errors="replace")
        by_point = (fix / "latlon.html").read_text(encoding="utf-8", errors="replace")

        async def fetch(_c, url):
            return by_point if "?lat=" in url else by_slug

        async def boom(*_a, **_k):
            raise RuntimeError("stubbed out")

        async def no_om(_c, _p):
            return None

        monkeypatch.setattr(yandex_html, "fetch_html", fetch)
        monkeypatch.setattr(gismeteo, "fetch_html", boom)
        monkeypatch.setattr(openmeteo, "fetch", no_om)
        service.invalidate()
        ya = TestClient(app).get("/weather/api/weather?city=kazan").json()[
            "sources"]["yandex"]
        assert ya["available"] is False and ya["reason"] == "другой город"

    def test_one_unreadable_hour_label_does_not_500_the_app(
            self, request, monkeypatch):
        """«24:00» parses as an hour; the night-icon pass ran `dt.time(24, 0)`
        on every serve, over the cached payload, and took every source down
        with it (and /api/health, while there was one)."""
        raw = (request.path.parent / "fixtures" / "current.html").read_text(
            encoding="utf-8", errors="replace")
        odd = raw.replace("07:00: +9°", "24:00: +9°", 1)
        assert odd != raw

        async def fetch(_c, _u):
            return odd

        async def boom(*_a, **_k):
            raise RuntimeError("stubbed out")

        async def no_om(_c, _p):
            return None

        monkeypatch.setattr(yandex_html, "fetch_html", fetch)
        monkeypatch.setattr(gismeteo, "fetch_html", boom)
        monkeypatch.setattr(openmeteo, "fetch", no_om)
        service.invalidate()
        c = TestClient(app, raise_server_exceptions=False)
        assert c.get("/weather/api/weather").status_code == 200
        # And again, from the cache: the pass runs on every serve, not once.
        assert c.get("/weather/api/weather").status_code == 200

    def test_a_bug_in_one_sources_assembly_costs_one_tab(self, client_,
                                                          monkeypatch):
        def broken(*_a, **_k):
            raise ValueError("year 55841 is out of range")

        monkeypatch.setattr(service, "align_to_now", broken)
        # With the token, because the exception's text is in `detail`.
        d = client_.get("/weather/api/weather",
                        headers=with_debug_token(monkeypatch)).json()
        assert d["sources"]["yandex"]["available"] is False
        assert d["sources"]["yandex"]["reason"] == "не прочиталось"
        assert any("55841" in x for x in d["sources"]["yandex"]["detail"])

    def test_stale_cache_beats_nothing(self, request, monkeypatch):
        raw = (request.path.parent / "fixtures" / "current.html").read_text(
            encoding="utf-8", errors="replace")

        async def ok(_c, _u):
            return raw

        async def no_om(_c, _p):
            return None

        async def boom0(_c, _u):
            raise RuntimeError("stubbed out")

        monkeypatch.setattr(yandex_html, "fetch_html", ok)
        monkeypatch.setattr(gismeteo, "fetch_html", boom0)
        monkeypatch.setattr(openmeteo, "fetch", no_om)
        service.invalidate()
        c = TestClient(app)
        first = c.get("/weather/api/weather").json()
        assert first["sources"]["yandex"]["current"]["temp_c"] == NOW_C

        async def boom(*_a, **_k):
            raise RuntimeError("gone")

        monkeypatch.setattr(yandex_html, "fetch_html", boom)
        # With the token: an anonymous `force` is answered from the cache now
        # (TestForceTakesTheToken), which would never reach the broken fetch.
        token = with_debug_token(monkeypatch)
        d = c.get("/weather/api/weather?force=1", headers=token).json()
        assert d["sources"]["yandex"]["current"]["temp_c"] == NOW_C
        assert d["health"]["status"] == "stale"
        assert any("устарели" in w for w in d["health"]["warnings"])


class TestStrangersCannotSpendTheServersAddress:
    """GPS fixes and searches are keyed by coordinates and free text, so each
    new one is a fresh round of upstream requests from this server's address.
    Unbudgeted, one client decided how often that happened."""

    @pytest.fixture
    def rounds(self, client_, monkeypatch):
        seen: list[str] = []

        async def om(_c, place):
            seen.append(place.slug)
            return None

        monkeypatch.setattr(openmeteo, "fetch", om)
        monkeypatch.setattr(service, "cold", service.Budget(per_hour=0, burst=3))
        return seen

    def test_new_coordinates_stop_going_upstream_past_the_budget(
            self, client_, rounds):
        for i in range(10):
            r = client_.get(f"/weather/api/weather?lat={-40 + i}&lon=-20")
            assert r.status_code in (200, 503)
        assert len(rounds) == 3
        assert r.json()["sources"]["yandex"]["reason"] == "слишком часто"

    def test_the_registry_is_never_rationed(self, client_, rounds):
        for i in range(5):
            client_.get(f"/weather/api/weather?lat={-40 + i}&lon=-20")
        assert client_.get("/weather/api/weather?city=yoshkar-ola").status_code == 200

    def test_an_outage_is_remembered_rather_than_refetched(self, monkeypatch):
        asked: list[str] = []

        async def refused(_c, url, **_kw):
            asked.append(url)
            raise RuntimeError("refused")

        async def no_om(_c, _p):
            return None

        monkeypatch.setattr(yandex_html, "fetch_html", refused)
        monkeypatch.setattr(gismeteo, "fetch_html", refused)
        monkeypatch.setattr(openmeteo, "fetch", no_om)
        service.invalidate()
        c = TestClient(app)
        assert c.get("/weather/api/weather").status_code == 503
        once = len(asked)
        for _ in range(5):
            assert c.get("/weather/api/weather").status_code == 503
        assert len(asked) == once


class TestSurfaces:
    def test_cities(self, client_):
        d = client_.get("/weather/api/cities").json()
        assert d["default"] == "yoshkar-ola"
        assert any(c["name"] == "Йошкар-Ола" for c in d["cities"])

    def test_health_is_retired_and_says_where_to_look(self, client_, monkeypatch):
        """Gone, not missing (DECISIONS.md §38). A 404 there is also what a
        wrong BASE_PATH or a proxy that never reached the app would answer;
        only the app can say 410, so whatever still asks learns that the site
        is up and where the answer moved. Saying so costs no weather."""
        from app import main

        async def no_weather(*_a, **_k):
            raise AssertionError("the retired /api/health went to the sources")

        monkeypatch.setattr(main, "get_weather", no_weather)
        r = client_.get("/weather/api/health")
        assert r.status_code == 410
        assert r.json() == {"retired": "2026-10-02",
                            "build": "/weather/api/version",
                            "sources": "/weather/api/weather"}

    def test_manifest_scope_follows_base_path(self, client_):
        m = client_.get("/weather/manifest.webmanifest").json()
        assert m["scope"] == "/weather/" and m["start_url"] == "/weather/"

    def test_service_worker_is_allowed_the_whole_subsection(self, client_):
        r = client_.get("/weather/sw.js")
        assert r.headers["Service-Worker-Allowed"] == "/weather/"

    def test_debug_routes_404_without_a_token(self, client_):
        """404, not 403 -- their existence is not advertised."""
        assert client_.get("/weather/api/debug/selftest").status_code == 404

    def test_debug_routes_take_the_token_and_nothing_else(self, client_,
                                                          monkeypatch):
        token = with_debug_token(monkeypatch)
        flush = "/weather/api/debug/flush"
        assert client_.post(flush).status_code == 403
        assert client_.post(flush, headers={"X-Debug-Token": "x"}).status_code == 403
        assert client_.post(flush, headers=token).json() == {"flushed": "all"}

    def test_an_empty_base_path_serves_a_bare_subdomain(self):
        """Documented as `BASE_PATH=""`. It used to mean "/weather" (an empty
        value read as unset), and "/" -- the only way to get an empty base --
        put /healthz behind the static mount, failing the image's health
        check."""
        import os
        import subprocess
        import sys

        code = ("from fastapi.testclient import TestClient\n"
                "from app.main import app\n"
                "c = TestClient(app)\n"
                "print(*(c.get(p).status_code for p in "
                "('/healthz', '/api/version', '/', '/sw.js')))\n")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                             env={**os.environ, "BASE_PATH": ""},
                             capture_output=True, text=True, timeout=60)
        assert out.stdout.split()[-4:] == ["200"] * 4, out.stderr[-500:]

    def test_root_redirects_into_the_subsection(self, client_):
        r = client_.get("/", follow_redirects=False)
        assert r.status_code in (307, 308)
        assert r.headers["location"] == "/weather/"


class TestWhatTheServerAsks:
    """The server keeps a new image only when three questions get the right
    answer, and it asks them from the owner's infrastructure repository, where
    nothing in this one can see them. A change that stopped answering one
    would pass every other test here, ship, and be rolled back by the server
    on every deploy -- quietly, since the old image goes on serving. So the
    answers are pinned here, each beside who asks."""

    def test_the_page_title_is_exactly_what_the_deploy_check_greps_for(
            self, client_):
        """The deploy check fetches https://mureev.com/weather/ and keeps the
        new image only if the body contains the literal `<title>Погода</title>`.
        Translate the title here, decorate it or merely reformat it --
        `<title>Погода · Weather</title>`, an attribute, a line break -- and
        every deploy is rolled back. The English interface retitles the
        page from app.js, in the DOM, after the check has read the body; that
        is not what this pins. Bytes, because a grep reads bytes."""
        r = client_.get("/weather/")
        assert r.status_code == 200
        head = r.content.split(b"</head>", 1)[0]
        assert re.findall(rb"<title\b.*?</title>", head, re.S) == \
            ["<title>Погода</title>".encode()]

    def test_version_answers_with_the_build(self, client_):
        """The deploy check's second question: `/weather/api/version` must
        answer 2xx or 3xx. It is also how anyone tells which build is live,
        and CI asks it for the commit it just built."""
        r = client_.get("/weather/api/version")
        assert r.status_code == 200
        assert set(r.json()) == {"build", "built_at", "shell"}

    def test_healthz_says_only_that_the_process_is_up(self, client_):
        """The image's own HEALTHCHECK, which the server reads as the third
        answer. Nothing about the sources: a probe that asked them would
        restart the container whenever the weather sites have a bad hour."""
        r = client_.get("/healthz")
        assert (r.status_code, r.json()) == (200, {"ok": True})


class TestTheCanaryReadsWhatTheAppServes:
    """`tools/canary.py` is the one thing that reads the live site on a
    schedule, and a key it asks for that the payload does not carry is a check
    that never runs and never says so. That happened: it asked `/api/health`
    for `dropped_fields`, which that endpoint called `dropped`. So these feed
    it the payload the real app builds, never a dict typed to match the
    canary's own expectations."""

    @pytest.fixture
    def canary(self, client_, monkeypatch):
        from tools import canary

        def fetch(url, timeout):
            r = client_.get(url.removeprefix("http://testserver"))
            if r.status_code >= 400:
                raise urllib.error.HTTPError(url, r.status_code, r.reason_phrase,
                                             r.headers, None)
            return r.json()

        monkeypatch.setattr(canary, "fetch", fetch)
        return lambda *args: canary.main(["--site", "http://testserver/weather",
                                          *args])

    def test_a_calm_day_passes_and_a_missing_source_does_not(self, canary):
        # Gismeteo is stubbed out here, as it is refused on some boxes.
        assert canary("--allow-missing", "gismeteo") == 0
        assert canary() == 1

    def test_a_dropped_field_fails_it(self, canary, monkeypatch):
        """Dropped by the validator, not typed into a payload: a humidity of
        743 fails its range contract on the way through the real assembly."""
        calm = openmeteo.fetch

        async def soaked(c, place):
            raw = await calm(c, place)
            raw["current"]["relative_humidity_2m"] = 743
            return raw

        monkeypatch.setattr(openmeteo, "fetch", soaked)
        assert canary("--allow-missing", "gismeteo") == 1

    def test_a_stale_payload_is_not_read_as_todays(self, canary, client_,
                                                   monkeypatch):
        """With every source failing, the app serves its last good payload --
        with 200, because a phone should still see it, and with the provenance
        of the fetch that worked. Read as today's, a morning on which nothing
        answers would pass. It is exit 2, as the 503 from /api/health was."""
        assert client_.get("/weather/api/weather").status_code == 200

        async def gone(*_a, **_k):
            raise RuntimeError("gone")

        async def no_om(_c, _p):
            return None

        monkeypatch.setattr(yandex_html, "fetch_html", gone)
        monkeypatch.setattr(openmeteo, "fetch", no_om)
        # Ten minutes later, as far as the cache is concerned.
        monkeypatch.setattr(service._cache, "get_fresh", lambda _k: None)
        r = client_.get("/weather/api/weather")
        assert (r.status_code, r.json()["health"]["status"]) == (200, "stale")
        assert canary("--allow-missing", "gismeteo") == 2


class TestSecurityHeaders:
    def test_csp_forbids_every_third_party(self, client_):
        csp = client_.get("/weather/api/cities").headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "connect-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        # No host allowlist anywhere: if a CDN is not named, it cannot load.
        assert "http://" not in csp and "https://" not in csp

    def test_geolocation_is_permitted_only_to_us(self, client_):
        pp = client_.get("/weather/api/cities").headers["permissions-policy"]
        assert "geolocation=(self)" in pp

    def test_no_referrer(self, client_):
        h = client_.get("/weather/api/cities").headers
        assert h["referrer-policy"] == "no-referrer"


class TestFrontEndHygiene:
    """The HTML is a security surface. These assertions are cheap and the
    failure they prevent -- a 'quick' CDN import added months from now -- is
    silent."""

    def test_no_connection_hints(self, request):
        html = (request.path.parent.parent / "static" / "index.html").read_text(
            encoding="utf-8")
        for hint in ('rel="preconnect"', 'rel="dns-prefetch"', 'rel="preload"'):
            assert hint not in html

    def test_no_cross_origin_urls(self, request):
        html = (request.path.parent.parent / "static" / "index.html").read_text(
            encoding="utf-8")
        import re
        for m in re.finditer(r'(?:src|href)="(https?://[^"]+)"', html):
            pytest.fail(f"third-party subresource in index.html: {m.group(1)}")

    def test_service_worker_blocks_cross_origin(self, request):
        sw = (request.path.parent.parent / "static" / "sw.js").read_text(
            encoding="utf-8")
        assert "url.origin !== self.location.origin" in sw
        assert "403" in sw


class TestTheDayEndpoint:
    """`/api/day` is the one request this app makes because somebody tapped
    something. Everything about it is shaped by that being optional."""

    @staticmethod
    def when(days: int) -> str:
        return (RECORDED + dt.timedelta(days=days)).isoformat()

    def test_it_returns_the_day_that_was_asked_for(self, client_):
        want = self.when(3)
        r = client_.get(f"/weather/api/day?date={want}&city=yoshkar-ola")
        assert r.status_code == 200
        got = r.json()
        assert got["source"] == "yandex"
        assert got["day"]["date"] == want

    def test_it_carries_eight_columns_with_gusts(self, client_):
        d = client_.get(f"/weather/api/day?date={self.when(2)}").json()["day"]
        assert len(d["hours"]) == 8
        assert all(h["wind_ms"] is not None for h in d["hours"])
        assert any(h.get("wind_gust_ms") for h in d["hours"])

    def test_a_day_with_no_page_is_204_and_not_an_error(self, client_):
        """A GPS fix has no addressable page and a date past the tenth has no
        page at all. Neither is a failure -- it is a question with no answer,
        and the screen carries on with what the main payload gave it."""
        assert client_.get(
            f"/weather/api/day?date={self.when(40)}").status_code == 204

    def test_a_day_with_no_page_costs_nothing(self, client_, monkeypatch):
        """No page means no lock and no client: building a client loads the CA
        bundle on the event loop, and a flood of these 204s used to slow every
        other request by two orders of magnitude."""
        built: list[int] = []
        monkeypatch.setattr(service, "client", lambda *a, **k: built.append(1))
        r = client_.get("/weather/api/day?city=moscow&date=2001-01-01")
        assert r.status_code == 204 and not built

    def test_a_refused_day_is_not_asked_for_again_for_ten_minutes(self, client_,
                                                                   monkeypatch):
        """Registry cities never draw on the strangers' budget (§37), and this
        endpoint multiplies each of them by ten dates. With a minute's memory
        of a refusal, an outage could be retried sixty times a minute through
        here alone -- six cities, ten days -- against a host already refusing
        this server. Ten minutes makes it six, and the screen loses nothing:
        the day is drawn from the main payload either way (§25)."""
        asked: list[int] = []

        async def refused(*a, **k):
            asked.append(1)
            raise RuntimeError("refused")

        monkeypatch.setattr(service.yandex_day, "load", refused)
        want = self.when(4)
        url = f"/weather/api/day?city=kazan&date={want}"
        key = f"kazan|{want}"
        service._days.drop(key)
        try:
            assert client_.get(url).status_code == 204
            service._days_missing._peek(key).stored_at -= 9 * 60
            assert client_.get(url).status_code == 204
            assert len(asked) == 1, "a refused day was asked for again within ten minutes"
            service._days_missing._peek(key).stored_at -= 2 * 60
            client_.get(url)
            assert len(asked) == 2, "a refused day was never asked for again"
        finally:
            service._days_missing.drop(key)

    def test_a_malformed_date_is_refused(self, client_):
        assert client_.get("/weather/api/day?date=tuesday").status_code == 400

    def test_it_is_not_in_the_cold_load(self, client_):
        """The whole justification for fetching on demand is that nothing
        waits for it. If this ever became part of the first paint, the ten
        requests it replaced would have to come back."""
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        boot = js[js.index("function boot()"):]
        assert "api/day" not in boot, \
            "the day detail is being fetched during boot rather than on tap"


class TestItIsCheapToLoad:
    """Bytes on the wire, as a budget rather than a hope.

    A weather app is opened for four seconds on a phone that is often on a
    train. The whole of it -- shell, script, service worker, first payload --
    should arrive in less than a photograph.

    These are regression guards, not aspirations. Every number here was
    measured, and the budgets sit just above the measurement, so the test that
    fails is the one where somebody adds a charting library.
    """

    SHELL = ("index.html", "app.js", "sw.js")

    @staticmethod
    def wire_bytes(response) -> int:
        """What actually crossed the network.

        Not `len(response.content)`: the test client decompresses gzip
        transparently, so reading the body measures the file on disk and the
        budget silently becomes three times what you wrote. The first version
        of this test reported 82 kB for a 26 kB load and I nearly raised the
        limit to match. `Content-Length` is set by the compression middleware
        after compressing, so it is the real figure -- when there is one.

        **Past 64 KiB there is not.** Starlette sends a file in 64 KiB chunks,
        and given more than one its gzip middleware streams the result with no
        length at all. `app.js` crossed that line and this raised `KeyError`
        where a size belonged. The middleware compresses at level 6 without a
        flush, so compressing the body again at level 6 is the same byte count;
        the test below holds that wherever a length is still stated.
        """
        n = response.headers.get("content-length")
        return int(n) if n else len(gzip.compress(response.content, compresslevel=6))

    def test_recompressing_matches_a_stated_length(self, client_):
        for name in ("sw.js", "api/weather"):
            r = client_.get(f"/weather/{name}", headers={"Accept-Encoding": "gzip"})
            stated = int(r.headers["content-length"])
            assert stated == len(gzip.compress(r.content, compresslevel=6)), name

    def test_the_api_is_compressed(self, client_):
        """22.8 kB of very repetitive JSON compresses to 2.5 kB. Nothing in
        front of the app was doing this: the nginx location block for /weather/
        has no gzip directive, so every byte went out raw."""
        r = client_.get("/weather/api/weather", headers={"Accept-Encoding": "gzip"})
        assert r.status_code == 200
        assert r.headers.get("content-encoding") == "gzip"

    def test_the_shell_is_compressed(self, client_):
        for name in self.SHELL:
            r = client_.get(f"/weather/{name}", headers={"Accept-Encoding": "gzip"})
            assert r.headers.get("content-encoding") == "gzip", name
            assert self.wire_bytes(r) < len(r.content), name

    def test_it_varies_on_accept_encoding(self, client_):
        """Without `Vary`, a shared cache can hand a gzipped body to a client
        that never asked for one. There is a CDN-shaped hole here even though
        there is no CDN today."""
        r = client_.get("/weather/app.js", headers={"Accept-Encoding": "gzip"})
        assert "accept-encoding" in r.headers.get("vary", "").lower()

    def test_a_client_that_cannot_decompress_still_gets_the_file(self, client_):
        r = client_.get("/weather/app.js", headers={"Accept-Encoding": "identity"})
        assert r.status_code == 200 and "content-encoding" not in r.headers

    def test_a_cold_load_fits_in_a_budget(self, client_):
        """Shell plus first payload, compressed, as a phone would fetch it.

        Raised once, from 32 kB, and worth recording what bought it. Three
        things landed together: the day-detail screen and the navigation it
        needed (+3.7 kB of `app.js`), its stylesheet (+1.3 kB), and Open-Meteo's
        hourly series going from one day to ten (+3.2 kB of payload). The last
        of those is the whole reason any day of the forecast can be opened, and
        it costs nothing upstream -- the request was already being made and the
        answer thrown away.

        A note on the other two, because it is a real cost of this codebase's
        house style: a good deal of `app.js` is prose. Comments explaining the
        bug behind a line are the most valuable text in this repository and
        they are also bytes on a phone. That trade is made deliberately and
        this is where the bill arrives. Stripping them at serve time was
        considered and rejected: a comment remover that mangles one regex
        literal is a silent, catastrophic failure, and this is 41 kB fetched
        once and then held by the service worker for good.

        **Raised twice in one sitting, which is the pattern this test exists to
        resist**, so the second one is worth pinning down. It bought parts of
        day for all ten days from Gismeteo -- forty more objects per payload --
        and those have to be in the *main* payload rather than fetched on
        demand, because the day screen's whole design is that it works before
        the network answers and offline. That is the trade, stated: an extra
        2 kB on every cold load so that opening a day never waits.

        What should refuse a third raise: anything that is not paid for by
        something visible offline. Growth in `app.js` for a feature that only
        works online belongs behind a fetch, not in the shell.

        **Raised a third time anyway, to 48.5 kB, and it is worth being honest
        that this one is decoration.** The weather now moves differently for
        each of eighteen conditions instead of three, day and night apart. It
        is paid for by the offline rule -- the sky is stylesheet and a lookup
        table, so it works with the radio off and it is what the app looks like
        every time it is opened. But it buys no information, and if a fourth
        raise is ever wanted for something that does, this is the 3 kB to take
        it out of.

        **Raised a fourth time, to 55.8 kB, for two things the owner asked for
        on the same night** (2026-10-02), each with its own entry. The English
        interface (§36) is about 3.7 kB: every string now exists in two
        languages, plus the English readings of what the sources say. The
        install banner (§35) is about 2.5 kB, most of it a phone drawn in CSS
        rather than shipped as an image. The sky above was *not* taken out to
        pay for them: neither is information about the weather, so the rule
        written here does not apply, and the owner, not this test, decides
        whether the sky is worth its bytes. Both name what to give back first
        if a fifth raise is refused -- the phone drawing, then the sky.

        **Raised a fifth time, to 64 kB, and this one is room rather than a
        feature** (2026-10-02, the owner's call, DECISIONS.md §42). The fourth
        left 43 bytes between the shell and the budget, so the next change to
        the sky would have had to stop and ask. 64 kB still fails on what this
        test exists for -- a charting library, a web font, a framework -- and
        leaves the sky room to move. The uncompressed budget went the same day:
        it measured the comments more than the code, and the comments are the
        house style (§24).
        """
        total = 0
        for path in (*self.SHELL, "api/weather"):
            r = client_.get(f"/weather/{path}", headers={"Accept-Encoding": "gzip"})
            total += self.wire_bytes(r)
        assert total < 64_000, (
            f"a cold load is now {total/1000:.1f} kB compressed; it was 41 kB. "
            f"Something sizeable joined the shell -- check before raising this.")

    def test_static_assets_say_how_long_they_may_be_kept(self, client_):
        """Unhashed shell files must revalidate -- a cached copy that never
        checks is a device pinned to an old build for ever, which is the bug
        the derived service-worker version exists to prevent. Icons are content
        and may be kept."""
        for name in self.SHELL:
            assert client_.get(f"/weather/{name}").headers["cache-control"] == "no-cache"
        icon = client_.get("/weather/icons/icon-192.png")
        assert "max-age=" in icon.headers["cache-control"]

    def test_nothing_in_the_shell_is_fetched_from_elsewhere(self, client_):
        """Restated here as a *performance* claim rather than a privacy one:
        every extra origin is a DNS lookup, a TCP handshake and a TLS
        negotiation before a single byte arrives."""
        html = client_.get("/weather/index.html").text
        assert "http://" not in html.replace("http://www.w3.org", "")


class TestTheLaunchIsOneContinuousColour:
    """Tap to first paint, with nothing flashing in between.

    Three separate things decide what the screen shows in the first half
    second, each read by a different consumer at a different moment:

      manifest background_color   iOS, to draw the standalone launch screen
      the critical <style>        the browser, for the first paint
      --sky1's default            the browser again, once 30 kB of CSS is read

    They were #0b1220, nothing, and #0d1630. So the splash was near-black, the
    gap before the stylesheet parsed was the WebView's own white, and the app
    then arrived in a third colour. Three transitions where there should be
    none.

    They are written in three places because nothing can read all three, so
    this asserts they agree instead.
    """

    @staticmethod
    def _critical_colour(html: str) -> str:
        import re
        head = html.split("</style>", 1)[0]
        assert "html{background:" in head, \
            "the critical style block is gone -- the first paint is white again"
        return re.search(r"html\{background:(#[0-9a-f]{6})", head).group(1)

    def test_the_critical_block_comes_before_the_stylesheet(self, client_):
        """It exists to be parsed first. Anywhere else and it is decoration."""
        html = client_.get("/weather/index.html").text
        assert html.index("html{background:") < html.index("Layout priorities")

    def test_the_splash_and_the_first_paint_are_the_same_colour(self, client_):
        html = client_.get("/weather/index.html").text
        manifest = client_.get("/weather/manifest.webmanifest").json()
        assert manifest["background_color"] == self._critical_colour(html)

    def test_the_first_paint_matches_the_sky_it_becomes(self, client_):
        """`--sky1` is the top of the gradient the app settles on. If the first
        paint is a different colour there is a step change on load, which is
        the flash this all exists to remove."""
        import re
        html = client_.get("/weather/index.html").text
        dark = re.search(r":root\{--sky1:(#[0-9a-f]{6})", html).group(1)
        assert self._critical_colour(html) == dark

    def test_light_mode_launches_on_the_same_colour(self, client_):
        """One sky for both appearances (DECISIONS.md §40), so one first paint.

        Light mode used to have a sky of its own and a first paint to match --
        which the manifest could not: it carries one `background_color`, so a
        light-mode launch went from a navy splash to a paler sky, the one step
        §19 recorded as unfixable. It is fixed by there being nothing to
        match. This fails if a light-scheme rule starts moving the sky again,
        anywhere in the stylesheet, because then the step comes back."""
        import re
        html = client_.get("/weather/index.html").text
        head = html.split("</style>", 1)[0]
        assert "prefers-color-scheme" not in head, \
            "the critical block has a light-mode colour again"
        for m in re.finditer(r"@media \(prefers-color-scheme: ?light\)\{", html):
            depth, i = 1, m.end()
            while depth:
                depth += {"{": 1, "}": -1}.get(html[i], 0)
                i += 1
            assert "--sky" not in html[m.end():i], \
                "a light-scheme rule moves the sky; the launch steps again"

    def test_the_theme_colour_agrees_too(self, client_):
        html = client_.get("/weather/index.html").text
        manifest = client_.get("/weather/manifest.webmanifest").json()
        assert manifest["theme_color"] == manifest["background_color"]
        assert f'content="{manifest["theme_color"]}" id="theme-color"' in html

    def test_there_is_a_skeleton_shaped_like_the_app(self, client_):
        """Not a dimmed full stop. On a cold install this is the app for a
        second or two, and it should look like the app."""
        html = client_.get("/weather/index.html").text
        assert 'class="boot"' in html
        assert html.count("<i class=") >= 5

    def test_the_skeleton_invents_no_data(self, client_):
        """Same rule as everywhere else here: never show a plausible number
        that is not real. Furniture is honest; a fake temperature is not."""
        import re
        boot = re.search(r'<div class="boot".*?</div>', client_.get(
            "/weather/index.html").text, re.S).group(0)
        assert not re.search(r"[0-9]", boot)

    def test_the_app_fades_in_rather_than_snapping(self, client_):
        html = client_.get("/weather/index.html").text
        assert "materialise" in html
        assert "prefers-reduced-motion" in html

    def test_the_fade_cannot_leave_the_page_blank(self, client_):
        """`both` fill mode, and no JavaScript involved. A fade-in gated on a
        script is a blank page for anyone whose script fails -- the classic way
        to make a site worse while trying to make it feel faster."""
        html = client_.get("/weather/index.html").text
        assert "animation:materialise .22s ease-out both" in html
        assert "to{opacity:1" in html

    def test_the_fade_is_not_on_the_element_that_rerenders(self, client_):
        """`#content` is replaced on every refresh; an animation there would
        replay every ten minutes, which is a tic rather than a transition."""
        import re
        html = client_.get("/weather/index.html").text
        content_rule = re.search(r"#content\{[^}]*\}", html)
        assert not content_rule or "animation" not in content_rule.group(0)

    def test_the_loading_state_is_announced(self, client_):
        """The skeleton is aria-hidden, so something has to speak."""
        html = client_.get("/weather/index.html").text
        assert 'class="sr"' in html and "Загружаем" in html


class TestTheIconAndTheAppAreOneDrawing:
    """The home-screen icon is the forecast's own `i-partly` glyph on the clear
    day's sky, rendered large and downscaled; then the app was redrawn from the
    icon -- the glyphs took its cloud, the clear day its gradient, and the
    install banner's drawing of it its glow (DECISIONS.md §44).

    A PNG and a stylesheet cannot read each other, so as with the launch
    colour above, this asserts they agree and says which one would have to
    move. Recolour the glyph and the icon must be rendered again; render the
    icon in another sky and the clear day goes with it.
    """

    ICONS = ("icon-512.png", "icon-192.png", "apple-touch-icon.png",
             "icon-maskable.png")

    @staticmethod
    def _hex(rgb) -> str:
        return "#" + "".join(f"{v:02x}" for v in rgb)

    def _icons(self, client_):
        Image = pytest.importorskip("PIL.Image", reason="pillow not installed")
        import io
        for name in self.ICONS:
            r = client_.get(f"/weather/icons/{name}")
            assert r.status_code == 200, name
            yield name, Image.open(io.BytesIO(r.content)).convert("RGB")

    def test_the_icon_wears_the_glyphs_two_colours(self, client_):
        """The two flat areas of the icon -- the cloud, then the sun -- are its
        two commonest colours at every size, since a downscaled flat area keeps
        its colour inside the edge. They are the symbol's two fills."""
        html = client_.get("/weather/index.html").text
        glyph = re.search(r'<symbol id="i-partly".*?</symbol>', html).group(0)
        want = set(re.findall(r'fill="(#[0-9a-f]{6})"', glyph))
        assert len(want) == 2, f"i-partly is no longer a sun and a cloud: {want}"
        for name, im in self._icons(client_):
            top = sorted(im.getcolors(1 << 24), reverse=True)[:2]
            got = {self._hex(c) for _, c in top}
            assert got == want, (
                f"{name} is drawn in {sorted(got)} and the glyph in "
                f"{sorted(want)}: the icon and the forecast's glyph have parted")

    def test_a_clear_day_is_the_icons_sky(self, client_):
        """Down the icon's right edge, the side farthest from its glow, the
        pixels are the gradient itself: its first colour in the top corner,
        and 62% of the way down the colour the clear day's middle stop is
        meant to be -- the point the icon's gradient passes on its way to the
        launch colour. A row is one pixel of a gradient that spans the tile,
        so that one is allowed a level either way for rounding. The banner's
        drawing of the icon starts where both do."""
        html = client_.get("/weather/index.html").text
        sky1, sky2 = re.search(
            r':root\[data-sky="clear-day"\]\s*\{--sky1:(#[0-9a-f]{6});'
            r'--sky2:(#[0-9a-f]{6})', html).groups()
        for name, im in self._icons(client_):
            corner = self._hex(im.getpixel((im.width - 1, 0)))
            assert corner == sky1, (
                f"{name} begins at {corner}, the clear day at {sky1}")
            mid = im.getpixel((im.width - 1, round(.62 * (im.height - 1))))
            want = tuple(int(sky2[i:i + 2], 16) for i in (1, 3, 5))
            assert all(abs(a - b) <= 1 for a, b in zip(mid, want, strict=True)), (
                f"{name} is {self._hex(mid)} 62% of the way down, and the clear "
                f"day's middle stop {sky2}: the icon's gradient has moved")
        banner = re.search(r"\.a2hs \.g b\{[^}]*\}", html).group(0)
        assert f"linear-gradient({sky1}," in banner, \
            "the banner draws the icon on a sky the icon no longer has"


class TestTwoLanguages:
    """The English interface, from the server's side: names spelled for
    English readers, and nothing about the reader's language sent upstream."""

    def test_the_built_in_cities_carry_their_english_names(self, client_):
        got = {c["slug"]: c["name_en"]
               for c in client_.get("/weather/api/cities").json()["cities"]}
        assert got["moscow"] == "Moscow"            # not the transliterated Moskva
        assert got["saint-petersburg"] == "Saint Petersburg"
        assert got["yoshkar-ola"] == "Yoshkar-Ola"

    def test_the_forecast_says_where_it_is_in_both(self, client_):
        place = client_.get("/weather/api/weather").json()["place"]
        assert (place["name"], place["name_en"]) == ("Йошкар-Ола", "Yoshkar-Ola")

    def test_a_gps_fix_is_named_in_latin_letters_too(self, client_):
        place = client_.get("/weather/api/weather?lat=55.30&lon=48.10").json()["place"]
        assert place["name_en"] and not re.search("[А-Яа-я]", place["name_en"])

    def test_a_search_asks_in_both_languages_whoever_is_asking(
            self, client_, monkeypatch):
        """Asking only in the reader's language would tell the geocoder what
        it is -- an Accept-Language header by another name (invariant 5). So
        every search asks twice, identically but for `language`, and the two
        answers are joined by the geocoder's own id."""
        from app.sources import geocode

        asked = []

        class Answer:
            def __init__(self, rows):
                self.rows = rows

            def raise_for_status(self):
                pass

            def json(self):
                return {"results": self.rows}

        async def fake_get(self, url, params=None, **_kw):
            asked.append(dict(params))
            name, admin, country = (("Париж", "Иль-де-Франс", "Франция")
                                    if params["language"] == "ru"
                                    else ("Paris", "Île-de-France", "France"))
            return Answer([{"id": 2988507, "name": name, "admin1": admin,
                            "country": country, "country_code": "FR",
                            "latitude": 48.85, "longitude": 2.35,
                            "timezone": "Europe/Paris", "population": 2_100_000}])

        monkeypatch.setattr(geocode._cache, "get_fresh", lambda _k: None)
        monkeypatch.setattr(geocode._cache, "get_stale", lambda _k: None)
        import httpx2
        monkeypatch.setattr(httpx2.AsyncClient, "get", fake_get)
        hit = client_.get("/weather/api/search?q=paris",
                          headers={"Accept-Language": "en-US"}).json()["results"][0]
        assert (hit["name"], hit["name_en"]) == ("Париж", "Paris")
        assert hit["subtitle_en"] == "Île-de-France, France"
        assert sorted(a["language"] for a in asked) == ["en", "ru"]
        assert len({tuple(sorted((k, v) for k, v in a.items() if k != "language"))
                    for a in asked}) == 1

    def test_the_installed_name_follows_the_page_not_a_header(self, client_):
        assert client_.get("/weather/manifest.webmanifest?lang=en").json()["name"] \
            == "Weather"
        assert client_.get("/weather/manifest.webmanifest",
                           headers={"Accept-Language": "en"}).json()["name"] == "Погода"
