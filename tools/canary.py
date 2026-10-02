#!/usr/bin/env python3
"""Has an upstream quietly changed under us?

    make canary                       # against the live site
    make canary SITE=http://localhost:8080/weather

The test suite runs against committed fixtures, which is what makes it fast and
offline -- and also means it is, by construction, incapable of noticing that
the real pages have moved. A green suite proves the parser still reads *July's*
HTML. This reads today's.

It is not a second test suite. It asks one question the suite cannot:

    is every source still answering from the rung it answered from before?

A source that drops from tier 1 to tier 3 usually keeps working. The numbers
stay right, nothing errors, and the parser is now one small redesign away from
confidently reading the wrong cell. That is the state worth hearing about on a
calm Tuesday rather than on the morning you actually wanted the forecast --
which is the entire argument for recording provenance in the first place.

What it reads is the forecast itself: `/api/weather` for the default city, the
payload every phone gets, which carries each source's provenance. It used to
read `/api/health`, which reshaped that same envelope under names of its own --
and asked it for `dropped_fields`, which that endpoint called `dropped`, so a
dropped field could never fail this. Read from what the app actually serves,
the names cannot drift apart. The build comes from `/api/version`, for the log.

Exit codes, so a scheduler can act on it:

    0  everything as expected
    1  something degraded -- read the output, then `make fixtures`
    2  nothing to measure: the site is unreachable, or no source is answering
       right now (a different problem; not a parser one)

Deliberately dependency-free: stdlib only, so it runs from a cron line, a CI
job, or a laptop with nothing installed.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

# What each source is expected to manage on a good day. Tier 1 is an embedded
# JSON contract, 2 is labelled/accessible markup, 3 is content-shaped DOM.
# Open-Meteo is a documented JSON API and has no lower rung to fall to, so
# anything but 1 there means something is badly wrong rather than merely drifting.
EXPECTED_TIER = {"yandex": 2, "gismeteo": 2, "openmeteo": 1}

TIER_NAME = {0: "absent", 1: "NAMED (embedded JSON)",
             2: "LABELLED (a11y/labelled markup)", 3: "SHAPE (DOM shape)"}


def fetch(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def build_of(site: str, timeout: float) -> str:
    """Which build answered. For the log only: no verdict depends on it, so a
    failure here is a question mark rather than an exit code."""
    try:
        return str(fetch(site + "/api/version", timeout).get("build") or "?")
    except Exception:
        return "?"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", default="https://mureev.com/weather")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--allow-missing", default="",
                    help="comma-separated sources that may be unavailable "
                         "without failing, e.g. gismeteo on a blocked box")
    args = ap.parse_args(argv)

    site = args.site.rstrip("/")
    url = site + "/api/weather"
    try:
        payload = fetch(url, args.timeout)
    except urllib.error.HTTPError as e:
        # The app's own 503 says no source answered and nothing was cached; a
        # 502 or 504 is the proxy in front failing to reach it at all.
        print(f"  {url} answered {e.code} {e.reason}")
        return 2
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"  cannot reach {url}: {e}")
        return 2

    health = payload.get("health") or {}
    if health.get("status") not in ("ok", "degraded"):
        # Stale: every source failed just now, and this is the last good
        # payload held over. It is served with 200, because a phone should
        # still see it -- but its provenance describes the last fetch that
        # worked, not today's pages, so reading it here would be a false
        # "nothing has moved". /api/health answered 503 for it, so this is
        # the exit code it had then.
        print(f"  {url}: status {health.get('status')}, "
              f"{health.get('age_s')}s old -- no source is answering now")
        return 2

    tolerated = {s.strip() for s in args.allow_missing.split(",") if s.strip()}
    problems: list[str] = []

    print(f"\n  {url}")
    print(f"  status: {health.get('status')}   build: {build_of(site, args.timeout)}"
          f"   age: {health.get('age_s')}s\n")

    for key, expected in EXPECTED_TIER.items():
        src = (payload.get("sources") or {}).get(key) or {}
        if not src.get("available"):
            line = f"  {key:<10} UNAVAILABLE  {src.get('reason') or '?'}"
            print(line)
            if key not in tolerated:
                problems.append(f"{key} is down: {src.get('reason')}")
            continue

        tiers = {k: v for k, v in (src.get("provenance") or {}).items() if v}
        worst = max(tiers.values(), default=0)
        flag = "  " if worst <= expected else "!!"
        print(f"{flag}{key:<10} worst tier {worst} "
              f"({TIER_NAME.get(worst, worst)})"
              f"{'   FALLBACK PROFILE' if src.get('fallback_profile') else ''}")

        if worst > expected:
            slipped = sorted(k for k, v in tiers.items() if v > expected)
            problems.append(
                f"{key} dropped to tier {worst} (expected <= {expected}); "
                f"fields: {', '.join(slipped)}")
        if src.get("dropped_fields"):
            problems.append(f"{key} dropped fields: {src['dropped_fields']}")

    diverge = health.get("divergence_c") or {}
    if diverge:
        print("\n  divergence °C: " +
              ", ".join(f"{k} {v:+.1f}" for k, v in sorted(diverge.items())))

    print()
    if not problems:
        print("  Nothing has moved. The fixtures still describe reality.\n")
        return 0

    print("  Something moved:\n")
    for p in problems:
        print(f"    - {p}")
    print("""
  This is the early warning, not the failure. The numbers are probably still
  correct -- a lower rung usually reads the right cell. What has changed is
  that the mechanism you were relying on is gone, and the one now answering is
  more fragile.

    make fixtures        re-record from the box that does the fetching
    make fixtures-gm
    make check           the test diff tells you exactly what moved
""")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
