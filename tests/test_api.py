"""End-to-end through the API, with the upstreams stubbed.

No network is required or wanted here: the container this was built in has no
outbound route to Yandex, and a test suite that needs one is a test suite that
fails on a train.
"""


import pytest
from fastapi.testclient import TestClient

from app import service
from app.main import app
from app.sources import gismeteo, openmeteo, yandex_html


@pytest.fixture
def client_(request, monkeypatch):
    raw = (request.path.parent / "fixtures" / "current.html").read_text(
        encoding="utf-8", errors="replace")

    async def fake_fetch(_client, url):
        return raw

    async def fake_om(_client, _place):
        # Close enough to agree with the fixture's +16°, so the referee stays
        # quiet and we are testing the happy path rather than the alarm.
        return {
            "current": {"time": "2026-07-31T21:00", "temperature_2m": 15.4,
                        "apparent_temperature": 15.0, "relative_humidity_2m": 88,
                        "surface_pressure": 993.0, "wind_speed_10m": 1.2,
                        "wind_direction_10m": 270, "weather_code": 0},
            "hourly": {"time": ["2026-07-31T21:00"], "temperature_2m": [15.4],
                       "weather_code": [0], "precipitation": [0.0],
                       "precipitation_probability": [0]},
            "daily": {"time": ["2026-07-31"], "temperature_2m_max": [20.0],
                      "temperature_2m_min": [14.0], "weather_code": [61],
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


class TestWeatherEndpoint:
    def test_default_city(self, client_):
        r = client_.get("/weather/api/weather")
        assert r.status_code == 200
        d = r.json()
        assert d["place"]["name"] == "Йошкар-Ола"
        ya = d["sources"]["yandex"]
        assert ya["current"]["temp_c"] == 16.0
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
        assert gm["current"] is None

    def test_provenance_is_reported_per_source(self, client_):
        d = client_.get("/weather/api/weather").json()
        assert d["sources"]["yandex"]["provenance"]["temp_c"] == 1
        assert d["sources"]["yandex"]["fallback_profile"] is False

    def test_divergence_is_recorded_but_decides_nothing(self, client_):
        """Yandex says 16.0, Open-Meteo says 15.4. Both are served, both are
        selectable, and the delta is on the record for whoever is debugging."""
        d = client_.get("/weather/api/weather").json()
        assert d["health"]["divergence_c"]["yandex/openmeteo"] == pytest.approx(0.6)
        assert d["selected"] == "yandex"

    def test_lat_lon_addressing(self, client_):
        r = client_.get("/weather/api/weather?lat=56.63&lon=47.9")
        assert r.status_code == 200
        assert r.json()["sources"]["yandex"]["current"]["temp_c"] == 16.0

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


class TestDegradation:
    def test_yandex_down_selects_the_next_available_source(
            self, request, monkeypatch):
        async def boom(_client, _url):
            raise RuntimeError("connection refused")

        async def fake_om(_client, _place):
            return {"current": {"time": "2026-07-31T21:00",
                                "temperature_2m": 15.4, "weather_code": 0}}

        monkeypatch.setattr(yandex_html, "fetch_html", boom)
        monkeypatch.setattr(gismeteo, "fetch_html", boom)
        monkeypatch.setattr(openmeteo, "fetch", fake_om)
        service.invalidate()

        d = TestClient(app).get("/weather/api/weather").json()
        assert d["selected"] == "openmeteo"
        assert d["sources"]["openmeteo"]["current"]["temp_c"] == 15.4
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
            return {"current": {"time": "2026-07-31T21:00",
                                "temperature_2m": -12.0, "weather_code": 0}}

        monkeypatch.setattr(yandex_html, "fetch_html", fake_fetch)
        monkeypatch.setattr(gismeteo, "fetch_html", boom)
        monkeypatch.setattr(openmeteo, "fetch", cold_om)
        service.invalidate()

        d = TestClient(app).get("/weather/api/weather").json()
        assert d["selected"] == "yandex"
        assert d["sources"]["yandex"]["current"]["temp_c"] == 16.0
        assert d["sources"]["openmeteo"]["current"]["temp_c"] == -12.0
        assert d["health"]["divergence_c"]["yandex/openmeteo"] == pytest.approx(28.0)

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
        assert first["sources"]["yandex"]["current"]["temp_c"] == 16.0

        async def boom(*_a, **_k):
            raise RuntimeError("gone")

        monkeypatch.setattr(yandex_html, "fetch_html", boom)
        d = c.get("/weather/api/weather?force=1").json()
        assert d["sources"]["yandex"]["current"]["temp_c"] == 16.0
        assert d["health"]["status"] == "stale"
        assert any("устарели" in w for w in d["health"]["warnings"])


class TestSurfaces:
    def test_cities(self, client_):
        d = client_.get("/weather/api/cities").json()
        assert d["default"] == "yoshkar-ola"
        assert any(c["name"] == "Йошкар-Ола" for c in d["cities"])

    def test_health_is_opinionated(self, client_):
        r = client_.get("/weather/api/health")
        assert r.status_code == 200
        assert r.json()["status"] in ("ok", "degraded")

    def test_manifest_scope_follows_base_path(self, client_):
        m = client_.get("/weather/manifest.webmanifest").json()
        assert m["scope"] == "/weather/" and m["start_url"] == "/weather/"

    def test_service_worker_is_allowed_the_whole_subsection(self, client_):
        r = client_.get("/weather/sw.js")
        assert r.headers["Service-Worker-Allowed"] == "/weather/"

    def test_debug_routes_404_without_a_token(self, client_):
        """404, not 403 -- their existence is not advertised."""
        assert client_.get("/weather/api/debug/selftest").status_code == 404

    def test_root_redirects_into_the_subsection(self, client_):
        r = client_.get("/", follow_redirects=False)
        assert r.status_code in (307, 308)
        assert r.headers["location"] == "/weather/"


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
        after compressing, so it is the real figure.
        """
        return int(response.headers["content-length"])

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
        """Shell plus first payload, compressed, as a phone would fetch it."""
        total = 0
        for path in (*self.SHELL, "api/weather"):
            r = client_.get(f"/weather/{path}", headers={"Accept-Encoding": "gzip"})
            total += self.wire_bytes(r)
        assert total < 32_000, (
            f"a cold load is now {total/1000:.1f} kB compressed; it was 26 kB. "
            f"Something sizeable joined the shell -- check before raising this.")

    def test_the_uncompressed_shell_has_not_ballooned_either(self, client_):
        """Compression can hide a lot of growth. Watch the source too."""
        raw = sum(len(client_.get(f"/weather/{n}").content) for n in self.SHELL)
        assert raw < 80_000, f"the shell source is now {raw/1000:.1f} kB"

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
    def _critical_colour(html: str, scheme: str = "dark") -> str:
        import re
        head = html.split("</style>", 1)[0]
        assert "html{background:" in head, \
            "the critical style block is gone -- the first paint is white again"
        if scheme == "light":
            head = head.split("prefers-color-scheme:light", 1)[1]
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

    def test_light_mode_gets_its_own_first_paint(self, client_):
        """A dark first paint under a light sky is the same flash, inverted."""
        html = client_.get("/weather/index.html").text
        light = self._critical_colour(html, "light")
        assert light != self._critical_colour(html)
        assert f"--sky1:{light}" in html

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
