"""The scraper. This is the source of record.

Request hygiene, which is most of the privacy model:

* We send a plausible browser `User-Agent` and `Accept-Language: ru-RU`, and
  **nothing derived from the phone.** Not its `Accept-Language`, not its
  `User-Agent`, not its `Referer`, not its timezone. `Europe/Moscow` versus
  anything else gives away region independently of IP, so a header that merely
  passes through is a leak with extra steps.
* One upstream fetch per city per cache TTL, serving every device behind us.
  That is a slower request rate than a single human with the page open.
* `robots.txt` permits `/pogoda`. It disallows `/pogoda/search`, `/pogoda/404`,
  `/pogoda/0` and the AMP paths, and we touch none of them. Note the asymmetry:
  `yandex.com/weather/*` *is* disallowed, which is why this is `.ru/pogoda`.

Addressing is by slug or by lat/lon, never by `geoid`. `?geoid=41` is genuinely
Yoshkar-Ola and is genuinely ignored: the modern front end geolocates the
requesting IP instead and hands back Columbus, Ohio, with no error and a
perfectly parseable page.
"""

from __future__ import annotations

import datetime as dt
import logging
from urllib.parse import urlencode

import httpx

from ..config import settings
from ..extract import Extracted, check_identity, parse
from ..models import ParseError, Place

log = logging.getLogger(__name__)


def headers() -> dict[str, str]:
    return {
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Cache-Control": "no-cache",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }


def urls_for(place: Place, host: str | None = None) -> list[str]:
    """Every way we know to ask for this place, best first."""
    host = (host or settings.yandex_host).rstrip("/")
    out: list[str] = []
    if place.path and not place.ad_hoc:
        out.append(f"{host}/pogoda/ru/{place.path}")
    coords = urlencode({"lat": f"{place.lat:.4f}", "lon": f"{place.lon:.4f}"})
    out.append(f"{host}/pogoda/?{coords}")
    return out


async def fetch_html(client: httpx.AsyncClient, url: str) -> str:
    r = await client.get(url, headers=headers(), follow_redirects=True,
                         timeout=settings.upstream_timeout_s)
    r.raise_for_status()
    return r.text


async def load(client: httpx.AsyncClient, place: Place, *,
               today: dt.date | None = None) -> tuple[Extracted, str]:
    """Fetch and parse, trying each addressing form and then the fallback host.

    A page that parses cleanly but describes the wrong city is rejected here,
    loudly, and we move on to the next way of asking. That is the single most
    important line in this module: the failure this defends against does not
    look like a failure.
    """
    attempts: list[str] = []
    for host in (settings.yandex_host, settings.yandex_fallback_host):
        for url in urls_for(place, host):
            try:
                html_text = await fetch_html(client, url)
            except Exception as e:
                attempts.append(f"{url}: fetch failed: {e}")
                continue
            try:
                got = parse(html_text, today=today)
            except ParseError as e:
                attempts.append(f"{url}: {e}")
                continue

            expect_slug = place.path if (place.path and not place.ad_hoc
                                         and "/pogoda/ru/" in url) else None
            bad = check_identity(
                got.ident,
                expect_slug=expect_slug,
                expect_lat=place.lat if expect_slug is None else None,
                expect_lon=place.lon if expect_slug is None else None,
            )
            if bad:
                log.warning("identity check rejected %s: %s", url, bad)
                attempts.append(f"{url}: wrong place ({bad})")
                continue
            return got, url

    raise ParseError("no usable Yandex page; tried -- " + " | ".join(attempts))
