"""Is the sun up?

A weather icon that shows a blazing sun at half past one in the morning is not
a small cosmetic slip -- it is the app telling you something it has no business
believing, which is the failure mode the rest of this codebase is organised
around. So this answers the question properly rather than approximately.

**Why not a lookup, and why not a fixed window.** The obvious implementation is
`hour >= 21 or hour < 5`, and that is what one path here used to do. It is
correct in Yoshkar-Ola in August by coincidence and wrong for most of the rest
of the year: sunrise there moves from 03:44 in June to 08:37 in December, and
sunset from 21:19 to 15:56. A fixed window puts a sun in the sky at 07:00 in
January and a moon at 20:00 in July. Sunrise/sunset strings *are* on the
Gismeteo page, but not on all three sources and not for tomorrow's hours, so
using them would make the icon depend on which source you happened to pick.

Arithmetic has none of those problems: it needs no fetch, no table, no
timezone database beyond the one already in use, and it is equally right in
December, at the equator, and north of the Arctic Circle -- where a fixed
window is not merely inaccurate but categorically wrong, since the sun may not
rise or set at all.

The algorithm is the USNO low-precision solar position, good to about 0.01°
between 1950 and 2050 -- roughly a minute of sunrise time, which is well past
the point where anyone can tell by looking out of the window.
"""

from __future__ import annotations

import datetime as dt
from math import asin, atan2, cos, degrees, radians, sin

# Sunrise and sunset are defined at the moment the sun's *upper limb* touches
# the horizon, not its centre: half a degree of solar radius plus about 0.57°
# of atmospheric refraction. Using 0° instead would put every sunrise four
# minutes late, and -- more to the point -- would stop matching the published
# times this module is tested against.
HORIZON_DEG = -0.833


def altitude_deg(lat: float, lon: float, when: dt.datetime) -> float:
    """The sun's altitude above the horizon, in degrees, at a place and time.

    `when` may be naive, in which case it is read as UTC. Negative means below
    the horizon; +90 would be directly overhead.
    """
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    # Days since J2000.0, fractional.
    n = when.timestamp() / 86400.0 + 2440587.5 - 2451545.0

    mean_long = (280.460 + 0.9856474 * n) % 360.0
    mean_anom = radians((357.528 + 0.9856003 * n) % 360.0)
    # Ecliptic longitude: mean longitude plus the equation of the centre.
    ecl = radians(mean_long + 1.915 * sin(mean_anom) + 0.020 * sin(2 * mean_anom))
    obliquity = radians(23.439 - 0.0000004 * n)

    declination = asin(sin(obliquity) * sin(ecl))
    right_asc = atan2(cos(obliquity) * sin(ecl), cos(ecl))

    # Greenwich mean sidereal time, in hours, then local hour angle.
    gmst = (18.697374558 + 24.06570982441908 * n) % 24.0
    hour_angle = radians((gmst * 15.0 + lon - degrees(right_asc) + 180.0)
                         % 360.0 - 180.0)

    lat_r = radians(lat)
    return degrees(asin(sin(lat_r) * sin(declination)
                        + cos(lat_r) * cos(declination) * cos(hour_angle)))


def is_night(lat: float, lon: float, when: dt.datetime) -> bool:
    """Is the sun below the horizon here, now?"""
    return altitude_deg(lat, lon, when) < HORIZON_DEG


def _event(lat: float, lon: float, day: dt.date, *, rising: bool) -> dt.datetime | None:
    """Sunrise or sunset on `day` (UTC), or None on a polar day or night.

    Only used by the tests and by anyone reading this to check it against a
    published almanac -- the app itself only ever asks `is_night`. Coarse scan
    then bisection, because a closed-form solution would need more care than
    the thing it is checking.
    """
    start = dt.datetime.combine(day, dt.time(0, tzinfo=dt.UTC))
    prev_t, prev_a = start, altitude_deg(lat, lon, start) - HORIZON_DEG
    for i in range(1, 24 * 6 + 1):
        t = start + dt.timedelta(minutes=10 * i)
        a = altitude_deg(lat, lon, t) - HORIZON_DEG
        if (a > 0) != (prev_a > 0) and ((a > 0) == rising):
            lo, hi = prev_t, t
            for _ in range(40):
                mid = lo + (hi - lo) / 2
                if (altitude_deg(lat, lon, mid) - HORIZON_DEG > 0) == (a > 0):
                    hi = mid
                else:
                    lo = mid
            return lo + (hi - lo) / 2
        prev_t, prev_a = t, a
    return None


def sunrise(lat: float, lon: float, day: dt.date) -> dt.datetime | None:
    return _event(lat, lon, day, rising=True)


def sunset(lat: float, lon: float, day: dt.date) -> dt.datetime | None:
    return _event(lat, lon, day, rising=False)


# --- applying it to icons ---------------------------------------------------

# The ones where you can see what is behind the cloud. An *overcast* sky, rain
# and fog look the same whatever is up there, and inventing `rain-night` would
# mean drawing a moon nobody could see.
#
# `cloudy` joined this list late, and the symptom was worth recording: it is
# «облачно с прояснениями» -- broken cloud -- and its glyph is a sun peering
# round a cloud, so the night rows of the day screen showed a sun at three in
# the morning. The night form was missing rather than wrong, which is why
# nothing failed: `nightify` strips a `-night` suffix it does not recognise,
# so the icon came back correct-looking and diurnal.
_HAS_NIGHT_FORM = ("clear", "partly", "cloudy")


def nightify(icon: str | None, night: bool) -> str | None:
    """Force an icon into its day or night form.

    Idempotent and bidirectional on purpose: it is applied over whatever the
    parser produced, so it has to *correct* a wrong guess rather than only add
    a suffix to a bare one. Yandex ships a real day/night flag in its icon
    codes and should already agree; Gismeteo and Open-Meteo ship none at all,
    which is how a midsummer-noon sun ended up over a forecast for 01:25.
    """
    if not icon:
        return icon
    base = icon[:-6] if icon.endswith("-night") else icon
    if base not in _HAS_NIGHT_FORM:
        return base
    return f"{base}-night" if night else base


def local_now(tz: str) -> dt.datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(tz))
    except Exception:                                   # pragma: no cover
        return dt.datetime.now(dt.UTC)


def zone(tz: str) -> dt.tzinfo:
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz)
    except Exception:                                   # pragma: no cover
        return dt.UTC


def hour_times(times: list[str], tz: str,
               now: dt.datetime | None = None) -> list[dt.datetime | None]:
    """Turn an hourly series' labels into real instants.

    The series is a mix of formats by source -- `"21:00"` from the scrapers,
    a full ISO stamp from Open-Meteo -- and the bare ones carry no date, which
    matters exactly once per series: the run crosses midnight, and every hour
    after that belongs to tomorrow. Walking forward and rolling the date on
    each wrap is the whole trick.
    """
    tzi = zone(tz)
    now = now or dt.datetime.now(tzi)
    out: list[dt.datetime | None] = []
    day = now.date()
    prev: int | None = None
    for raw in times:
        text = (raw or "").strip()
        if "T" in text:                     # already an instant
            try:
                stamp = dt.datetime.fromisoformat(text)
                out.append(stamp if stamp.tzinfo else stamp.replace(tzinfo=tzi))
                continue
            except ValueError:
                out.append(None)
                continue
        try:
            hh, mm = (int(x) for x in text.split(":")[:2])
        except (ValueError, TypeError):
            out.append(None)
            prev = None
            continue
        if prev is None:
            # The first label is the one closest to now, not necessarily today:
            # a series starting at 00:00 fetched at 23:50 is tomorrow's.
            if hh < now.hour - 12:
                day = day + dt.timedelta(days=1)
        elif hh < prev:
            day = day + dt.timedelta(days=1)
        if not (0 <= hh < 24 and 0 <= mm < 60):
            # «24:00» is a way of writing midnight that `dt.time` refuses. An
            # instant we cannot name is None, like any unreadable label --
            # raising here ran on every serve and took the whole payload down.
            out.append(None)
            continue
        prev = hh
        out.append(dt.datetime.combine(day, dt.time(hh, mm), tzinfo=tzi))
    return out
