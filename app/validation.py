
"""What is servable, and what gets dropped.

The failure that hurts is not the scraper breaking loudly. A parser that
returns nothing is caught by the first `if not data` in the call chain. A
parser that returns **743** because a redesign moved the pressure cell will
tell you it is +743 degrees -- or a plausible +55, after some well-meaning
clamp -- and you will believe it.

So: **values are dropped, never clamped.** Every rejection path in this file
sets the field to `None` and records why. A blank with a note beside it is
strictly better than a plausible wrong number.

The layers, each catching what the ones above it cannot:

1. **Range contracts.** Bounds generous enough that real weather never trips
   them and tight enough that a mis-parsed cell almost always does. Oymyakon's
   −67.7 °C clears them; a pressure reading of 743 in the temperature field
   does not.
2. **Unit signatures.** A range check says a value is impossible. A signature
   says *why*, which is the difference between a 3 a.m. mystery and a one-line
   fix. The interesting case is humidity `0.81`: it passes 0–100 bounds
   cleanly and only the signature notices it is a fraction.
3. **Series structure.** *Degeneracy* -- 24 identical hourly values means a
   selector matched one node and the loop read it 24 times; real days are never
   perfectly flat. *Discontinuity* -- an 8 °C hour-to-hour step is not
   meteorology, it is a row misalignment.
4. **Continuity.** The temperature did not move 20 degrees since the fetch
   twenty minutes ago. Weak alone, and the allowance grows with the gap so a
   long outage never trips it. Its job is catching the parser that broke
   *between* two fetches, where every other check sees a self-consistent page.
5. **Internal coherence.** The four above look at one value, or one series.
   None can catch fields that are each individually perfect and jointly
   nonsense -- a headline condition describing midnight beside an hourly
   column describing now. That only shows when two fields are held up against
   each other, and it is the failure that actually shipped.

One more check, corroboration against an independent model, used to live here
and to *reject* a source that diverged too far. It was removed when the third
source arrived: with all three temperatures on screen the user can see a
disagreement directly, and an app that silently substitutes a different source
is making a decision behind their back. The deltas are still computed --
`service._record_divergence` -- but they inform rather than decide.

No single check is sufficient. Together they are hard to fool, because a broken
parser would have to produce a value that is simultaneously in range, in the
right unit, smooth, and close to what we saw twenty minutes ago.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from itertools import pairwise

from .models import Current, Day, Hour
from .series import covering

log = logging.getLogger(__name__)

# field -> (low, high, unit label)
RANGES: dict[str, tuple[float, float, str]] = {
    "temp_c": (-70.0, 60.0, "°C"),
    "feels_like_c": (-90.0, 70.0, "°C"),
    "pressure_mmhg": (600.0, 820.0, "мм рт. ст."),
    "humidity_pct": (0.0, 100.0, "%"),
    "wind_ms": (0.0, 80.0, "м/с"),
    "uv_index": (0.0, 15.0, "UV"),
    "water_temp_c": (-2.0, 45.0, "°C"),
    # The Kp index is defined on a 0-9 scale and cannot be anything else, which
    # makes it the tightest contract in the table: a cell misread into it fails
    # almost every time.
    "kp_index": (0.0, 9.0, "Kp"),
    # A day, not an hour. The wettest days on record are a few hundred
    # millimetres; the bound is there to catch a pressure or a timestamp
    # arriving in this field, not to have an opinion about monsoons.
    "precip_mm": (0.0, 500.0, "мм"),
    "snow_cm": (0.0, 200.0, "см"),
    "snow_depth_cm": (0.0, 1000.0, "см"),
    # This one was found by the test that asserts every numeric field on a
    # `Day` has a contract, on the first run of that test. `precip_prob` has
    # been on the model since the beginning and had never been checked -- a
    # source reporting a fraction (0.4 for 40%) or a millimetre count in it
    # would have gone straight to the screen.
    "precip_prob": (0.0, 100.0, "%"),
}


@dataclass
class Report:
    dropped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def drop(self, field_name: str, why: str) -> None:
        self.dropped.append(field_name)
        self.warnings.append(f"{field_name}: {why}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.dropped and not self.warnings


# --- 2. unit signatures ----------------------------------------------------

def unit_signature(field_name: str, value: float) -> str | None:
    """Name the unit this value *looks* like, when that isn't the one we want."""
    if field_name in ("temp_c", "feels_like_c", "water_temp_c"):
        if 600 <= value <= 820:
            return "looks like pressure in mmHg"
        if 900 <= value <= 1100:
            return "looks like pressure in hPa"
        if 200 <= value <= 350:
            return "looks like a temperature in kelvin"
        if 60 < value <= 130:
            return "looks like a temperature in fahrenheit"
    if field_name == "pressure_mmhg":
        if 900 <= value <= 1100:
            return "looks like hPa, not mmHg"
        if -100 <= value <= 100:
            return "looks like a temperature, not a pressure"
    # Passes the 0-100 bounds cleanly. Only the signature sees it.
    if field_name == "humidity_pct" and 0 < value < 1:
        return "looks like a fraction, not a percentage"
    if field_name == "wind_ms" and 90 <= value <= 400:
        return "looks like a wind *bearing* in degrees, not a speed"
    return None


def check_value(field_name: str, value: float | None, rep: Report,
                where: str = "", contract: str | None = None) -> float | None:
    """Range contract plus unit signature. Returns the value or None.

    `contract` names the rule to apply when it differs from the field being
    checked: a day's `feels_max_c` is a feels-like temperature and should be
    judged as one, but a report saying `feels_like_c: 743` when the field is
    called `feels_max_c` sends the next reader to the wrong line. The rule and
    the label are two different things and this keeps them apart.
    """
    if value is None:
        return None
    label = f"{where}{field_name}" if where else field_name
    rule = contract or field_name
    bounds = RANGES.get(rule)
    sig = unit_signature(rule, value)
    if bounds is not None:
        low, high, unit = bounds
        if not (low <= value <= high):
            why = sig or f"outside {low}..{high} {unit}"
            rep.drop(label, f"{value} {why}")
            return None
    if sig is not None:
        rep.drop(label, f"{value} {sig}")
        return None
    return value


def validate_current(cur: Current | None, rep: Report) -> Current | None:
    if cur is None:
        return None
    for f in ("temp_c", "feels_like_c", "pressure_mmhg", "humidity_pct", "wind_ms"):
        setattr(cur, f, check_value(f, getattr(cur, f), rep))
    return cur


# Every numeric field on a `Day`, against the contract it has to satisfy. A
# table rather than twenty lines of `check_value`, because the failure mode
# being guarded against is *forgetting an entry* -- and a list is something you
# can read against the dataclass in one glance, which twenty scattered calls
# are not. `tests/test_invariants.py` asserts the two stay in step.
DAY_CONTRACTS: tuple[tuple[str, str], ...] = (
    ("temp_min_c", "temp_c"), ("temp_max_c", "temp_c"),
    ("feels_min_c", "feels_like_c"), ("feels_max_c", "feels_like_c"),
    ("avg_temp_c", "temp_c"), ("water_temp_c", "water_temp_c"),
    ("humidity_pct", "humidity_pct"),
    ("pressure_min_mmhg", "pressure_mmhg"), ("pressure_max_mmhg", "pressure_mmhg"),
    ("wind_ms", "wind_ms"), ("wind_gust_ms", "wind_ms"),
    ("precip_mm", "precip_mm"), ("snow_cm", "snow_cm"),
    ("snow_depth_cm", "snow_depth_cm"),
    ("uv_index", "uv_index"), ("kp_index", "kp_index"),
    ("precip_prob", "precip_prob"),
)

# The same idea for a part of a day. Separate table because the fields are not
# the same shape -- a part carries one temperature where a day carries a range
# -- and because a `DayPart` is validated four times per day per source, so
# what it checks is worth being able to read on its own.
PART_CONTRACTS: tuple[tuple[str, str], ...] = (
    ("temp_c", "temp_c"), ("feels_like_c", "feels_like_c"),
    ("humidity_pct", "humidity_pct"), ("pressure_mmhg", "pressure_mmhg"),
    ("wind_ms", "wind_ms"), ("wind_gust_ms", "wind_ms"),
    ("precip_mm", "precip_mm"),
)

# And for one hour. Same argument a third time: a numeric field with no entry
# here is served unchecked, and `tests/test_invariants.py` walks all three
# dataclasses against all three tables so adding a field to any of them without
# a contract fails rather than passes quietly.
HOUR_CONTRACTS: tuple[tuple[str, str], ...] = (
    ("temp_c", "temp_c"), ("feels_like_c", "feels_like_c"),
    ("precip_mm", "precip_mm"), ("precip_prob", "precip_prob"),
    ("wind_ms", "wind_ms"), ("wind_gust_ms", "wind_ms"),
)


def validate_days(days: list[Day], rep: Report) -> list[Day]:
    out: list[Day] = []
    for d in days:
        for name, contract in DAY_CONTRACTS:
            setattr(d, name, check_value(name, getattr(d, name), rep,
                                         where=f"{d.date} ", contract=contract))
        for p in d.parts:
            for name, contract in PART_CONTRACTS:
                setattr(p, name, check_value(name, getattr(p, name), rep,
                                             where=f"{d.date}/{p.name} ",
                                             contract=contract))
        if d.parts or d.temp_max_c is not None:
            out.append(d)
    # Fewer than three days is a parse failure dressed as a short list.
    if days and len(out) < 3:
        rep.warn(f"only {len(out)} forecast days survived validation")
    return out


# --- 3. series structure ---------------------------------------------------

def check_series(hours: list[Hour], rep: Report,
                 max_step_c: float = 8.0) -> list[Hour]:
    for h in hours:
        for name, contract in HOUR_CONTRACTS:
            setattr(h, name, check_value(name, getattr(h, name), rep,
                                         where=f"{h.time} ", contract=contract))

    temps = [h.temp_c for h in hours if h.temp_c is not None]
    if len(temps) >= 6:
        if len(set(temps)) == 1:
            rep.warn(
                f"hourly degeneracy: {len(temps)} identical values ({temps[0]}°) "
                "-- a selector probably matched one node and was read N times"
            )
            return []
        worst = max(abs(b - a) for a, b in pairwise(temps))
        if worst > max_step_c:
            rep.warn(
                f"hourly discontinuity: {worst:.1f}° step between adjacent hours "
                "-- that is a row misalignment, not meteorology"
            )
    return hours


def check_daily_series(days: list[Day], rep: Report) -> None:
    maxes = [d.temp_max_c for d in days if d.temp_max_c is not None]
    if len(maxes) >= 5 and len(set(maxes)) == 1:
        rep.warn(f"daily degeneracy: every day has the same high ({maxes[0]}°)")

    # A ten-day forecast is ten *consecutive* days, and the failure this
    # catches has no other symptom: dates that repeat or jump mean some columns
    # were dated from their own label and the rest were counted from our clock,
    # so a row is showing one day's weather under another day's heading. Every
    # number in it is real, which is why nothing else here would object.
    dates = [d.date for d in days if d.date]
    if len(dates) >= 2:
        gaps = {(dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
                for a, b in pairwise(dates)}
        if gaps - {1}:
            rep.warn(
                f"daily dates are not consecutive ({sorted(gaps)} day steps) -- "
                f"some columns were dated from the page and some from the clock")


# --- 4. continuity ---------------------------------------------------------

def check_continuity(now_c: float | None, last_c: float | None,
                     gap_s: int, rep: Report) -> bool:
    """Did the temperature move further than time allows?

    The allowance grows with the gap, so a long outage never trips this. Ten
    degrees of headroom plus three per elapsed hour is loose enough for a real
    frontal passage and tight enough to notice a parser that started reading
    the humidity.
    """
    if now_c is None or last_c is None or gap_s <= 0:
        return False
    allowance = 10.0 + 3.0 * (gap_s / 3600.0)
    moved = abs(now_c - last_c)
    if moved > allowance:
        rep.warn(
            f"temperature moved {moved:.1f}° in {gap_s // 60} min "
            f"(allowance {allowance:.1f}°) -- suspect the parser, not the sky"
        )
        return True
    return False


# --- 5. internal coherence -------------------------------------------------

def check_coherence(cur: Current | None, hours: list[Hour], days: list[Day],
                    rep: Report, tz: str = "UTC") -> None:
    """Does this source agree with *itself*?

    The four layers above each look at one value, or at one series. Between
    them they will catch a temperature that is impossible, that is secretly a
    pressure, that repeats twenty-four times, or that jumped twenty degrees
    since the last fetch. None of them can catch the failure that actually
    shipped here: a headline reading «Малооблачно, туман» beside an hourly
    column for the same instant reading «Безоблачно», because the headline was
    quietly describing midnight and the column was describing now.

    Every number involved was in range, in the right unit, in a well-formed
    series, and continuous. The fields were individually perfect and jointly
    nonsense, and the only place that shows is when you hold two of them up
    against each other.

    It warns rather than drops, deliberately. Two fields disagreeing is
    evidence about the *parser*, not about the sky, and this codebase does not
    silently overrule an upstream -- see `DECISIONS.md` §4. The warning lands
    in `/api/health`, which is where a human decides.
    """
    if cur is None:
        return

    at = covering(hours, cur.observed_epoch, tz)
    if at is not None:
        if (cur.temp_c is not None and at.temp_c is not None
                and abs(cur.temp_c - at.temp_c) > COHERENCE_TEMP_C):
            rep.warn(
                f"current {cur.temp_c:+.0f}° disagrees with the {at.time} column "
                f"({at.temp_c:+.0f}°) covering the same moment -- one of them is "
                f"reading the wrong cell")
        if cur.icon and at.icon and _family(cur.icon) != _family(at.icon):
            rep.warn(
                f"current condition {cur.icon!r} disagrees with the {at.time} "
                f"column ({at.icon!r}) covering the same moment")

    today = days[0] if days else None
    if (today is not None and cur.temp_c is not None
            and today.temp_min_c is not None and today.temp_max_c is not None):
        low = today.temp_min_c - COHERENCE_DAY_SLACK_C
        high = today.temp_max_c + COHERENCE_DAY_SLACK_C
        if not (low <= cur.temp_c <= high):
            rep.warn(
                f"current {cur.temp_c:+.0f}° sits outside today's own range "
                f"{today.temp_min_c:+.0f}..{today.temp_max_c:+.0f}° -- the two "
                f"came from the same page and should not disagree")


# Two degrees between a headline and the hour covering it is ordinary rounding
# and a different observation minute. Five is a different cell.
COHERENCE_TEMP_C = 5.0
# A daily min/max is a forecast and the current reading is an observation, so
# they may legitimately part company at the edges of the day.
COHERENCE_DAY_SLACK_C = 4.0

# Icons that describe the same *kind* of weather. Comparing exact keys would
# fire on `rain` versus `rain-light`, which is a disagreement about degree and
# not about what is happening.
_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("clear", "clear-night"),
    ("partly", "partly-night", "cloudy", "cloudy-night"),
    ("overcast", "fog"),
    ("drizzle", "rain-light", "rain", "rain-heavy"),
    ("snow-light", "snow", "snow-heavy", "sleet", "hail"),
    ("thunder",),
)


def _family(icon: str) -> str:
    for group in _FAMILIES:
        if icon in group:
            return group[0]
    return icon


