"""How the Gismeteo fetch chooses a way in, and when it gives up.  (`routing.py`)

Gismeteo refuses this server by IP and no request-level change touches it
(`DECISIONS.md` §7). So the fetch has two independent knobs -- which host, and
which egress address -- and walks the product of them. Everything here is that
walk. No network: the loads are stubbed, because what is under test is the
*decision*, not the parser.

The distinction that matters most is which failures are worth another route:

    Blocked / httpx errors -> refused. Another route may work.
    ParseError             -> the page arrived and did not parse. Every route
                              returns the same page, so retrying spends the
                              whole budget reproducing one bug and then reports
                              a timeout -- which is how a broken parser hides.

Get that backwards and the app still "works", right up until the day the
parser breaks and the health endpoint blames the network.
"""

from __future__ import annotations

import asyncio
import importlib

import httpx
import pytest

from app import cities
from app import routing as R
from app.models import Blocked, ParseError


@pytest.fixture(autouse=True)
def clean_sticky():
    R._sticky.clear()
    yield
    R._sticky.clear()


@pytest.fixture
def place():
    return cities.get("yoshkar-ola")


def reconfigure(monkeypatch, **env):
    """Rebuild Settings with these env vars. It is a frozen dataclass read at
    import, which is the right call for a server and inconvenient for a test."""
    import app.config

    for k, v in env.items():
        monkeypatch.setenv(k, v)
    importlib.reload(app.config)
    monkeypatch.setattr(R, "settings", app.config.settings)
    monkeypatch.setattr("app.http.settings", app.config.settings)
    monkeypatch.setattr("app.sources.gismeteo.settings", app.config.settings)
    return app.config.settings


# --- the route list --------------------------------------------------------

class TestRouteList:
    def test_direct_on_every_host_when_nothing_is_configured(self, monkeypatch):
        reconfigure(monkeypatch, GISMETEO_PROXY="", UPSTREAM_PROXY="")
        assert R.routes() == [
            ("https://www.gismeteo.ru", None),
            ("https://meteofor.lv/ru", None),
        ]

    def test_the_mirror_is_a_default_not_a_fallback(self, monkeypatch):
        """meteofor.lv ships configured. It is the same forecast service under
        its export brand, and it answers the addresses gismeteo.ru refuses --
        which made it cheaper than any proxy."""
        s = reconfigure(monkeypatch, GISMETEO_PROXY="")
        assert "https://meteofor.lv/ru" in s.gismeteo_host_list

    def test_a_configured_proxy_is_tried_before_direct(self, monkeypatch):
        """Setting a proxy is an instruction, not a hint: you may have set it
        because Gismeteo blocks this box, but equally because you want to
        appear in-country regardless. Preferring direct because it happened to
        answer would quietly undo that."""
        reconfigure(monkeypatch, GISMETEO_PROXY="http://p1:8080")
        assert R.routes() == [
            ("https://www.gismeteo.ru", "http://p1:8080"),
            ("https://meteofor.lv/ru", "http://p1:8080"),
            ("https://www.gismeteo.ru", None),
            ("https://meteofor.lv/ru", None),
        ]

    def test_direct_is_always_reachable_however_long_the_proxy_list(self, monkeypatch):
        reconfigure(monkeypatch, GISMETEO_PROXY="http://a:1,http://b:2,http://c:3")
        assert (R.routes()[-1][1]) is None

    def test_the_list_is_deduped_and_whitespace_tolerant(self, monkeypatch):
        """It gets pasted together from probe output, and a repeated entry is a
        route tried twice against the same clock budget."""
        s = reconfigure(monkeypatch,
                        GISMETEO_PROXY=" http://a:1 , http://a:1,http://b:2 ")
        assert s.gismeteo_egress == ("http://a:1", "http://b:2", None)

    def test_gismeteo_proxy_overrides_the_general_one(self, monkeypatch):
        s = reconfigure(monkeypatch, UPSTREAM_PROXY="http://general:1",
                        GISMETEO_PROXY="http://specific:2")
        assert s.gismeteo_egress == ("http://specific:2", None)

    def test_it_falls_back_to_the_general_proxy(self, monkeypatch):
        s = reconfigure(monkeypatch, UPSTREAM_PROXY="http://general:1",
                        GISMETEO_PROXY="")
        assert s.gismeteo_egress == ("http://general:1", None)


class TestDirectMeansDirect:
    def test_the_direct_route_bypasses_the_upstream_proxy(self, monkeypatch, place):
        """`None` in the route list meant direct, and `client(proxy=None)`
        meant UPSTREAM_PROXY -- so with one set, every "direct" attempt went
        through it again and /api/health reported it as direct."""
        reconfigure(monkeypatch, UPSTREAM_PROXY="http://203.0.113.9:3128",
                    GISMETEO_PROXY="")
        built: list[dict] = []

        class Recorder:
            def __init__(self, **kw):
                built.append(kw)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        async def refused(*_a, **_k):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr("app.http.httpx.AsyncClient", Recorder)
        monkeypatch.setattr("app.sources.gismeteo.load", refused)
        run(R.fetch_gismeteo(place))
        proxied = [kw.get("proxy") for kw in built]
        assert proxied == ["http://203.0.113.9:3128"] * 2 + [None] * 2


# --- what gets retried, and what does not ----------------------------------

def run(coro):
    return asyncio.run(coro)


def stub(monkeypatch, outcomes: dict, seen: list):
    """Make gismeteo.load answer per (host, proxy) from `outcomes`."""
    async def fake_load(client, place, *, host, timeout=None, today=None):
        seen.append(host)
        out = outcomes.get(host)
        if isinstance(out, Exception):
            raise out
        return out, f"{host}/weather-x/"

    monkeypatch.setattr("app.sources.gismeteo.load", fake_load)


class Got:
    """Just enough of an Extracted for the orchestration path."""
    def __init__(self):
        self.current = object()
        self.ident = type("I", (), {"name": "Йошкар-Ола"})()


class TestFailover:
    def test_a_403_on_the_first_host_moves_to_the_second(self, monkeypatch, place):
        reconfigure(monkeypatch, GISMETEO_PROXY="")
        seen: list[str] = []
        good = Got()
        stub(monkeypatch, {
            "https://www.gismeteo.ru": httpx.HTTPStatusError(
                "403", request=httpx.Request("GET", "https://x/"),
                response=httpx.Response(403)),
            "https://meteofor.lv/ru": good,
        }, seen)
        got, err = run(R.fetch_gismeteo(place))
        assert got is good and err is None
        assert seen == ["https://www.gismeteo.ru", "https://meteofor.lv/ru"]

    def test_a_challenge_page_counts_as_refused(self, monkeypatch, place):
        """A 200 with a captcha in the body is a refusal wearing a success
        code. Calling it a parse failure would stop the search on the first
        host that answers politely."""
        reconfigure(monkeypatch, GISMETEO_PROXY="")
        seen: list[str] = []
        good = Got()
        stub(monkeypatch, {
            "https://www.gismeteo.ru": Blocked("captcha"),
            "https://meteofor.lv/ru": good,
        }, seen)
        got, err = run(R.fetch_gismeteo(place))
        assert got is good and err is None
        assert len(seen) == 2

    def test_a_parse_failure_stops_the_search_immediately(self, monkeypatch, place):
        """The one that matters. Every route returns the same page, so trying
        the rest can only waste the budget and mislabel a parser bug as a
        network problem."""
        reconfigure(monkeypatch, GISMETEO_PROXY="")
        seen: list[str] = []
        stub(monkeypatch, {
            "https://www.gismeteo.ru": ParseError("no current temperature"),
            "https://meteofor.lv/ru": Got(),
        }, seen)
        got, err = run(R.fetch_gismeteo(place))
        assert got is None
        assert "no current temperature" in err
        assert seen == ["https://www.gismeteo.ru"], "it kept going after a parse error"

    def test_the_wrong_city_is_never_papered_over_by_another_route(
            self, monkeypatch, place):
        """`check_identity` raises ParseError, so this is the same rule -- but
        it is worth its own test, because "try another mirror until one agrees"
        is exactly the tempting wrong fix."""
        reconfigure(monkeypatch, GISMETEO_PROXY="")
        seen: list[str] = []
        stub(monkeypatch, {
            "https://www.gismeteo.ru": ParseError("wrong place (id 4364)"),
            "https://meteofor.lv/ru": Got(),
        }, seen)
        got, err = run(R.fetch_gismeteo(place))
        assert got is None and "wrong place" in err
        assert len(seen) == 1

    def test_every_route_refused_reports_the_last_reason(self, monkeypatch, place):
        reconfigure(monkeypatch, GISMETEO_PROXY="")
        seen: list[str] = []
        boom = httpx.ConnectError("no route to host")
        stub(monkeypatch, {
            "https://www.gismeteo.ru": boom,
            "https://meteofor.lv/ru": boom,
        }, seen)
        got, err = run(R.fetch_gismeteo(place))
        assert got is None
        assert "meteofor" in err and "ConnectError" in err

    def test_a_city_with_no_id_never_reaches_the_network(self, monkeypatch):
        reconfigure(monkeypatch, GISMETEO_PROXY="")
        seen: list[str] = []
        stub(monkeypatch, {}, seen)
        got, err = run(R.fetch_gismeteo(cities.ad_hoc(56.63, 47.89)))
        assert got is None and err == "нет города"
        assert seen == []


class TestStickiness:
    def test_the_winner_is_tried_first_next_time(self, monkeypatch, place):
        """Without this the app pays the whole search on every fetch instead of
        only on the one where the winner finally dies."""
        reconfigure(monkeypatch, GISMETEO_PROXY="")
        seen: list[str] = []
        stub(monkeypatch, {
            "https://www.gismeteo.ru": httpx.ConnectError("nope"),
            "https://meteofor.lv/ru": Got(),
        }, seen)
        run(R.fetch_gismeteo(place))
        assert len(seen) == 2
        seen.clear()
        run(R.fetch_gismeteo(place))
        assert seen == ["https://meteofor.lv/ru"], "it re-walked the dead route"

    def test_a_dead_winner_is_forgotten_rather_than_retried_forever(
            self, monkeypatch, place):
        reconfigure(monkeypatch, GISMETEO_PROXY="")
        R._sticky["route"] = ("https://meteofor.lv/ru", None)
        seen: list[str] = []
        stub(monkeypatch, {
            "https://meteofor.lv/ru": httpx.ConnectError("gone"),
            "https://www.gismeteo.ru": Got(),
        }, seen)
        run(R.fetch_gismeteo(place))
        assert R._sticky["route"] == ("https://www.gismeteo.ru", None)


class TestBudget:
    def test_a_long_dead_list_cannot_hold_the_whole_response(self, monkeypatch,
                                                             place):
        """Gismeteo is fetched concurrently with the other two sources, so its
        slowest route sets the latency for all three. Eight dead proxies at
        12 s each is not a degraded tab, it is a broken app."""
        reconfigure(monkeypatch,
                    GISMETEO_PROXY=",".join(f"http://p{i}:8080" for i in range(8)),
                    GISMETEO_ROUTE_BUDGET_S="0.2")
        seen: list[str] = []

        async def slow_load(client, place, *, host, timeout=None, today=None):
            seen.append(host)
            await asyncio.sleep(0.15)
            raise httpx.ConnectError("dead")

        monkeypatch.setattr("app.sources.gismeteo.load", slow_load)
        got, err = run(R.fetch_gismeteo(place))
        assert got is None
        assert "budget" in err
        assert len(seen) < 18, f"the budget did not bound the search: {len(seen)}"


class TestTheBudgetIsWallClock:
    def test_a_route_that_drips_cannot_outlast_the_budget(self, monkeypatch,
                                                          place):
        """httpx bounds each read, so an answer arriving a byte at a time
        never times out; GISMETEO_ROUTE_BUDGET_S promised total wall-clock."""
        reconfigure(monkeypatch, GISMETEO_ROUTE_BUDGET_S="1.5",
                    UPSTREAM_TIMEOUT_S="1")

        async def drip(*_a, **_k):
            await asyncio.sleep(30)

        monkeypatch.setattr("app.sources.gismeteo.load", drip)
        import time
        t0 = time.monotonic()
        got, why = run(R.fetch_gismeteo(place))
        assert got is None and "TimeoutError" in why
        assert time.monotonic() - t0 < 3


class TestMasking:
    def test_proxy_credentials_never_reach_a_log_or_a_health_endpoint(self):
        """Free proxy lists hand out user:pass@host often enough that this
        would eventually copy a password into /api/health, and health output
        gets pasted into chat windows."""
        masked = R._mask("http://bob:hunter2@10.0.0.1:8080")
        assert "hunter2" not in masked and "bob" not in masked
        assert "10.0.0.1:8080" in masked

    def test_a_direct_route_says_so(self):
        assert R.label_route(("https://meteofor.lv/ru", None)) == \
            "https://meteofor.lv/ru"

    def test_a_proxied_route_names_both_ends(self):
        line = R.label_route(("https://www.gismeteo.ru", "http://p:1"))
        assert "gismeteo.ru" in line and "http://p:1" in line
