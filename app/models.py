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
    DEGRADED = "degraded"   # serving, but something was dropped or substituted
    STALE = "stale"         # last good payload, upstream currently unusable
    DOWN = "down"           # nothing servable


class Source(str, Enum):  # noqa: UP042 - value goes straight to JSON
    YANDEX_HTML = "yandex_html"
    OPENMETEO = "openmeteo"
    CACHE = "cache"


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
    """One of night / morning / day / evening."""

    name: str
    temp_c: float | None = None
    feels_like_c: float | None = None
    condition: str | None = None
    icon: str | None = None
    humidity_pct: float | None = None
    pressure_mmhg: float | None = None
    wind_ms: float | None = None
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
    uv_index: float | None = None
    water_temp_c: float | None = None
    sunrise: str | None = None
    sunset: str | None = None
    daylight: str | None = None
    magnetic: str | None = None
    parts: list[DayPart] = field(default_factory=list)


@dataclass
class Hour:
    time: str                      # "21:00", or ISO when it came from Open-Meteo
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
    # and how far apart the sources landed. Surfaced by /api/health, never
    # rendered in the app.
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

    @property
    def view(self) -> SourceView | None:
        return self.sources.get(self.selected)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["health"]["status"] = self.health.status.value
        for key, sv in self.sources.items():
            d["sources"][key]["fallback_profile"] = sv.fallback_profile
        return d


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
