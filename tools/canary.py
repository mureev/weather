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

Exit codes, so a scheduler can act on it:

    0  everything as expected
    1  something degraded -- read the output, then `make fixtures`
    2  could not reach the site at all (a different problem; not a parser one)

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", default="https://mureev.com/weather")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--allow-missing", default="",
                    help="comma-separated sources that may be unavailable "
                         "without failing, e.g. gismeteo on a blocked box")
    args = ap.parse_args()

    url = args.site.rstrip("/") + "/api/health"
    try:
        health = fetch(url, args.timeout)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"  cannot reach {url}: {e}")
        return 2

    tolerated = {s.strip() for s in args.allow_missing.split(",") if s.strip()}
    problems: list[str] = []

    print(f"\n  {url}")
    print(f"  status: {health.get('status')}   build: {health.get('build')}"
          f"   age: {health.get('age_s')}s\n")

    for key, expected in EXPECTED_TIER.items():
        src = (health.get("sources") or {}).get(key) or {}
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
