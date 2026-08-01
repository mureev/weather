"""The one place an outbound HTTP client is built.

Split out of `service.py` because it answers a different question. Everything
here is about *transport* -- which egress address, which HTTP version, how long
to wait -- and nothing here knows what a forecast is. `routing.py` decides
which door to knock on; this decides how to knock.
"""

from __future__ import annotations

import importlib.util
import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)

# HTTP/2 makes the request profile look more like a browser and less like a
# script, which is worth having and not worth a hard dependency: without `h2`
# installed we negotiate HTTP/1.1 rather than refusing to start.
HTTP2_AVAILABLE = importlib.util.find_spec("h2") is not None
if not HTTP2_AVAILABLE:  # pragma: no cover - environment probe
    log.info("h2 not installed; upstream fetches will use HTTP/1.1")


def client(http2: bool | None = None,
           proxy: str | None = None,
           timeout: float | None = None) -> httpx.AsyncClient:
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
    kw: dict = {"follow_redirects": True,
                "timeout": timeout or settings.upstream_timeout_s}
    egress = proxy if proxy is not None else settings.proxies
    if egress:
        kw["proxy"] = egress
    # HTTP/2 makes the request profile look more like a browser and less like a
    # script. Not worth a hard dependency: without `h2` we use HTTP/1.1 rather
    # than refusing to start.
    want = HTTP2_AVAILABLE if http2 is None else (http2 and HTTP2_AVAILABLE)
    if want:
        kw["http2"] = True
    return httpx.AsyncClient(**kw)
