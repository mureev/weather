"""Gismeteo — the second source.

**Addressing.** `gismeteo.ru/robots.txt` disallows `/*?*` — every URL carrying a
query string — and `/ajax` besides. So the only permitted way in is the clean
path form `/weather-<slug>-<id>/`, and that numeric id is not derivable from
anything we know about a place. Ids for the built-in cities are below;
`GISMETEO_IDS` adds more by hand.

When we have no id, this source reports itself unavailable and its tab is
disabled with a reason. It does **not** substitute a nearby city we do have an
id for. Showing Cheboksary's numbers under a heading that says Yoshkar-Ola is
precisely the wrong-city failure the rest of this codebase exists to prevent;
doing it to ourselves deliberately would be worse than having Yandex do it to
us by accident.

**Parsing** turned out to be the easiest of the three, and for a pleasant
reason: Gismeteo's markup is *typed*.

* `window.M.state` is a plain JSON object holding `weather.cw` — current
  conditions as parallel single-element arrays (`temperatureAir: [15]`,
  `pressure: [748]`, `windDirection: [311]`) — and a `city` block carrying id,
  slug **and coordinates**, which makes the identity check numeric rather than
  a string comparison against an inflected Russian heading.
* Forecast temperatures live in custom elements: `<temperature-value
  value="21" from-unit="c">`. An attribute, already signed, already a number.
  The U+2212 trap that dominates the Yandex parser simply cannot occur here.
* Hours are `<time-value timestamp="1785445200">` — Unix seconds, converted
  using the city's own `timeZone` offset rather than the server's clock.
* Conditions are `data-tooltip="малооблачно, дождь, туман"` on each column.

Their CSS class names are also *not* hashed — `widget-row-wind`,
`widget-row-icon` — so tier 3 has something durable to match on, unlike Yandex
where every class carries a per-build suffix.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
from typing import Any

import httpx
from lxml import html as LH

from .. import ru_text as R
from ..config import settings
from ..extract import Extracted, Identity, _balanced
from ..models import Blocked, Current, Day, DayPart, Hour, ParseError, Place, Tier
from ..series import covering

log = logging.getLogger(__name__)

# The default host, and its mirror. `meteofor.lv` is the same forecast service
# under its export brand: the same numeric city ids, the same `window.M.state`,
# the same values to the minute -- and, unlike `gismeteo.ru`, it answers a
# Latvian address. The full ordered list lives in `settings.gismeteo_host_list`
# and every entry is put through the identity check below like any other, so a
# mirror that quietly served a different town would be rejected, not believed.
HOST = "https://www.gismeteo.ru"

# slug -> gismeteo path segment ("<their-slug>-<id>"), harvested from their own
# catalogue pages. Every one is verified at request time by the identity check
# below, because an id that silently points at the wrong town is exactly the
# failure we cannot afford to take on trust.
PATHS: dict[str, str] = {
    "yoshkar-ola": "yoshkar-ola-11975",
    "cheboksary": "cheboksary-4361",
    "kazan": "kazan-4364",
    "nizhny-novgorod": "nizhny-novgorod-4355",
    "moscow": "moscow-4368",
    "saint-petersburg": "sankt-peterburg-4079",
}


def _load_extra() -> None:
    """`GISMETEO_IDS=slug:their-slug-id,...`

    A malformed entry is skipped with a warning rather than taking the source
    down — losing one city is annoying, refusing to serve any is worse.
    """
    for raw in filter(None, (p.strip() for p in
                             (settings.gismeteo_ids or "").split(","))):
        parts = raw.split(":")
        if len(parts) != 2 or not re.fullmatch(r"[a-z0-9-]+-\d+", parts[1].strip()):
            log.warning("GISMETEO_IDS: skipping malformed entry %r", raw)
            continue
        PATHS[parts[0].strip()] = parts[1].strip()


_load_extra()


def city_id(place: Place | None) -> str | None:
    if place is None or place.ad_hoc:
        return None
    return PATHS.get(place.slug)


def urls_for(place: Place, host: str = HOST) -> tuple[str, str, str, str] | None:
    """The four pages we read, on `host`: now, hourly, ten days, parts of day.

    Every mirror uses the identical `/weather-<slug>-<id>/` shape, which is why
    the host is a parameter and not a rewrite: nothing else about the address
    changes, including the id.

    The landing page carries an hourly strip, but a *three-hourly* one -- eight
    columns at 0:00, 3:00, 6:00 and so on. `/hourly/` is the same widget with
    every hour in it, which is the series worth having, so it is fetched
    separately and preferred when it parses.

    `/3-days/` is misnamed by its own URL and that is worth knowing before you
    look at it: it is a **ten-day** grid at four columns a day -- ночь, утро,
    день, вечер -- carrying the same fifteen metric rows as `/10-days/` but per
    part rather than per day. It is the richest page of the four and the only
    reason the day-detail screen can say anything about Thursday evening.
    """
    seg = city_id(place)
    if not seg:
        return None
    host = host.rstrip("/")
    base = f"{host}/weather-{seg}"
    return f"{base}/", f"{base}/hourly/", f"{base}/10-days/", f"{base}/3-days/"


def headers() -> dict[str, str]:
    """A request Chrome would plausibly have made.

    The first version of this sent `Upgrade-Insecure-Requests: 1` and a Chrome
    User-Agent but none of the `Sec-Fetch-*` family -- a combination real Chrome
    never produces, since those headers ship together on every navigation. To a
    WAF that reads as a script wearing a browser's name, and Gismeteo answered
    403 while plain `curl` from the same address got 200. Sending *fewer*
    headers was passing where sending *some* was not, which is the tell: it is
    the inconsistency being scored, not the volume.

    Nothing here derives from the phone. Not its Accept-Language, not its
    User-Agent, not its Referer, not its timezone.
    """
    return {
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Upgrade-Insecure-Requests": "1",
        # Present on every real Chrome navigation. Their absence beside the
        # header above is the thing that looked wrong.
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Chromium";v="126", "Not(A:Brand";v="24", '
                     '"Google Chrome";v="126"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "Cache-Control": "max-age=0",
    }


async def _optional(coro) -> str | None:
    """Await something we would like but can live without."""
    try:
        return await coro
    except Exception as e:
        log.info("gismeteo optional page unavailable: %s", e)
        return None


async def fetch_html(client: httpx.AsyncClient, url: str, *,
                     timeout: float | None = None) -> str:
    """One page. `timeout` overrides the default so a route search can give
    each candidate a slice of its budget rather than the whole thing."""
    r = await client.get(url, headers=headers(), follow_redirects=True,
                         timeout=timeout or settings.upstream_timeout_s)
    r.raise_for_status()
    return r.text


async def load(client: httpx.AsyncClient, place: Place, *,
               today: dt.date | None = None,
               timeout: float | None = None,
               host: str = HOST) -> tuple[Extracted, str]:
    urls = urls_for(place, host)
    if urls is None:
        raise ParseError(f"no gismeteo id for {place.slug!r}")
    now_url, hourly_url, days_url, parts_url = urls

    # Four pages, concurrently. Two of them are *optional*: each is an upgrade
    # on something we already have -- `/hourly/` refines a series the landing
    # page carries at three-hour resolution, `/3-days/` adds parts of day to a
    # ten-day list that stands perfectly well without them. Losing either
    # should cost detail, not the source.
    now_html, days_html, hourly_html, parts_html = await asyncio.gather(
        fetch_html(client, now_url, timeout=timeout),
        fetch_html(client, days_url, timeout=timeout),
        _optional(fetch_html(client, hourly_url, timeout=timeout)),
        _optional(fetch_html(client, parts_url, timeout=timeout)))

    got = parse(now_html, days_html=days_html, hourly_html=hourly_html,
                parts_html=parts_html, today=today)
    bad = check_identity(got.ident, place)
    if bad:
        raise ParseError(f"{now_url}: wrong place ({bad})")
    return got, now_url


# --- identity --------------------------------------------------------------

def check_identity(ident: Identity, place: Place) -> str | None:
    """Does this page describe the town we asked for?

    Coordinates first when the state blob gives them, because a numeric check
    needs no opinion about Russian declension. The heading fallback compares
    *stems*: the page says «Погода в Йошкар-Оле» (prepositional) for
    Йошкар-Ола (nominative), so a full-string comparison would reject every
    correct page.
    """
    expect = city_id(place)
    if expect and ident.geo_id is not None:
        want = int(expect.rsplit("-", 1)[1])
        if ident.geo_id != want:
            return f"asked for gismeteo id {want}, page says {ident.geo_id}"

    if ident.lat is not None and ident.lon is not None:
        if abs(ident.lat - place.lat) > 1.0 or abs(ident.lon - place.lon) > 2.0:
            return (f"asked for {place.lat},{place.lon}; page resolved to "
                    f"{ident.lat},{ident.lon}")
        return None

    hay = " ".join(x for x in (ident.h1, ident.title, ident.name) if x).lower()
    if not hay:
        return "page has neither <title> nor <h1>"
    stem = _stem(place.name)
    if stem and stem not in hay:
        return f"asked for {place.name!r}, page says {(ident.h1 or ident.title)!r}"
    return None


def _stem(name: str) -> str:
    """Drop the last two characters of the final word — enough to survive a
    Russian case ending without matching everything."""
    n = R.clean(name or "").lower()
    if not n:
        return ""
    head, _, tail = n.rpartition(" ")
    tail = tail[:-2] if len(tail) > 4 else tail
    return (head + " " + tail).strip() if head else tail


# --- the state blob --------------------------------------------------------

def state(html_text: str) -> dict | None:
    """`window.M.state = {...}` — Gismeteo's hydration payload."""
    m = re.search(r"window\.M\.state\s*=\s*", html_text)
    if not m:
        return None
    raw = _balanced(html_text, m.end())
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _col(cw: dict, key: str, i: int = 0) -> float | None:
    """`weather.cw` is columnar: every field is a list parallel to the others."""
    v = cw.get(key)
    if isinstance(v, list) and len(v) > i:
        v = v[i]
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


_DIRS = ("северный", "северо-восточный", "восточный", "юго-восточный",
         "южный", "юго-западный", "западный", "северо-западный")


def _bearing_to_ru(deg: float | None) -> str | None:
    if deg is None:
        return None
    return _DIRS[int((float(deg) + 22.5) % 360 // 45)]


# --- parsing ---------------------------------------------------------------

def parse(html_text: str, *, days_html: str | None = None,
          hourly_html: str | None = None, parts_html: str | None = None,
          today: dt.date | None = None) -> Extracted:
    if R.looks_like_captcha(html_text):
        # `Blocked`, not `ParseError`: a challenge page is a refusal wearing a
        # 200, and refusals are the one failure a different exit address can
        # fix. Calling it a parse failure would make the route search give up
        # on the first proxy that answers politely.
        raise Blocked("gismeteo: page looks like a captcha or block page")

    doc = LH.fromstring(html_text)
    st = state(html_text) or {}
    out = Extracted(ident=_identity(doc, st))

    cur, prov = _current(doc, st)
    out.current = cur
    out.provenance.update(prov)

    out.hourly, hprov, _hour_at = _hours(doc, st)
    out.provenance.update(hprov)

    if hourly_html:
        # Prefer whichever page yields more hours rather than trusting the
        # dedicated one blindly: if /hourly/ ever redesigns out from under the
        # parser, the landing page's three-hourly strip is still a forecast,
        # and silently serving nothing would be the worse outcome.
        fine, fprov, _fine_at = _hours(LH.fromstring(hourly_html), st)
        if len(fine) > len(out.hourly):
            out.hourly = fine
            out.provenance.update(fprov)

    if days_html:
        out.daily, dprov = _days(LH.fromstring(days_html),
                                 today=today or dt.date.today())
        out.provenance.update(dprov)

    if parts_html and out.daily:
        # Purely additive, and matched by date rather than by position: the two
        # pages are fetched in the same second but they are still two pages,
        # and a ten-day list starting on a different morning from a forty-cell
        # grid would otherwise hang every part of Tuesday off Monday.
        by_date, pprov = _parts(LH.fromstring(parts_html),
                                today=today or dt.date.today())
        out.provenance.update(pprov)
        for day in out.daily:
            day.parts = by_date.get(day.date, [])

    # The condition, last, because it is a lookup *into* the hourly series --
    # the column covering the moment the reading was taken. Doing it here
    # rather than inside `_current` is what makes the hero and the "now" column
    # the same fact by construction instead of two independent guesses that
    # happened to agree on the day the fixture was recorded.
    if out.current is not None:
        hit = covering(out.hourly, out.current.observed_epoch)
        if hit is not None and hit.condition:
            out.current.condition = hit.condition
            out.current.icon = hit.icon
            out.provenance["condition"] = int(Tier.LABELLED)

    if out.current is None or out.current.temp_c is None:
        # Raise rather than return zero. A scraper returning 0 shows +0° in
        # January and is believed; here it simply disables the tab.
        raise ParseError("gismeteo: no current temperature could be extracted")
    return out


def _identity(doc: Any, st: dict) -> Identity:
    ident = Identity()
    t = doc.xpath("//title/text()")
    ident.title = R.clean(t[0]) if t else None
    h1 = doc.xpath("//h1")
    ident.h1 = R.clean(h1[0].text_content()) if h1 else None
    can = doc.xpath('//link[@rel="canonical"]/@href')
    ident.canonical = can[0] if can else None

    city = st.get("city") if isinstance(st, dict) else None
    if isinstance(city, dict):
        ident.slug = city.get("slug")
        gid = city.get("id")
        ident.geo_id = int(gid) if isinstance(gid, int) else None
        coords = city.get("coordinates") or {}
        lat, lon = coords.get("latitude"), coords.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            ident.lat, ident.lon = float(lat), float(lon)

    if ident.geo_id is None and ident.canonical:
        m = re.search(r"/weather-([a-z0-9-]+?)-(\d+)/?", ident.canonical)
        if m:
            ident.slug = ident.slug or m.group(1)
            ident.geo_id = int(m.group(2))

    if ident.h1:
        m = re.match(r"\s*Погода\s+(?:в|во|на)\s+(.+)", ident.h1)
        ident.name = m.group(1).strip() if m else ident.h1
    return ident


def _current(doc: Any, st: dict) -> tuple[Current | None, dict[str, int]]:
    cur = Current()
    prov: dict[str, int] = {}

    cw = ((st.get("weather") or {}).get("cw") or {}) if isinstance(st, dict) else {}
    if cw:
        for attr, key in (("temp_c", "temperatureAir"),
                          ("feels_like_c", "temperatureFeelsLike"),
                          ("humidity_pct", "humidity"),
                          ("pressure_mmhg", "pressure"),
                          ("wind_ms", "windSpeed")):
            v = _col(cw, key)
            if v is not None:
                setattr(cur, attr, v)
                prov[attr] = int(Tier.NAMED)
        bearing = _col(cw, "windDirection")
        if bearing is not None:
            cur.wind_dir = _bearing_to_ru(bearing)
            prov["wind_dir"] = int(Tier.NAMED)

    # When the observation was taken. Load-bearing, not decoration: the
    # readable condition has to come from the strip (see below), and picking
    # the right column out of it is impossible without knowing what "now" is.
    obs = _col(cw, "date")
    if obs is not None:
        cur.observed_epoch = int(obs)

    # NOTE: the condition is deliberately *not* set here. It arrives in the
    # state blob as a translation key (`nebulosity.type.0`) with no dictionary
    # shipped on the page, so the readable text has to come from a column
    # tooltip -- and *which* column is the whole question. `parse` fills it in
    # once the hourly series exists, from the column covering `observed_at`.
    #
    # It used to take the first tooltip on the page, which is the strip's
    # leftmost column: midnight. On this file's own fixture that put a
    # description of 00:00 next to a temperature observed at 23:00, and it went
    # unnoticed for the reason such things always do -- the fixture was
    # captured at 00:54, the one hour of the day when the two agree.

    if cur.temp_c is None:
        # Tier 3: the headline value as a typed attribute, wherever it sits.
        for tv in doc.xpath("//temperature-value[@value]")[:1]:
            v = R.to_float(tv.get("value") or "")
            if v is not None:
                cur.temp_c = v
                prov["temp_c"] = int(Tier.SHAPE)

    return (cur if cur.temp_c is not None else None), prov



def _tz_offset_min(st: dict) -> int:
    city = st.get("city") if isinstance(st, dict) else None
    tz = (city or {}).get("timeZone")
    return int(tz) if isinstance(tz, int) else 180        # MSK


def _hours(doc: Any, st: dict) -> tuple[list[Hour], dict[str, int], list[int]]:
    """Hourly, from `<time-value timestamp>` plus the chart's typed values.

    Times are rendered from the *city's* UTC offset, not the server's clock --
    the box is in Latvia and the weather is not.
    """
    stamps = doc.xpath('//*[contains(@class,"widget-row-datetime-time")]'
                       '//time-value[@timestamp]')
    chart = _temperature_chart(doc)
    if not stamps or chart is None:
        return [], {"hourly": int(Tier.ABSENT)}, []

    temps = [R.to_float(tv.get("value") or "")
             for tv in chart.xpath(".//temperature-value[@value]")]
    tips = [R.clean(n.get("data-tooltip") or "") for n in
            doc.xpath(_TOKEN.format(cls="widget-row-icon")
                      + "//*[@data-tooltip]")]
    precip = _precip_mm(doc)

    offset = dt.timezone(dt.timedelta(minutes=_tz_offset_min(st)))
    out: list[Hour] = []
    at: list[int] = []          # the epoch behind each kept column, in step
    seen: set[str] = set()
    for i, tv in enumerate(stamps):
        try:
            ts = int(tv.get("timestamp"))
        except (TypeError, ValueError):
            continue
        when = dt.datetime.fromtimestamp(ts, tz=offset).strftime("%H:%M")
        if when in seen or i >= len(temps) or temps[i] is None:
            continue
        seen.add(when)
        tip = tips[i] if i < len(tips) else None
        out.append(Hour(time=when, at=ts, temp_c=temps[i],
                        precip_mm=precip[i] if i < len(precip) else None,
                        condition=(tip[0].upper() + tip[1:]) if tip else None,
                        icon=R.icon_key(tip) if tip else None))
        at.append(ts)
    if not out:
        return [], {"hourly": int(Tier.ABSENT)}, []
    return out, {"hourly": int(Tier.LABELLED)}, at


# Matching a class by *token* rather than by substring. `contains(@class,
# "widget-row-icon")` also matches `widget-row-icon-snow`, which is the XPath
# spelling of the trap this codebase already has a name for: "безоблачно"
# contains "облачно". On the landing page the snow row carries no tooltips so
# nothing broke; on a page where it does, every icon in the strip shifts.
_TOKEN = '//*[contains(concat(" ", normalize-space(@class), " "), " {cls} ")]'


def _precip_mm(doc: Any) -> list[float | None]:
    """The «Осадки в жидком эквиваленте» row, in millimetres per column.

    The page publishes it and we were throwing it away: every Gismeteo hour
    shipped `precip_mm=None` while the row sat in the markup with 0,5 and 0,9
    in it. Nothing failed -- a field that is always empty looks exactly like a
    field the source does not provide, which is why it went unnoticed until
    someone compared the two pages side by side.
    """
    rows = doc.xpath(_TOKEN.format(cls="widget-row-precipitation-bars"))
    if not rows:
        return []
    out: list[float | None] = []
    for cell in rows[0].xpath('.//*[contains(@class,"row-item")]'):
        # The trap, and it is a nasty one: a dry hour is the plain text "0",
        # but a *wet* hour is a typed element -- `<precipitation-value
        # value="3.7" from-unit="mm">` -- and `text_content()` on it returns
        # nothing. Read the text alone and you get a series of zeros with holes
        # where the rain was, which downstream reads as "no precipitation
        # today". Every value that matters is the one that goes missing.
        typed = cell.xpath(".//precipitation-value[@value]")
        if typed:
            out.append(R.to_float(typed[0].get("value") or ""))
            continue
        out.append(R.to_float(R.clean(cell.text_content())))
    return out


# --- the per-day metric rows ------------------------------------------------
#
# The ten-day page is a stack of labelled rows -- wind, humidity, pressure, UV,
# geomagnetic activity, pollen -- each with one cell per day. We were reading
# exactly two of them (the temperature chart's max and min) and leaving the
# other thirteen on the page, which is the failure `test_mapping.py` was written
# about: nothing broke, the app just showed a tenth of what it had downloaded.
#
# Each row can be found three ways, and they fail independently:
#
#   1 NAMED     `data-row="wind-speed"` -- their own semantic key, and the only
#               handle here that is neither prose nor presentation.
#   2 LABELLED  the Russian caption. Survives a rename of the key above.
#   3 SHAPE     the class token. Survives a rewording of the caption.
#
# Class alone would not do even as a first choice: three separate rows carry
# `widget-row-wind`, distinguished only by `row-wind-speed` / `row-wind-
# direction` / `row-wind-gust`. Caption alone would not either -- two of those
# three captions differ by one word.
_ROWS: dict[str, tuple[str, str, str]] = {
    # logical name          data-row                  caption fragment            class token
    "temp":       ("temperature-air", "температура воздуха", "widget-row-chart-temperature-air"),
    "feels":      ("temperature-heat-index", "по ощущению", "widget-row-chart-temperature-heat-index"),
    "avg":        ("temperature-avg", "среднесуточная", "widget-row-chart-temperature-avg"),
    "wind":       ("wind-speed", "скорость ветра", "row-wind-speed"),
    "gust":       ("wind-gust", "порывы ветра", "row-wind-gust"),
    "wind_dir":   ("wind-direction", "направление ветра", "row-wind-direction"),
    "pressure":   ("pressure", "давление", "widget-row-chart-pressure"),
    "humidity":   ("humidity", "влажность", "widget-row-humidity"),
    "uv":         ("radiation", "уф-индекс", "widget-row-radiation"),
    "kp":         ("geomagnetic", "геомагнитная", "widget-row-geomagnetic"),
    "precip":     ("precipitation-bars", "осадки", "widget-row-precipitation-bars"),
    "snow":       ("icon-snow", "выпадающий снег", "widget-row-icon-snow"),
    "snow_depth": ("snow-height", "высота снежного", "widget-row-chart-snow-height"),
}


def _find_row(doc: Any, name: str) -> tuple[Any | None, int]:
    """The row node and which rung of the ladder answered."""
    key, caption, cls = _ROWS[name]
    got = doc.xpath(f'//*[@data-row="{key}"]')
    if got:
        return got[0], int(Tier.NAMED)
    for row in doc.xpath('//*[contains(@class,"widget-row")]'):
        cap = row.xpath('.//*[contains(@class,"widget-row-caption")]')
        if cap and caption in R.clean(cap[0].text_content()).lower():
            return row, int(Tier.LABELLED)
    got = doc.xpath(_TOKEN.format(cls=cls))
    return (got[0], int(Tier.SHAPE)) if got else (None, int(Tier.ABSENT))


def _cells(row: Any) -> list[Any]:
    """One node per day, in column order.

    Three cell shapes coexist on the same page: `row-item` for the plain rows,
    `.values > .value` for the charts, and -- snow depth only -- a typed element
    that *is* the cell.

    Reading a row's typed elements flat would be shorter and wrong. The pressure
    row omits its `mint` on the last two days, so a flat list of twenty is
    eighteen, and every day after the gap silently reads its neighbour's number.
    Nothing about that failure is visible: the values are all plausible
    pressures. Columns are containers, so counting containers is the only
    reading that stays aligned when one of them is missing a half.
    """
    items = row.xpath('.//*[contains(concat(" ", normalize-space(@class), " "),'
                      ' " row-item ")]')
    if items:
        return items
    return row.xpath('.//*[contains(concat(" ", normalize-space(@class), " "),'
                     ' " values ")]/*')


def _cell_value(cell: Any, part: str | None = None) -> float | None:
    """The number in one cell, typed attribute first.

    `part` narrows to `maxt` or `mint` for the rows that carry a range. The
    typed attribute is preferred everywhere for the reason the module docstring
    gives: it is already signed and already a number, so the U+2212 trap cannot
    reach it. Text is the fallback, for the rows Gismeteo renders as plain
    digits -- humidity, UV, Kp.
    """
    scope = cell
    if part is not None:
        got = cell.xpath(f'.//*[contains(concat(" ", normalize-space(@class),'
                         f' " "), " {part} ")]')
        if not got:
            return None
        scope = got[0]
    typed = ([scope] if scope.get("value") is not None else []) \
        + scope.xpath(".//*[@value]")
    if typed:
        return R.to_float(typed[0].get("value") or "")
    return R.to_float(R.clean(scope.text_content()))


def _row_values(doc: Any, name: str, part: str | None = None,
                prov: dict[str, int] | None = None) -> list[float | None]:
    row, tier = _find_row(doc, name)
    if prov is not None:
        prov[f"daily.{name}"] = tier
    if row is None:
        return []
    return [_cell_value(c, part) for c in _cells(row)]


# Gismeteo writes wind direction as a Russian abbreviation in the cell; every
# other source in this app speaks the long form, and the front end has one
# table turning long forms back into short ones for display. Translating here
# means the client keeps one vocabulary instead of three.
_ABBR: dict[str, str] = {
    "с": "северный", "св": "северо-восточный", "в": "восточный",
    "юв": "юго-восточный", "ю": "южный", "юз": "юго-западный",
    "з": "западный", "сз": "северо-западный", "штиль": "штиль",
}


def _dir_from(cell: Any) -> str | None:
    word = R.clean(cell.text_content()).lower().replace("-", "")
    return _ABBR.get(word)


def _temperature_chart(doc: Any) -> Any | None:
    """The chart row that holds air temperature, by its caption.

    Taking the *first* chart row worked on the landing page and is a positional
    assumption, which is the class of thing this parser avoids everywhere else
    -- and the hourly and ten-day pages do not order their rows the same way.
    Falls back to the first row when no caption matches, so a caption rename
    degrades rather than breaks.
    """
    rows = doc.xpath('//*[contains(@class,"widget-row-chart")]')
    for row in rows:
        cap = row.xpath('.//*[contains(@class,"widget-row-caption")]')
        text = R.clean(cap[0].text_content()).lower() if cap else ""
        if "температура воздуха" in text:
            return row
    return rows[0] if rows else None


# Which `Day` attribute each row fills, and which half of it to read. Kept as
# data rather than fifteen near-identical assignments because the interesting
# part is the *list* -- adding a metric should be one line here, and a metric
# that stops arriving should be visible as a gap in `provenance` rather than
# discovered by looking at the page with your eyes.
_DAY_FIELDS: tuple[tuple[str, str, str | None], ...] = (
    ("feels_max_c",       "feels",      "maxt"),
    ("feels_min_c",       "feels",      "mint"),
    ("avg_temp_c",        "avg",        None),
    ("pressure_max_mmhg", "pressure",   "maxt"),
    ("pressure_min_mmhg", "pressure",   "mint"),
    ("wind_ms",           "wind",       None),
    ("wind_gust_ms",      "gust",       None),
    ("humidity_pct",      "humidity",   None),
    ("uv_index",          "uv",         None),
    ("kp_index",          "kp",         None),
    ("precip_mm",         "precip",     None),
    ("snow_cm",           "snow",       None),
    ("snow_depth_cm",     "snow_depth", None),
)


def _days(doc: Any, *, today: dt.date) -> tuple[list[Day], dict[str, int]]:
    """The ten-day block: dates, typed max/min, tooltips, and the metric rows."""
    dates = [R.clean(x.text_content()) for x in
             doc.xpath('//*[contains(@class,"widget-row-date")]'
                       '//*[contains(@class,"row-item")]')]
    tips = [R.clean(n.get("data-tooltip") or "") for n in
            doc.xpath(_TOKEN.format(cls="widget-row-icon")
                      + "//*[@data-tooltip]")]
    prov: dict[str, int] = {}
    highs = _row_values(doc, "temp", "maxt", prov)
    lows = _row_values(doc, "temp", "mint")
    if not highs:
        return [], {"daily": int(Tier.ABSENT)}

    metrics = {name: _row_values(doc, row, part, prov)
               for name, row, part in _DAY_FIELDS}
    dirs_row, _ = _find_row(doc, "wind_dir")
    dirs = [_dir_from(c) for c in _cells(dirs_row)] if dirs_row is not None else []
    column_dates = _column_dates(dates, len(highs), today=today)

    out: list[Day] = []
    for i, hi in enumerate(highs):
        lo = lows[i] if i < len(lows) else None
        if hi is None and lo is None:
            continue
        date = column_dates[i]
        tip = tips[i] if i < len(tips) else None
        d = Day(date=date.isoformat(),
                title=R.clean(dates[i]) if i < len(dates) else None,
                temp_min_c=lo, temp_max_c=hi,
                condition=(tip[0].upper() + tip[1:]) if tip else None,
                icon=R.icon_key(tip) if tip else None,
                wind_dir=dirs[i] if i < len(dirs) else None)
        for name, _row, _part in _DAY_FIELDS:
            col = metrics[name]
            if i < len(col) and col[i] is not None:
                setattr(d, name, col[i])
        out.append(d)

    # Fewer than three days is a parse failure wearing a short list's clothes.
    if len(out) < 3:
        return [], {"daily": int(Tier.ABSENT)}
    prov["daily"] = int(Tier.LABELLED)
    return out, prov


# Which `DayPart` attribute each row fills, on the parts grid. Same rows as the
# ten-day page, one value per part instead of a range per day -- which is why
# none of these names a `maxt`/`mint` half.
_PART_FIELDS: tuple[tuple[str, str], ...] = (
    ("temp_c", "temp"),
    ("feels_like_c", "feels"),
    ("pressure_mmhg", "pressure"),
    ("humidity_pct", "humidity"),
    ("wind_ms", "wind"),
    ("wind_gust_ms", "gust"),
    ("precip_mm", "precip"),
)

# The four columns each date is divided into, lower-cased to match the
# vocabulary Yandex uses -- one word list reaches the client rather than two,
# and `service._PART_HOUR` keys on it when deciding which parts are dark.
_PART_NAMES = ("ночь", "утро", "день", "вечер")


def _parts(doc: Any, *, today: dt.date) -> tuple[dict[str, list[DayPart]],
                                                 dict[str, int]]:
    """The parts-of-day grid: date -> its four parts.

    The page is `/3-days/` and shows ten. Forty columns, four per date, with
    the same metric rows as the ten-day page — so this is the ten-day forecast
    at four times the resolution, and the only place any source in this app
    publishes «Thursday evening» as a thing you can look at.

    Refuses rather than guesses when the grid does not divide evenly. Forty
    columns over ten dates is a grid; thirty-nine over ten is a page that has
    changed shape, and mapping it by position anyway is how you end up showing
    Wednesday morning under Tuesday.
    """
    prov: dict[str, int] = {}
    dates = [R.clean(x.text_content()) for x in
             doc.xpath(_TOKEN.format(cls="widget-row-tod-date")
                       + '//*[contains(@class,"row-item")]')]
    names = [R.clean(x.text_content()).lower() for x in
             doc.xpath(_TOKEN.format(cls="widget-row-datetime-time")
                       + '//*[contains(@class,"row-item")]')]
    if not dates or not names or len(names) != len(dates) * len(_PART_NAMES):
        return {}, {"parts": int(Tier.ABSENT)}

    tips = [R.clean(n.get("data-tooltip") or "") for n in
            doc.xpath(_TOKEN.format(cls="widget-row-icon") + "//*[@data-tooltip]")]
    metrics = {attr: _row_values(doc, row, None, prov)
               for attr, row in _PART_FIELDS}
    dirs_row, _ = _find_row(doc, "wind_dir")
    dirs = [_dir_from(c) for c in _cells(dirs_row)] if dirs_row is not None else []

    when = _column_dates(dates, len(dates), today=today)
    out: dict[str, list[DayPart]] = {}
    for i, name in enumerate(names):
        tip = tips[i] if i < len(tips) else None
        part = DayPart(
            name=name,
            condition=(tip[0].upper() + tip[1:]) if tip else None,
            icon=R.icon_key(tip) if tip else None,
            wind_dir=dirs[i] if i < len(dirs) else None)
        for attr, _row in _PART_FIELDS:
            col = metrics[attr]
            if i < len(col):
                setattr(part, attr, col[i])
        out.setdefault(when[i // len(_PART_NAMES)].isoformat(), []).append(part)
    prov["parts"] = int(Tier.NAMED)
    return out, prov


def _column_dates(labels: list[str], count: int, *,
                  today: dt.date) -> list[dt.date]:
    """A date for every column, anchored on the first label that states one.

    Only the first column spells its month out -- «сб 1 авг», then «вс 2», «пн
    3» -- so the rest have to be counted from somewhere. Counting from *today*
    is the obvious choice and it is subtly wrong: if the page's first column
    ever disagrees with our idea of today (a response cached across midnight,
    a fixture replayed on another day), column zero takes its date from the
    label and every column after it takes a different one from the clock. The
    visible symptom is two rows with the same date and one date missing --
    which looks like an off-by-one in the *renderer*, and is the sort of thing
    that costs an evening.

    Anchoring on the label instead makes the sequence internally consistent by
    construction: one date is read, the others are that date plus their offset.
    Today is only the anchor when no column says anything at all.
    """
    anchor, at = today, 0
    for i, label in enumerate(labels[:count]):
        got = _date_from(label, today=today, index=i)
        if got is not None:
            anchor, at = got, i
            break
    return [anchor + dt.timedelta(days=i - at) for i in range(count)]


def _date_from(label: str, *, today: dt.date, index: int) -> dt.date | None:
    """"пт 31 июля" / "вс 2" -> a date, or None when the label states no month.

    `today` disambiguates the year, which the label never carries: «1 янв» in
    late December is next year's.
    """
    m = R.DATE_RE.search(R.clean(label).lower())
    if m:
        day = int(m.group("day"))
        month = R.MONTHS[m.group("month").lower()]
        best: dt.date | None = None
        for year in (today.year - 1, today.year, today.year + 1):
            try:
                cand = dt.date(year, month, day)
            except ValueError:
                continue
            if best is None or abs((cand - today).days) < abs((best - today).days):
                best = cand
        if best is not None:
            return best
    return None
