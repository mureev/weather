"""Yandex's page for **one** day of the ten.

`…/pogoda/ru/<slug>/details/auto/10-day-weather/day-<n>` is the only place any
source in this app publishes a single day at three-hourly resolution *with*
feels-like, gusts and precipitation probability attached to each column. The
ten-day page carries four parts of a day; this carries eight columns.

**Why it is fetched lazily.** One day is one URL, so ten days is ten requests
against the one this app spends per source per city per ten minutes. Fetching
them all on every refresh would multiply the app's whole upstream footprint to
deepen its least-thin source. So `/api/day` fetches exactly the day somebody
opened, caches it for the usual TTL, and the ten-day list keeps working
untouched when the fetch fails or the phone is offline — the four parts of day
are already in the main payload.

**Why the URL's day number is not trusted.** `day-5` is a position, and this
codebase has been bitten by positions often enough to have an invariant about
it (`CLAUDE.md` 12): the offset is computed from the date, the page is fetched,
and then the page's *own stated date* is checked against the date that was
asked for. A page that answers with a different day is rejected exactly the way
a page describing the wrong city is. Yandex ships that date as
`<time datetime="2026-08-07T00:00:00+03:00">`, which needs no interpretation.

**How it is read.** Every column carries a visually-hidden sentence that names
its own fields -- «днём: +18°, небольшой дождь, Ощущается как 18.» -- which is
the tier-2 mechanism the main Yandex parser already leans on, and the reason a
redesign here degrades rather than lies. The icon comes from Yandex's own sprite
code (`style="--icon:6"`), which encodes day and night, with the condition words
as the fallback.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from itertools import pairwise
from typing import Any

import httpx
from lxml import html as LH

from .. import ru_text as R
from ..config import settings
from ..models import Day, Hour, ParseError, Place, Tier
from . import yandex_html

log = logging.getLogger(__name__)

# How far ahead this page exists. Yandex serves ten days; asking for more gets
# a redirect or a page about a different day, and the date check below would
# reject it anyway -- but refusing here saves the request.
MAX_OFFSET = 9

_A11Y = 'contains(@class,"visuallyHidden")'
_ITEM = 'contains(@class,"block__item__")'
_BLOCK = 'contains(@class,"AppDetailedForecastBlock_block__")'


def url_for(place: Place, offset: int, host: str | None = None) -> str | None:
    """The page for `offset` days from today, or None if we cannot address it.

    Only by slug. A GPS fix has no slug, and `/pogoda/?lat=&lon=` has no
    per-day equivalent -- so an ad-hoc place simply has no detail page, and the
    caller shows what the main payload already carries.
    """
    if place.ad_hoc or not place.path or not 0 <= offset <= MAX_OFFSET:
        return None
    host = (host or settings.yandex_host).rstrip("/")
    return (f"{host}/pogoda/ru/{place.path}"
            f"/details/auto/10-day-weather/day-{offset}")


async def load(client: httpx.AsyncClient, place: Place, want: dt.date,
               *, today: dt.date) -> Day:
    """Fetch and parse the page for `want`, or raise."""
    offset = (want - today).days
    url = url_for(place, offset)
    if url is None:
        raise ParseError(f"no per-day page for {place.slug!r} at {want}")
    html_text = await yandex_html.fetch_html(client, url)
    return parse(html_text, want=want)


def parse(html_text: str, *, want: dt.date) -> Day:
    if R.looks_like_captcha(html_text):
        raise ParseError("yandex day page looks like a captcha")
    doc = LH.fromstring(html_text)

    stamps = _stamps(doc)
    if not stamps:
        raise ParseError("no column timestamps on the day page")
    stated = stamps[0].date()
    if stated != want:
        # The same rejection as a page describing the wrong city, for the same
        # reason: everything on it parses, and all of it is about another day.
        raise ParseError(f"asked for {want}, page describes {stated}")

    day = Day(date=stated.isoformat())
    _astronomy(doc, day)

    cols = _columns(doc)
    for i, when in enumerate(stamps):
        hour = Hour(time=when.isoformat(timespec="minutes"),
                    at=int(when.timestamp()))
        _fill(hour, cols, i)
        day.hours.append(hour)
    if not any(h.temp_c is not None for h in day.hours):
        raise ParseError("day page parsed but carries no temperatures")
    return day


def _stamps(doc: Any) -> list[dt.datetime]:
    """The eight column instants, deduplicated and in order.

    The whole block renders twice -- wide and narrow layouts -- which is the
    same trap that once turned a ten-day forecast into twenty days. Dedupe on
    the value rather than slicing to eight, so a page that starts publishing
    twelve columns gains detail instead of losing it.
    """
    out: list[dt.datetime] = []
    seen: set[str] = set()
    for node in doc.xpath("//time[@datetime]"):
        raw = node.get("datetime") or ""
        if raw in seen:
            continue
        try:
            when = dt.datetime.fromisoformat(raw)
        except ValueError:
            continue
        seen.add(raw)
        out.append(when)
    return out


def _columns(doc: Any) -> dict[str, list[Any]]:
    """Each labelled block's eight cells, keyed by what the block is about.

    Keyed by the block's own Russian heading, except the temperature strip,
    which has no heading and is recognised by the one thing it always contains:
    a per-cell weather icon. Position is not used -- there are fifty-four
    blocks on the page and most of them are empty spacers.
    """
    out: dict[str, list[Any]] = {}
    for block in doc.xpath(f"//*[{_BLOCK}]"):
        cls = block.get("class") or ""
        if any(k in cls for k in ("block__items__", "block__item__",
                                  "block__title")):
            continue
        cells = block.xpath(f".//*[{_ITEM}]")
        if not cells:
            continue
        head = block.xpath('./*[contains(@class,"block__title")]')
        if head:
            key = R.clean(head[0].text_content()).lower().split(",")[0]
        elif cells[0].xpath('.//*[contains(@class,"weatherIcon")]'):
            key = "температура"
        else:
            continue
        # First wins: the duplicate render is identical, and taking the first
        # means a partially-hydrated second copy can never overwrite a good one.
        out.setdefault(key, cells)
    return out


def _fill(hour: Hour, cols: dict[str, list[Any]], i: int) -> None:
    temp = _cell(cols, "температура", i)
    if temp is not None:
        prose = R.clean(" ".join(
            n.text_content() for n in temp.xpath(f".//*[{_A11Y}]")))
        # Feels-like is pulled out *by its label first* and removed, so the
        # remaining first temperature is unambiguously the air temperature.
        # The other way round works on the fixture and breaks the day Yandex
        # reorders the clause -- the main parser learned this already.
        m = re.search(r"ощущается\s+как\s*([^,.]+)", prose, re.I)
        rest = prose[: m.start()] + " " + prose[m.end():] if m else prose
        if m:
            # «Ощущается как 18.» -- a bare number, with no degree sign, unlike
            # every other temperature Yandex writes. `R.temperature` requires
            # the °, correctly, so it returns None here and the field looked
            # like one the page does not publish. Both readings are tried and
            # both handle U+2212, which is the part that actually matters.
            said = m.group(1)
            hour.feels_like_c = R.temperature(said)
            if hour.feels_like_c is None:
                hour.feels_like_c = R.to_float(said)
        hour.temp_c = R.temperature(rest)
        hour.condition = R.condition(rest)
        if hour.condition:
            hour.condition = R.sentence(hour.condition)
        icon = temp.xpath('.//*[contains(@class,"weatherIcon")]/@style')
        hour.icon = (R.icon_from_yandex(icon[0]) if icon else None) \
            or R.icon_key(hour.condition)
        prob = temp.xpath('.//*[contains(@class,"precProbability")]')
        if prob:
            hour.precip_prob = R.humidity_pct(prob[0].text_content())

    wind = _cell(cols, "ветер", i)
    if wind is not None:
        # «, 2,2 Метров в секунду, до 3 Метров в секунду, юго-западный.» The
        # visible cell says only "2,2"; the sentence beside it carries the gust
        # and the direction, and spells its units out rather than using м/с.
        prose = R.clean(" ".join(
            n.text_content() for n in wind.xpath(f".//*[{_A11Y}]")))
        speeds = [R.to_float(v) for v in
                  re.findall(r"(?<![\d.,])(\d{1,2}(?:[.,]\d)?)\s*Метр", prose)]
        speeds = [v for v in speeds if v is not None]
        if speeds:
            hour.wind_ms = speeds[0]
            if len(speeds) > 1:
                hour.wind_gust_ms = speeds[1]
        else:
            hour.wind_ms = R.to_float(R.clean(wind.text_content()))
        hour.wind_dir = R.wind_dir(prose)


def _cell(cols: dict[str, list[Any]], key: str, i: int) -> Any | None:
    cells = cols.get(key) or []
    return cells[i] if i < len(cells) else None


def _astronomy(doc: Any, day: Day) -> None:
    """Sunrise, sunset and day length, from the small table above the columns.

    Read by label rather than by position: the three sit in one flat run of
    cells, and reading them as first/second/third would silently swap two of
    them the day a fourth is added.
    """
    for table in doc.xpath('//*[contains(@class,"AppDetailsCard_table")]'):
        cells = [R.clean(t) for t in table.itertext() if R.clean(t)]
        for label, value in pairwise(cells):
            low = label.lower()
            if low.startswith("восход") and not day.sunrise:
                day.sunrise = value
            elif low.startswith("закат") and not day.sunset:
                day.sunset = value
            elif low.startswith("световой") and not day.daylight:
                day.daylight = value


def provenance() -> dict[str, int]:
    """Flat, and honestly so: everything here comes from the same rung.

    The columns are found by their block headings and read from self-labelling
    accessibility prose -- tier 2 throughout. There is no embedded JSON on this
    page to fall back from, and no shape-classified reading to fall back to, so
    a redesign takes the whole page rather than degrading it. That is worth
    saying in `/api/health` rather than implying a ladder that is not there.
    """
    return {"day_detail": int(Tier.LABELLED)}
