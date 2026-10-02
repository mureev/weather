"""The one place an outbound HTTP client is built.

Split out of `service.py` because it answers a different question. Everything
here is about *transport* -- which egress address, which HTTP version, how long
to wait -- and nothing here knows what a forecast is. `routing.py` decides
which door to knock on; this decides how to knock.
"""

from __future__ import annotations

import importlib.util
import logging
import ssl

import certifi
import httpx2

from .config import settings

log = logging.getLogger(__name__)

# HTTP/2 makes the request profile look more like a browser and less like a
# script, which is worth having and not worth a hard dependency: without `h2`
# installed we negotiate HTTP/1.1 rather than refusing to start.
HTTP2_AVAILABLE = importlib.util.find_spec("h2") is not None
if not HTTP2_AVAILABLE:  # pragma: no cover - environment probe
    log.info("h2 not installed; upstream fetches will use HTTP/1.1")

# One TLS context for every client. Building one loads the CA bundle -- about
# 30 ms of CPU, synchronously on the event loop -- and a client is built per
# request, including requests that end up fetching nothing. Shared, a client
# costs well under a millisecond.
#
# Built here, from certifi, rather than by `httpx2.create_ssl_context()`. Its
# default is `truststore`, the operating system's store, which on Linux it
# applies afresh to every new connection: a re-read of the whole bundle each
# time on Debian's layout, the image's -- 19 ms at the median, on the event
# loop, measured (DECISIONS.md §39). That is the cost this context exists to
# pay once. certifi's anchors are also the ones the app has always trusted, so
# the change of client changes nothing about who is believed. Unlike httpx's
# builder it does not read SSL_CERT_FILE: as with `trust_env=False` below, the
# environment is not a second place to say who is trusted.
_TLS = ssl.create_default_context(cafile=certifi.where())


# An explicit "no proxy". `proxy=None` means "the default egress", which is
# UPSTREAM_PROXY when one is set -- so a route list that meant "direct" by None
# went through the proxy again, under a label saying it had not.
DIRECT = ""


def client(http2: bool | None = None,
           proxy: str | None = None,
           timeout: float | None = None) -> httpx2.AsyncClient:
    """One client, and the only place an egress proxy is configured.

    `UPSTREAM_PROXY` is empty by default. Point it at a box in-country and the
    upstreams see that IP instead of this server's -- which matters when the
    server is not where you want to appear to be, because both Yandex and
    Gismeteo geolocate the requesting IP when their addressing hints go stale.

    Worth knowing before trusting a proxy you did not build: every upstream
    here is HTTPS, so the proxy is asked to CONNECT and then relays bytes it
    cannot read. Certificates are still verified against the origin, by us.
    A hostile hop can drop the connection or stall it; it cannot hand us a
    forged forecast, which is the only failure that would actually matter.
    """
    # `trust_env=False`: HTTPS_PROXY in the environment would otherwise be a
    # second, silent place an egress proxy is configured.
    kw: dict = {"follow_redirects": True, "verify": _TLS, "trust_env": False,
                "timeout": timeout or settings.upstream_timeout_s}
    egress = settings.proxies if proxy is None else (proxy or None)
    if egress:
        kw["proxy"] = egress
    want = HTTP2_AVAILABLE if http2 is None else (http2 and HTTP2_AVAILABLE)
    if want:
        kw["http2"] = True
    return httpx2.AsyncClient(**kw)
