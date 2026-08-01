#!/usr/bin/env python3
"""Which way in to Gismeteo works *from this machine*?

    make routes                          # every route the app would try
    make routes ARGS='http://1.2.3.4:8080 http://5.6.7.8:3128'
    make routes ARGS='--city kazan'

Gismeteo answers 403 to some addresses and 200 to others, and no header or
transport change touches it (`DECISIONS.md` §7). There are exactly two ways
round that -- knock on a different door, or knock from a different address --
and this walks every combination the app itself would walk, in the same order,
using the same parser, and tells you which ones actually produce a forecast.

It reports more than a status code on purpose. A 200 is not the question; the
question is whether a *usable, correctly-identified* forecast comes back, and a
challenge page answers 200 too. So each row ends in the temperature that was
extracted and the city the page says it is for -- or the reason there is none.

Runs inside the image, where httpx and the parsers already live:

    docker run --rm -i -v "$PWD/tools/route_probe.py:/probe.py:ro" IMAGE \\
        python /probe.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

# Mounted at /probe.py and run with the image's WORKDIR, so `app` is normally
# importable already; this is for the case where it is run from elsewhere.
sys.path.insert(0, "/app")

import httpx

from app import routing
from app.cities import get as get_city
from app.config import settings
from app.http import client
from app.models import Blocked, ParseError
from app.sources import gismeteo


async def probe(route: routing.Route, place, timeout: float) -> tuple[bool, str]:
    host, proxy = route
    t0 = time.monotonic()
    try:
        async with client(http2=False, proxy=proxy, timeout=timeout) as c:
            got, _url = await gismeteo.load(c, place, host=host, timeout=timeout)
    except Blocked as e:
        return False, f"refused (challenge page): {e}"
    except httpx.HTTPStatusError as e:
        return False, f"HTTP {e.response.status_code}"
    except httpx.HTTPError as e:
        return False, f"{type(e).__name__}: {str(e)[:70]}"
    except ParseError as e:
        # Reached and readable, but not usable -- a real parser finding, and
        # the one result here that no other route will fix.
        return False, f"PARSE: {str(e)[:90]}"
    except Exception as e:  # pragma: no cover - diagnostic
        return False, f"{type(e).__name__}: {str(e)[:70]}"

    ms = int((time.monotonic() - t0) * 1000)
    cur = got.current
    temp = f"{cur.temp_c:+.0f}°C" if cur and cur.temp_c is not None else "no temp"
    who = got.ident.name or got.ident.slug or "?"
    gid = got.ident.geo_id
    state = "M.state" if got.ident.lat is not None else "DOM only"
    return True, (f"{ms:>5}ms  {temp:>7}  {who} (id {gid})  "
                  f"{state}  {len(got.hourly)}h/{len(got.daily)}d")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("proxies", nargs="*",
                    help="extra proxies to try, in addition to the configured ones")
    ap.add_argument("--city", default="yoshkar-ola")
    ap.add_argument("--timeout", type=float, default=15.0)
    args = ap.parse_args()

    place = get_city(args.city)
    if place is None:
        print(f"unknown city {args.city!r}")
        return 2
    if gismeteo.city_id(place) is None:
        print(f"no gismeteo id for {args.city!r} -- nothing to probe")
        return 2

    candidates = routing.routes()
    for p in args.proxies:
        for host in settings.gismeteo_host_list:
            if (host, p) not in candidates:
                candidates.append((host, p))

    print(f"\n  {len(candidates)} route(s), city {place.name}, in the order the app "
          f"would try them\n")
    winners = []
    for route in candidates:
        ok, detail = await probe(route, place, args.timeout)
        print(f"  {'OK ' if ok else '   '} {routing.label_route(route):<52} {detail}")
        if ok:
            winners.append(route)

    print()
    if not winners:
        print("  No route works from here.")
        print("  Every row a 403        -> this address is blocked on every host.")
        print("                            Add a proxy: probe candidates by passing")
        print("                            them as arguments before committing one.")
        print("  Every row PARSE:       -> not a routing problem. The page arrived")
        print("                            and did not parse; re-record the fixture")
        print("                            (make fixtures) and read the test diff.")
        return 1

    print(f"  {len(winners)} of {len(candidates)} routes work. Put the hosts in "
          f"GISMETEO_HOSTS and any proxies in GISMETEO_PROXY,")
    print("  in this order -- the app tries them top-down and remembers the winner:")
    print()
    print("    GISMETEO_HOSTS=" + ",".join(
        dict.fromkeys(h for h, _ in winners)))
    proxies = [p for _, p in winners if p]
    if proxies:
        print("    GISMETEO_PROXY=" + ",".join(dict.fromkeys(proxies)))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
