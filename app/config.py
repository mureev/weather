"""Environment-driven settings.

Frozen dataclass, read once at import. Everything here has a default that
produces a working app, so an empty `.env` is a valid configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _s(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _i(name: str, default: int) -> int:
    try:
        return int(_s(name, str(default)))
    except ValueError:
        return default


def _f(name: str, default: float) -> float:
    try:
        return float(_s(name, str(default)))
    except ValueError:
        return default


def _b(name: str, default: bool) -> bool:
    return _s(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


def _list(raw: str) -> tuple[str, ...]:
    """Comma-separated, trimmed, blanks dropped, order preserved, deduped.

    Deduped because these lists get pasted together from probe output and a
    repeated entry is a route tried twice against the same clock budget.
    """
    out: list[str] = []
    for part in (raw or "").split(","):
        p = part.strip().rstrip("/")
        if p and p not in out:
            out.append(p)
    return tuple(out)


@dataclass(frozen=True)
class Settings:
    # --- where the app lives -------------------------------------------------
    # Served under a path on an existing site. Set to "" for a bare subdomain
    # deploy; everything downstream (routes, manifest, service-worker scope)
    # derives from this single value.
    # Read directly rather than through `_s`, which treats an empty value as
    # unset -- and empty is the one value this setting documents.
    base_path: str = field(
        default_factory=lambda: os.environ.get("BASE_PATH", "/weather").rstrip("/"))

    # --- upstreams -----------------------------------------------------------
    yandex_host: str = field(default_factory=lambda: _s("YANDEX_HOST", "https://yandex.ru"))
    yandex_fallback_host: str = field(
        default_factory=lambda: _s("YANDEX_FALLBACK_HOST", "https://yandex.by")
    )
    # Optional egress proxy for the *upstream* fetch only. Empty = direct.
    # Point this at a box in-country and Yandex sees that IP instead of the
    # server's. Nothing else in the app changes.
    upstream_proxy: str = field(default_factory=lambda: _s("UPSTREAM_PROXY", ""))
    # Gismeteo blocks by IP, not by request shape: identical requests get 200
    # from a Russian residential address and 403 from this Latvian VPS -- plain
    # curl and stdlib urllib included. No header or transport change touches
    # it. Short of knocking on another host (`gismeteo_hosts`, below), the one
    # thing that will is an egress proxy on a box whose address they accept.
    # Falls back to UPSTREAM_PROXY, then to direct.
    #
    # **Comma-separated**, tried in order, because any one egress can die and
    # a list is what turns a dead entry into a non-event. See `gismeteo_egress`
    # below for the ordering, and `make routes` (`tools/route_probe.py`) to
    # test a candidate against the real page before it goes in here.
    gismeteo_proxy: str = field(default_factory=lambda: _s("GISMETEO_PROXY", ""))
    # Total wall-clock the route search may spend before giving up for this
    # fetch. Without it, eight dead proxies at a 12 s timeout each would hold
    # the whole /api/weather response for a minute and a half -- Gismeteo is
    # fetched concurrently with the other two, so its slowest route sets the
    # latency for all three. A bounded search degrades to "tab disabled"; an
    # unbounded one degrades to "the app is broken".
    gismeteo_route_budget_s: float = field(
        default_factory=lambda: _f("GISMETEO_ROUTE_BUDGET_S", 20.0)
    )
    # The other half of "how do we reach Gismeteo": *which host*. `meteofor.lv`
    # is the same forecast service under its export brand -- same numeric city
    # ids, same `window.M.state`, same values to the minute -- and it serves
    # Latvia, which `gismeteo.ru` will not. Changing where we knock turned out
    # to be cheaper than changing where we knock *from*.
    #
    # Comma-separated, tried in order, and combined with the proxy list above:
    # every host is tried on each egress route before moving to the next one,
    # so the free options are exhausted before a proxy is paid for.
    gismeteo_hosts: str = field(
        default_factory=lambda: _s(
            "GISMETEO_HOSTS", "https://www.gismeteo.ru,https://meteofor.lv/ru")
    )

    openmeteo_url: str = field(
        default_factory=lambda: _s("OPENMETEO_URL", "https://api.open-meteo.com/v1/forecast")
    )
    geocode_url: str = field(
        default_factory=lambda: _s(
            "GEOCODE_URL", "https://geocoding-api.open-meteo.com/v1/search"
        )
    )

    # --- behaviour -----------------------------------------------------------
    cache_ttl_s: int = field(default_factory=lambda: _i("CACHE_TTL_S", 600))
    stale_grace_s: int = field(default_factory=lambda: _i("STALE_GRACE_S", 6 * 3600))
    # How many places may sit in the cache at once. Keys are place slugs, and
    # a slug is whatever the URL can express -- every searchable city, plus one
    # per distinct GPS fix. Unbounded, that is a set that only ever grows.
    cache_max_entries: int = field(default_factory=lambda: _i("CACHE_MAX_ENTRIES", 64))
    upstream_timeout_s: float = field(default_factory=lambda: _f("UPSTREAM_TIMEOUT_S", 12.0))
    # Upstream rounds that callers can cause for places outside the registry
    # -- GPS fixes, searched places, search queries -- per hour, all callers
    # together. Those keys are coordinates and free text, so without a cap a
    # stranger decides how often this server's address asks Yandex and
    # Open-Meteo for something. Registry cities are exempt: a handful of keys,
    # one round per TTL each, however often they are asked for.
    cold_fetches_per_hour: int = field(
        default_factory=lambda: _i("COLD_FETCHES_PER_HOUR", 180))

    # How far apart two sources must land before the gap is worth recording in
    # /api/health. Informational: with three readings on screen, divergence no
    # longer rejects a source or overrides the user's selection.
    divergence_warn_c: float = field(default_factory=lambda: _f("DIVERGENCE_WARN_C", 6.0))

    default_city: str = field(default_factory=lambda: _s("DEFAULT_CITY", "yoshkar-ola"))
    extra_cities: str = field(default_factory=lambda: _s("EXTRA_CITIES", ""))
    # `slug:their-slug-id,...`  Gismeteo can only be addressed by its own
    # numeric id, and there is no way to derive one, so extra cities need it
    # supplied by hand.
    gismeteo_ids: str = field(default_factory=lambda: _s("GISMETEO_IDS", ""))
    # Gismeteo is fetched over HTTP/1.1 by default, as `curl` would. HTTP/2
    # fingerprinting was the second theory for its 403 and, like the first, it
    # was wrong: the refusal is by address (`DECISIONS.md` §7). The default
    # stayed because it is the more conservative request and costs nothing.
    gismeteo_http2: bool = field(default_factory=lambda: _b("GISMETEO_HTTP2", False))

    allow_geolocation: bool = field(default_factory=lambda: _b("ALLOW_GEOLOCATION", True))
    # Client rounds first; we round again server-side. Belt and braces: a
    # hand-crafted request cannot make us send a precise fix upstream, key a
    # cache by it or write it into our own log lines. uvicorn's access log is
    # the exception -- it records the request line as it arrived.
    coord_precision: int = field(default_factory=lambda: _i("COORD_PRECISION", 2))

    debug_token: str = field(default_factory=lambda: _s("DEBUG_TOKEN", ""))
    log_level: str = field(default_factory=lambda: _s("LOG_LEVEL", "INFO"))

    @property
    def user_agent(self) -> str:
        # A normal browser. We are one request per city per ten minutes serving
        # every device behind us; nothing here is trying to look like a fleet.
        return _s(
            "USER_AGENT",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        )

    @property
    def proxies(self) -> str | None:
        return self.upstream_proxy or None

    @property
    def gismeteo_proxies(self) -> str | None:
        """The first configured proxy. For callers that want just one."""
        egress = self.gismeteo_egress
        return egress[0] if egress and egress[0] else None

    @property
    def gismeteo_egress(self) -> tuple[str | None, ...]:
        """Every way *out* to Gismeteo, in the order they should be tried.

        `None` means "direct", and it is always the last entry: it costs one
        request every ten minutes on a box that is blocked, and it is the
        difference between the app working and not working on a box that is
        *not* -- a laptop on a VPN, the mock server, a future host in-country.
        A configured proxy list should never be the reason the ordinary path
        stops being tried.
        """
        return (*_list(self.gismeteo_proxy or self.upstream_proxy), None)

    @property
    def gismeteo_host_list(self) -> tuple[str, ...]:
        """Every host *to* try, in order. Always at least one."""
        return _list(self.gismeteo_hosts) or ("https://www.gismeteo.ru",)


settings = Settings()
