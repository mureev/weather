"""How to reach Gismeteo when Gismeteo does not want to be reached.

Gismeteo refuses this server by IP address and no request-level change touches
it -- see `DECISIONS.md` §7 for the evidence and the two wrong theories that
came first. There are exactly two ways around that, and this module is both of
them plus the rule for choosing between them:

    knock on a different door       GISMETEO_HOSTS   (gismeteo.ru, meteofor.lv)
    knock from a different address  GISMETEO_PROXY   (a list, tried in order)

It lives apart from `service.py` because it is the only source that needs any
of this, and because "which route worked" is state -- the sticky winner below --
that has no business sitting in the middle of forecast assembly.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time

import httpx

from .config import settings
from .http import DIRECT, client
from .models import Blocked, ParseError, Place
from .sources import gismeteo

log = logging.getLogger(__name__)


# A route is *which host* reached *how*: (host, proxy), proxy `None` = direct.
# Two knobs rather than one, because the two ways round an IP block are to
# knock somewhere else and to knock from somewhere else, and only the first
# turned out to be free.
Route = tuple[str, str | None]

# The route that worked last time, tried first next time. Mirrors come and go
# and free proxy lists are mostly dead entries, so without this the app pays
# the whole search on every fetch instead of only on the one where the winner
# finally dies.
_sticky: dict[str, Route] = {}


def _mask(proxy: str | None) -> str:
    """A proxy for logs and `detail`, with any credentials removed.

    Free proxy lists hand out `http://user:pass@host:port` often enough that
    printing the raw string would eventually copy a password into `detail`,
    and diagnostics get pasted into chat windows. The host and port stay:
    they are what a reader debugging a route needs, which is why `detail`
    goes only to the debug token (`DECISIONS.md` §38).
    """
    if not proxy:
        return "direct"
    try:
        u = httpx.URL(proxy)
        host = f"{u.host}:{u.port}" if u.port else (u.host or "?")
        return f"{u.scheme}://{host}"
    except Exception:
        return "proxy"


def label_route(route: Route) -> str:
    host, proxy = route
    return host if proxy is None else f"{host} via {_mask(proxy)}"


def _brief(e: Exception) -> str:
    """httpx's own message is three lines ending in an MDN link."""
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    return f"{type(e).__name__}: {e}"[:120]


def routes() -> list[Route]:
    """Host × egress, in intent order, last winner promoted to the front.

    Egress is the outer loop, and direct is its *last* entry rather than its
    first, because a configured proxy is an instruction and not a hint: the
    reason to set one may be that Gismeteo blocks this address, but it may
    equally be that you want to appear in-country regardless. Preferring
    direct because it happened to answer would quietly undo that.

    Hosts are the inner loop, so every mirror is tried on the route you asked
    for before the search gives up on it.
    """
    out: list[Route] = [(h, p)
                        for p in settings.gismeteo_egress
                        for h in settings.gismeteo_host_list]
    winner = _sticky.get("route")
    if winner in out:
        out.remove(winner)
        out.insert(0, winner)
    return out


async def fetch_gismeteo(place: Place, today: dt.date | None = None):
    """Gismeteo, by whichever route still works.

    Gismeteo refuses this server by address (`DECISIONS.md` §7), so the fetch
    has to be able to arrive from somewhere else -- or, far more cheaply, to
    knock on a different door. `GISMETEO_HOSTS` is the doors, `GISMETEO_PROXY`
    is the addresses, and this walks the product of the two until one answers.

    The retry rule is the whole point, and it is a rule about *which failure*:

      refused (`Blocked`, or any httpx error)  -> another route may work
      parsed and wrong (`ParseError`)          -> every route returns this page

    Retrying a genuine parse failure down eight routes would spend the whole
    budget reproducing the same bug eight times and then report a timeout,
    which is exactly how a broken parser hides. So it stops on the first one
    and says what broke.
    """
    if gismeteo.city_id(place) is None:
        # Gismeteo can only be addressed as /weather-<slug>-<id>/ -- their
        # robots.txt disallows every URL with a query string -- and we have no
        # id for this place. Saying so is the honest move; substituting a
        # nearby city we *do* have an id for would be the wrong-city failure
        # this project exists to prevent, only self-inflicted.
        return None, "нет города"

    candidates = routes()
    deadline = time.monotonic() + settings.gismeteo_route_budget_s
    last = "недоступен"

    for n, route in enumerate(candidates, 1):
        host, proxy = route
        left = deadline - time.monotonic()
        if n > 1 and left < 1.0:
            log.warning("gismeteo route budget spent after %d of %d routes",
                        n - 1, len(candidates))
            last = f"{last} (route budget spent after {n - 1}/{len(candidates)})"
            break
        per = min(settings.upstream_timeout_s, max(left, 1.0))
        try:
            # httpx's timeout bounds each *read*, not the request: a route
            # that drips bytes never trips it, so without this the budget
            # bounded only the gaps between routes.
            async with asyncio.timeout(per), client(
                    http2=settings.gismeteo_http2, proxy=proxy or DIRECT,
                    timeout=per) as c:
                got, url = await gismeteo.load(c, place, today=today,
                                              host=host, timeout=per)
        except (Blocked, httpx.HTTPError, TimeoutError) as e:
            last = f"{label_route(route)}: {_brief(e)}"
            log.info("gismeteo route %d/%d refused -- %s", n, len(candidates), last)
            if _sticky.get("route") == route:
                del _sticky["route"]
            continue
        except ParseError as e:
            log.warning("gismeteo unusable (%s): %s", label_route(route), e)
            return None, str(e)
        except Exception as e:                      # pragma: no cover
            log.warning("gismeteo fetch error: %s", e)
            return None, str(e)
        _sticky["route"] = route
        log.info("gismeteo ok via %s", url)
        return got, None

    return None, last


def sticky_route() -> Route | None:
    """Which route last worked, or None if none has yet. Read-only: for
    `health.detail`, which says how the forecast actually got here."""
    return _sticky.get("route")

