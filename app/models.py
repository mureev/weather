"""The normalized wire format.

The front end has no idea which source produced any given number. That
indirection is the whole maintainability story: when Yandex redesigns their
front end -- not if -- one parser changes and nothing downstream notices.

Every optional field is genuinely optional. A value that failed validation is
`None`, never a clamped stand-in, because a clamped 743 becomes a plausible
+55 and that is strictly worse than a blank.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Tier(int, Enum):
    """Which rung of the extraction ladder answered for a field."""

    NAMED = 1        # a named element matched -- the layout is where we left it
    LABELLED = 2     # found by its Russian label's neighbourhood
    SHAPE = 3        # found by content shape over the whole page
    ABSENT = 9       # nothing answered


class Status(str, Enum):  # noqa: UP042 - value goes straight to JSON
    OK = "ok"
    DEGRADED = "degraded"   # serving, but a source is out, a field dropped or a check warned
    STALE = "stale"         # last good payload, upstream currently unusable
    DOWN = "down"           # nothing servable


@dataclass
class Place:
    slug: str
    name: str            # Russian nominative, e.g. "Йошкар-Ола"
    lat: float
    lon: float
    yandex_slug: str | None = None
    tz: str = "Europe/Moscow"
    # True when this place came from a GPS fix rather than the registry.
    ad_hoc: bool = False
    # For the English interface: "Yoshkar-Ola". Spelled by hand for the
    # registry, by the geocoder for a search hit, else `ru_text.latin(name)`.
    name_en: str | None = None

    @property
    def path(self) -> str | None:
        return self.yandex_slug or self.slug


@dataclass
class Current:
    temp_c: float | None = None
    feels_like_c: float | None = None
    condition: str | None = None
    icon: str | None = None
    humidity_pct: float | None = None
    pressure_mmhg: float | None = None
    wind_ms: float | None = None
    wind_dir: str | None = None
    observed_at: str | None = None      # as the source words it, for display
    # The same moment as a UTC epoch, when the source gives one. Separate from
    # `observed_at` because that field is whatever the page happened to say --
    # an ISO stamp from one source, a formatted local time from another -- and
    # code that has to line two series up needs a number, not prose.
    observed_epoch: int | None = None


@dataclass
class DayPart:
    """One of night / morning / day / evening.

    Two sources fill these and they do not agree on the order, which is left
    alone on purpose: Yandex prints morning first and means the night that
    *follows* the day, Gismeteo prints night first and means the one that
    starts it. Sorting them into a canonical order would silently move one
    source's forecast by twenty-four hours. The source knows what its own
    columns are; we keep them in the order it published them.
    """

    name: str
    temp_c: float | None = None
    feels_like_c: float | None = None
    condition: str | None = None
    icon: str | None = None
    humidity_pct: float | None = None
    pressure_mmhg: float | None = None
    wind_ms: float | None = None
    wind_gust_ms: float | None = None
    wind_dir: str | None = None
    precip_mm: float | None = None


@dataclass
class Hour:
    time: str                      # "21:00" from a strip; ISO from Open-Meteo or a day page
    # The instant this entry describes, as a UTC epoch, when the source gives
    # one. A bare "21:00" cannot say which side of midnight it falls on, and
    # every attempt to infer that from position has been wrong at least once
    # here -- so where the page ships a real timestamp we keep it, and where it
    # does not we say so by leaving this `None` rather than guessing.
    at: int | None = None
    temp_c: float | None = None
    feels_like_c: float | None = None
    condition: str | None = None
    icon: str | None = None
    precip_mm: float | None = None
    precip_prob: float | None = None
    wind_ms: float | None = None
    wind_gust_ms: float | None = None
    wind_dir: str | None = None


@dataclass
class Day:
    date: str                      # ISO yyyy-mm-dd
    title: str | None = None    # "Сегодня, 31 июля"
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    condition: str | None = None
    icon: str | None = None
    precip_prob: float | None = None
    # Everything below is for the day-detail screen. All of it was already
    # being downloaded -- Gismeteo publishes a row per metric on the ten-day
    # page we fetch, and Open-Meteo returns them for the asking -- and all of
    # it was being dropped on the floor.
    #
    # Pressure is a *range* rather than a number because that is what the
    # source publishes, and picking one end of it to call "the pressure" is the
    # kind of small invention this codebase spends its comments avoiding.
    precip_mm: float | None = None
    feels_min_c: float | None = None
    feels_max_c: float | None = None
    avg_temp_c: float | None = None
    humidity_pct: float | None = None
    pressure_min_mmhg: float | None = None
    pressure_max_mmhg: float | None = None
    wind_ms: float | None = None
    wind_gust_ms: float | None = None
    wind_dir: str | None = None
    snow_cm: float | None = None
    snow_depth_cm: float | None = None
    kp_index: float | None = None
    uv_index: float | None = None
    water_temp_c: float | None = None
    sunrise: str | None = None
    sunset: str | None = None
    daylight: str | None = None
    magnetic: str | None = None
    parts: list[DayPart] = field(default_factory=list)
    # Hours belonging to *this day*, when a source publishes a page per day.
    # Empty in the main payload -- the flat `SourceView.hourly` series is what
    # the strip reads -- and filled only by `/api/day`, which is fetched when
    # somebody actually opens a day. Pruned from the wire when empty, so a day
    # that has none costs nothing to say so.
    hours: list[Hour] = field(default_factory=list)


@dataclass
class SourceView:
    """One source's complete answer, standing on its own.

    Three of these ride in every payload. The switcher in the UI picks between
    them client-side, so changing source is instant and costs no request -- and,
    more to the point, you are comparing three readings taken at the same
    moment rather than three taken as you tapped.
    """

    key: str                                    # yandex | gismeteo | openmeteo
    label: str                                  # what the tab says
    available: bool = False
    # Why not, in Russian, when available is False. Shown on the disabled tab.
    reason: str | None = None
    current: Current | None = None
    hourly: list[Hour] = field(default_factory=list)
    daily: list[Day] = field(default_factory=list)
    nowcast: str | None = None
    # field name -> tier that answered. An all-tier-3 profile means the layout
    # moved and the numbers are about to start being wrong. That is a warning
    # worth having on a calm day.
    provenance: dict[str, int] = field(default_factory=dict)
    dropped_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # The full text behind `reason`: URLs tried, exceptions, the validator's
    # verdicts, the Gismeteo route. For the debug token only -- see
    # `Weather.to_dict`.
    detail: list[str] = field(default_factory=list)

    @property
    def fallback_profile(self) -> bool:
        vals = [v for v in self.provenance.values() if v != Tier.ABSENT]
        return bool(vals) and all(v >= Tier.SHAPE for v in vals)


@dataclass
class Health:
    status: Status = Status.OK
    # Shown to the user, in Russian, short enough to read on a phone.
    warnings: list[str] = field(default_factory=list)
    # For whoever is debugging: URLs tried, exceptions, validator verdicts,
    # which route reached Gismeteo, and how far apart the sources landed.
    # Sent only with the debug token (`Weather.to_dict`), and never rendered
    # in the app.
    detail: list[str] = field(default_factory=list)
    # Pairwise temperature deltas, e.g. {"yandex/openmeteo": 0.6}. Recorded
    # because it is the single most useful number when debugging a suspected
    # mis-parse -- but it no longer *decides* anything. With three sources on
    # screen you can see the disagreement yourself, and an app that silently
    # overrides your explicit choice of source is worse than one that shows
    # you a number you can judge.
    divergence_c: dict[str, float] = field(default_factory=dict)
    age_s: int = 0


@dataclass
class Weather:
    """The envelope. Every source, every time."""

    place: Place
    fetched_at: str
    selected: str = "yandex"
    sources: dict[str, SourceView] = field(default_factory=dict)
    health: Health = field(default_factory=Health)
    # Is it dark in the city right now. A property of the moment and the place,
    # so it lives on the envelope rather than on any one source -- all three
    # would otherwise have to agree about it, and they have no idea.
    #
    # It exists because only `clear`, `partly` and `cloudy` have night forms of
    # their icon: rain at midnight is still spelled `rain`, and the front end
    # was lighting its drops for noon. Derived from solar position by `sun.py`
    # like everything else here, never from "the hour looks late" -- this is
    # Yoshkar-Ola, where June is light at eleven and December is dark at four.
    night: bool = False

    def to_dict(self, *, detail: bool = False) -> dict[str, Any]:
        """The envelope as it goes on the wire.

        `health.detail` and every source's `detail` stay behind unless asked
        for, and off is the default so that a new caller has to ask. They are
        the server's notes to itself -- an exception's text, the URL it was
        fetching, the route that reached Gismeteo, which names a proxy by host
        and port when one is in use -- and this goes to every phone and to
        anyone else who asks. Nothing in `static/` reads them: the app shows
        `warnings` and each tab's short `reason`. `/api/weather` asks for them
        when the request carries the debug token (`DECISIONS.md` §38).
        """
        d = prune(asdict(self))
        d["health"]["status"] = self.health.status.value
        if not detail:
            d["health"].pop("detail", None)
        for key, sv in self.sources.items():
            d["sources"][key]["fallback_profile"] = sv.fallback_profile
            if not detail:
                d["sources"][key].pop("detail", None)
        return d


def prune(value: Any) -> Any:
    """Drop `None`-valued keys on the way out.

    A `Day` now has twenty-odd optional fields and no source fills more than
    half of them, so the literal text `"snow_depth_cm": null,` was being shipped
    ten times per source per fetch. The client already reads every one of these
    with `!= null`, and in JavaScript a missing key reads back as `undefined`,
    for which `undefined != null` is *false* -- so an absent key and a null one
    are the same answer to every question the front end asks.

    Empty lists and strings stay. `dropped_fields: []` is a statement that
    nothing was dropped, and `warnings: []` is what the renderer iterates; an
    absent list would be a different fact wearing the same clothes.
    """
    if isinstance(value, dict):
        return {k: prune(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [prune(v) for v in value]
    return value


class ParseError(RuntimeError):
    """Raised rather than returning zero.

    A scraper that returns 0 will show you +0 degrees in January and you will
    believe it.
    """


class Blocked(ParseError):
    """We were refused, rather than misunderstood.

    The distinction is load-bearing once there is more than one way out to the
    internet. A `ParseError` means the page arrived and the parser could not
    read it -- fetching the identical page down a different route reproduces it
    exactly, so retrying is pure waste and hides a real breakage behind a
    timeout. A `Blocked` means *this exit address* was refused, which is the
    one failure another route can actually fix.

    A 403 arrives as `httpx.HTTPStatusError` and is treated the same way; this
    exists for the polite refusals that come back as 200 with a challenge page
    in the body, which would otherwise look like a parser bug.
    """
