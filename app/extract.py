"""Extraction: three tiers, three *mechanisms*.

The handover documents specified a three-rung ladder -- named element, labelled
neighbourhood, page-wide shape match -- as a hedge against Yandex moving things
around. Reading the live 2026 page turned that hedge into something better than
it was designed to be, because the modern `/pogoda` offers three genuinely
independent sources of the same numbers:

**Tier 1 -- the flight stream.** `/pogoda` is a Next.js App Router app, and the
React Server Components payload (`self.__next_f.push([1, "..."])`) carries a
``fact`` object whose keys mirror the official Yandex Weather API contract:
``{"temperature": 16, "feelsLike": 17, "windSpeed": 1, "pressure": 745, ...}``.
Typed numbers. No degree signs to misread, no comma decimals, no U+2212. The
research pass concluded no such blob existed -- reasonably, since every scraper
in the wild parses the DOM -- but it does, and it is by a wide margin the best
thing to read.

**Tier 2 -- the accessibility prose.** Each day card carries a visually-hidden
paragraph written for screen readers::

    утром температура воздуха +19°, ощущается как +21°, небольшой дождь,
    скорость ветра 1,7 м/с, северный, влажность 76%, давление 744 мм рт. ст.

Every value is named by the text next to it, so there are no columns to shift
and no classes to rename. It is also *more precise than the screen*: the
visible cell rounds that wind to "2 м/с". Accessibility text changes when the
information architecture changes, which is far less often than the CSS does.

**Tier 3 -- content shape over the visible DOM.** The last resort, and the one
the original design was built around. Classes are CSS modules
(``AppForecastDayPart_value__hash``), so we match on the stable prefix and then
classify each cell by *what it contains*: ``744`` is pressure, ``76%`` is
humidity, ``+19°`` is a temperature. A positional parser reads ``78%`` as a
temperature the first time someone reorders a row; this one does not.

Recording which rung answered costs one integer per field and is the early
warning that matters: if yesterday everything came from tier 1 and today it all
comes from tier 3, the numbers may still be right, and the ground has moved.

Two traps that survive into this file:

* The visible current temperature is split across elements -- the sign lives in
  ``AppFactTemperature_attr`` and the digits in ``AppFactTemperature_value``.
  Read ``value`` alone and every winter temperature comes out positive. Tier 3
  therefore reads the *parent* ``AppFact_temperature`` node, which renders as
  ``+16°`` sign and all.
* ``/details`` no longer contains a single ``<table>`` element. The advice to
  parse it with ``pandas.read_html`` -- the "least fragile scrape available" as
  of the research pass -- is obsolete. It is divs now, all the way down.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from lxml import html as LH

from . import ru_text as R
from .models import Current, Day, DayPart, Hour, ParseError, Tier

log = logging.getLogger(__name__)

# --- the flight stream -----------------------------------------------------

_PUSH = re.compile(r'self\.__next_f\.push\(\[1,\s*(".*?")\]\)', re.S)


def flight(html_text: str) -> str:
    """Decode the RSC flight stream into one string.

    Each push carries a JSON-encoded chunk; concatenating the decoded chunks
    reconstructs the stream. A chunk that fails to decode is skipped rather
    than fatal -- Yandex truncates the last push mid-string often enough that
    treating it as an error would make the parser flap.
    """
    out: list[str] = []
    for m in _PUSH.finditer(html_text):
        try:
            out.append(json.loads(m.group(1)))
        except Exception:
            continue
    return "".join(out)


def _balanced(s: str, start: int) -> str | None:
    """The balanced {...} / [...] literal beginning at `start`."""
    if start >= len(s) or s[start] not in "{[":
        return None
    opener = s[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def json_values(stream: str, key: str) -> Iterator[Any]:
    """Every JSON object/array assigned to `"key":` in the stream."""
    for m in re.finditer(rf'"{re.escape(key)}"\s*:\s*', stream):
        raw = _balanced(stream, m.end())
        if raw is None:
            continue
        try:
            yield json.loads(raw)
        except Exception:
            continue




# --- Yandex's enums --------------------------------------------------------

CONDITION_RU = {
    "CLEAR": "Ясно",
    "PARTLY_CLOUDY": "Малооблачно",
    "CLOUDY": "Облачно с прояснениями",
    "OVERCAST": "Пасмурно",
    "DRIZZLE": "Морось",
    "LIGHT_RAIN": "Небольшой дождь",
    "RAIN": "Дождь",
    "MODERATE_RAIN": "Дождь",
    "HEAVY_RAIN": "Сильный дождь",
    "CONTINUOUS_HEAVY_RAIN": "Длительный сильный дождь",
    "SHOWERS": "Ливень",
    "WET_SNOW": "Дождь со снегом",
    "LIGHT_SNOW": "Небольшой снег",
    "SNOW": "Снег",
    "SNOW_SHOWERS": "Снегопад",
    "HAIL": "Град",
    "THUNDERSTORM": "Гроза",
    "THUNDERSTORM_WITH_RAIN": "Дождь с грозой",
    "THUNDERSTORM_WITH_HAIL": "Гроза с градом",
}

WIND_RU = {
    "NORTH": "северный", "NORTH_EAST": "северо-восточный", "EAST": "восточный",
    "SOUTH_EAST": "юго-восточный", "SOUTH": "южный",
    "SOUTH_WEST": "юго-западный", "WEST": "западный",
    "NORTH_WEST": "северо-западный", "CALM": "штиль",
}


# --- page identity ---------------------------------------------------------

@dataclass
class Identity:
    """Who does this page think it is?

    `yandex.ru/pogoda` geolocates the requesting IP when its addressing hints
    go stale and returns a beautifully-formed, entirely parseable forecast for
    the wrong city. A request for Yoshkar-Ola came back as Columbus, Ohio
    during the research pass. Every fetch is checked against this before a
    single number is believed.
    """

    title: str | None = None
    h1: str | None = None
    canonical: str | None = None
    slug: str | None = None
    geo_id: int | None = None
    name: str | None = None          # nominative, e.g. "Йошкар-Ола"
    lat: float | None = None
    lon: float | None = None


def identity(html_text: str, doc: Any, stream: str) -> Identity:
    ident = Identity()
    t = doc.xpath("//title/text()")
    ident.title = R.clean(t[0]) if t else None
    h1 = doc.xpath("//h1")
    ident.h1 = R.clean(h1[0].text_content()) if h1 else None
    can = doc.xpath('//link[@rel="canonical"]/@href')
    ident.canonical = can[0] if can else None

    # The flight stream is authoritative when present: it carries the locality
    # Yandex actually resolved, with declensions, which is also how a GPS fix
    # gets a properly-inflected Russian name without asking a fourth party.
    for loc in json_values(stream, "locality"):
        if isinstance(loc, dict) and loc.get("name"):
            ident.name = loc.get("name")
            ident.slug = loc.get("slug")
            gid = loc.get("id")
            ident.geo_id = int(gid) if isinstance(gid, int) else None
            break
    if ident.name is None:
        for ling in json_values(stream, "locationLinguistics"):
            if isinstance(ling, dict) and ling.get("nominative"):
                ident.name = ling["nominative"]
                break
    if ident.name is None:
        ident.name = _name_from_header(ident.h1 or ident.title or "")

    m = re.search(r'"slug"\s*:\s*"([a-z0-9-]+)"\s*,\s*"lat"\s*:\s*(-?[\d.]+)\s*,'
                  r'\s*"lon"\s*:\s*(-?[\d.]+)', stream)
    if m:
        ident.slug = ident.slug or m.group(1)
        with contextlib.suppress(ValueError):
            ident.lat, ident.lon = float(m.group(2)), float(m.group(3))
    return ident


def _name_from_header(h: str) -> str | None:
    """"Погода в Йошкар-Оле" -> "Йошкар-Оле" (prepositional; a fallback only)."""
    m = re.match(r"\s*Погода\s+(?:в|во|на)\s+(.+?)\s*(?:—|$)", R.clean(h))
    return m.group(1) if m else None


def check_identity(ident: Identity, *, expect_slug: str | None = None,
                   expect_lat: float | None = None,
                   expect_lon: float | None = None,
                   tolerance_deg: float = 0.75) -> str | None:
    """Return a reason string if this page is not the place we asked for.

    Deliberately strict. A wrong-city page parses perfectly, which is exactly
    why it has to be rejected here rather than downstream.
    """
    if not (ident.title or ident.h1):
        return "page has neither <title> nor <h1>"

    if expect_slug:
        found = (ident.slug or "").lower()
        if found and found != expect_slug.lower():
            return f"asked for slug {expect_slug!r}, page says {found!r}"
        if not found:
            canon = (ident.canonical or "")
            if f"/{expect_slug.lower()}" not in canon.lower():
                return f"asked for slug {expect_slug!r}, canonical is {canon!r}"

    # A degree of latitude is ~111 km. Yandex snaps to its nearest known
    # locality, so the resolved point is never exactly what we asked for; three
    # quarters of a degree is generous for that and nowhere near generous
    # enough to let another country through.
    if (expect_lat is not None and expect_lon is not None
            and ident.lat is not None
            and (abs(ident.lat - expect_lat) > tolerance_deg
                 or abs(ident.lon - expect_lon) > tolerance_deg * 2)):
        return (f"asked for {expect_lat},{expect_lon}; page resolved to "
                f"{ident.lat},{ident.lon}")
    return None


# --- the result ------------------------------------------------------------

@dataclass
class Extracted:
    current: Current | None = None
    hourly: list[Hour] = field(default_factory=list)
    daily: list[Day] = field(default_factory=list)
    nowcast: str | None = None
    ident: Identity = field(default_factory=Identity)
    provenance: dict[str, int] = field(default_factory=dict)


def parse(html_text: str, *, today: dt.date | None = None) -> Extracted:
    """Parse a `/pogoda` page. Raises rather than returning empty.

    `parse_current` returning zero would show +0° in January and be believed,
    so absence of a current temperature is an exception, not a value.
    """
    if R.looks_like_captcha(html_text):
        raise ParseError("page looks like a captcha or block interstitial")

    doc = LH.fromstring(html_text)
    stream = flight(html_text)
    out = Extracted(ident=identity(html_text, doc, stream))

    cur, prov = _current(doc, stream)
    out.current = cur
    out.provenance.update(prov)

    out.nowcast = _nowcast(doc)
    out.daily, dprov = _days(doc, today=today or dt.date.today())
    out.provenance.update(dprov)
    out.hourly, hprov = _hours(doc)
    out.provenance.update(hprov)

    if out.current is None or out.current.temp_c is None:
        raise ParseError("no current temperature could be extracted")
    return out


# --- current conditions ----------------------------------------------------

def _current(doc: Any, stream: str) -> tuple[Current | None, dict[str, int]]:
    tier1 = _current_from_flight(stream)
    if tier1 is not None:
        cur, keys = tier1
        prov = {k: int(Tier.NAMED) for k in keys}
        # Fill anything the JSON lacked from the DOM, recording the lower tier
        # honestly rather than pretending tier 1 answered for everything.
        dom, dom_keys = _current_from_dom(doc)
        for k in dom_keys:
            if getattr(cur, k, None) is None and getattr(dom, k, None) is not None:
                setattr(cur, k, getattr(dom, k))
                prov[k] = int(Tier.LABELLED)
        return cur, prov

    dom, dom_keys = _current_from_dom(doc)
    return dom, {k: int(Tier.LABELLED) for k in dom_keys}


def _current_from_flight(stream: str) -> tuple[Current, list[str]] | None:
    """The `fact` object. Note *which* fact: the stream also carries
    `userLocationLaasFact`, which is the weather where Yandex thinks the
    *requester* is. On a foreign-hosted server that is a different city, and
    reading it would reproduce the Columbus-Ohio failure from inside our own
    parser."""
    fact = None
    for m in re.finditer(r'(?<![A-Za-z])"fact"\s*:\s*', stream):
        raw = _balanced(stream, m.end())
        if not raw:
            continue
        try:
            cand = json.loads(raw)
        except Exception:
            continue
        if isinstance(cand, dict) and "temperature" in cand:
            fact = cand
            break
    if fact is None:
        return None

    got: list[str] = []
    cur = Current()

    def take(attr: str, value: Any, cast=float) -> None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            setattr(cur, attr, cast(value))
            got.append(attr)

    take("temp_c", fact.get("temperatureInCelsius", fact.get("temperature")))
    take("feels_like_c", fact.get("feelsLike"))
    take("humidity_pct", fact.get("humidity"))
    take("pressure_mmhg", fact.get("pressure"))
    take("wind_ms", fact.get("windSpeed"))

    code = fact.get("condition")
    if isinstance(code, str):
        cur.condition = CONDITION_RU.get(code, code.replace("_", " ").capitalize())
        got.append("condition")
    icon = fact.get("icon")
    if isinstance(icon, str):
        cur.icon = R.icon_from_yandex(icon) or R.icon_key(cur.condition)
        if cur.icon:
            got.append("icon")
    wd = fact.get("windDirection")
    if isinstance(wd, str):
        cur.wind_dir = WIND_RU.get(wd, wd.lower())
        got.append("wind_dir")
    return cur, got


def _current_from_dom(doc: Any) -> tuple[Current, list[str]]:
    """Tier 2/3 for current conditions.

    Reads the *parent* temperature node, because the sign and the digits live
    in different elements and reading only the digits makes January look like
    July.
    """
    cur = Current()
    got: list[str] = []

    temp_nodes = doc.xpath('//*[contains(@class,"AppFact_temperature")]')
    for n in temp_nodes:
        v = R.temperature(n.text_content())
        if v is not None:
            cur.temp_c, _ = v, got.append("temp_c")
            break

    for n in doc.xpath('//*[contains(@class,"AppFact_feels")]'):
        v = R.temperature(n.text_content())
        if v is not None:
            cur.feels_like_c, _ = v, got.append("feels_like_c")
            break

    for n in doc.xpath('//*[contains(@class,"AppFact_warning")]'):
        c = R.condition(n.text_content())
        if c:
            cur.condition, _ = c, got.append("condition")
            break

    # `AppFact_details` is a row of bare values -- "1 м/с, З", "745", "90%",
    # "15°" -- with nothing but their content to say which is which.
    for n in doc.xpath('//*[contains(@class,"AppFact_details")]'):
        txt = R.clean(n.text_content())
        if len(txt) > 40:
            continue
        hit = R.classify(txt)
        if hit is None:
            continue
        name, value = hit
        if name == "temp_c":
            # The water temperature also renders as a bare "15°". Never let it
            # become the air temperature.
            continue
        if getattr(cur, name, None) is None:
            setattr(cur, name, value)
            got.append(name)
        if name == "wind_ms":
            d = R.wind_dir(txt)
            if d and cur.wind_dir is None:
                cur.wind_dir, _ = d, got.append("wind_dir")
    return cur, got


def _nowcast(doc: Any) -> str | None:
    """The Meteum precipitation line -- "Сегодня осадков не ожидается", or
    "дождь начнётся через 25 минут". No free-tier equivalent exists anywhere
    else, which is a large part of why this project scrapes at all."""
    best: str | None = None
    for n in doc.xpath('//*[contains(@class,"AppFact_warning")]'):
        t = R.clean(n.text_content())
        if not t or len(t) > 120:
            continue
        if (re.search(r"осадк|дожд|снег|гроз|ливен|прояснени", t, re.I)
                and (best is None or len(t) < len(best))):
            best = t
    return best


# --- daily -----------------------------------------------------------------

_A11Y = 'contains(@class,"visuallyHidden")'


def _days(doc: Any, *, today: dt.date) -> tuple[list[Day], dict[str, int]]:
    cards = doc.xpath('//*[contains(@class,"AppForecastDay_dayCard")]')
    if not cards:
        cards = doc.xpath('//*[contains(@class,"AppForecastDay_container")]')
    # The page renders the forecast block twice -- once for the wide layout and
    # once for the narrow one -- so a naive walk yields 10 days followed by the
    # same 10 days again. Deduplicate on the date and keep the richer copy;
    # the narrow rendering omits fields the wide one carries.
    best: dict[str, tuple[Day, int]] = {}
    order: list[str] = []
    for card in cards:
        d, tier = _one_day(card, today=today)
        if d is None:
            continue
        prior = best.get(d.date)
        if prior is None:
            best[d.date] = (d, tier)
            order.append(d.date)
        elif _richness(d) > _richness(prior[0]):
            best[d.date] = (d, min(tier, prior[1]))

    if not best:
        return [], {"daily": int(Tier.ABSENT)}
    days = [best[k][0] for k in sorted(order)]
    # The worst rung that answered is the honest summary for the group.
    return days, {"daily": max(best[k][1] for k in order)}


def _richness(d: Day) -> int:
    """How much of this day actually got filled in."""
    n = len(d.parts) * 4
    for p in d.parts:
        n += sum(1 for f in ("temp_c", "feels_like_c", "condition", "wind_ms",
                             "humidity_pct", "pressure_mmhg", "wind_dir")
                 if getattr(p, f) is not None)
    n += sum(1 for f in ("uv_index", "water_temp_c", "sunrise", "sunset")
             if getattr(d, f) is not None)
    return n


def _one_day(card: Any, *, today: dt.date) -> tuple[Day | None, int]:
    a11y = card.xpath(f".//p[{_A11Y}]") or card.xpath(f".//*[{_A11Y}]")
    lines: list[str] = []
    for p in a11y:
        segs = [R.clean(s) for s in p.itertext()]
        segs = [s for s in segs if s]
        if len(segs) >= 3:
            lines = segs
            break

    title = None
    h3 = card.xpath('.//*[contains(@class,"AppForecastDayHeader_dayTitle")]')
    if h3:
        title = R.clean(h3[0].text_content())

    if lines:
        day = _day_from_a11y(lines, today=today, title=title)
        if day is not None and day.parts:
            return day, int(Tier.LABELLED)

    day = _day_from_dom(card, today=today, title=title)
    return day, int(Tier.SHAPE)


def _day_from_a11y(lines: list[str], *, today: dt.date,
                   title: str | None) -> Day | None:
    header = lines[0].rstrip(":")
    date = _date_from_text(header, today=today) or _date_from_text(title or "", today=today)
    if date is None:
        return None
    day = Day(date=date.isoformat(), title=title or header)

    for line in lines[1:]:
        low = line.lower()
        part = _part_of(low)
        if part is not None:
            dp = _part_from_prose(part, line)
            if dp is not None:
                day.parts.append(dp)
            continue
        if "уф-индекс" in low:
            m = re.search(r"уф-индекс[:\s]+(\d{1,2})", low)
            if m:
                day.uv_index = float(m.group(1))
        elif "температура воды" in low:
            day.water_temp_c = R.temperature(line)
        elif "восход" in low:
            day.sunrise = _hhmm(line)
        elif "закат" in low:
            day.sunset = _hhmm(line)
        elif "световой день" in low:
            day.daylight = R.clean(line.split(":", 1)[-1])
        elif "магнитн" in low:
            day.magnetic = R.clean(line.split(":", 1)[-1])

    _summarise(day)
    return day


def _part_of(low: str) -> str | None:
    for word, canon in R.DAY_PART_CANON.items():
        if low.startswith(word):
            return canon
    return None


def _part_from_prose(name: str, line: str) -> DayPart | None:
    """Parse one self-labelled sentence.

    "утром температура воздуха +19°, ощущается как +21°, небольшой дождь,
     скорость ветра 1,7 м/с, северный, влажность 76%, давление 744 мм рт. ст."

    Feels-like is pulled out *by its label first*, then removed, so the
    remaining first temperature is unambiguously the air temperature. Doing it
    the other way round works in the fixture and breaks the day Yandex swaps
    the clause order.
    """
    text = R.clean(line)
    dp = DayPart(name=name)

    m = re.search(r"ощущается\s+как\s*([^,]+)", text, re.I)
    if m:
        dp.feels_like_c = R.temperature(m.group(1))
        text_wo = text[: m.start()] + " " + text[m.end() :]
    else:
        text_wo = text

    dp.temp_c = R.temperature(text_wo)
    dp.condition = R.condition(text_wo)

    # NOT `[^,]+` -- Russian uses the comma as a decimal separator, so a
    # comma-terminated capture turns "1,7 м/с" into "1". Anchor on the unit.
    mw = re.search(r"скорость\s+ветра\s*([\d.,\s]*м/с)", text, re.I)
    dp.wind_ms = R.wind_ms(mw.group(1)) if mw else R.wind_ms(text)
    dp.wind_dir = R.wind_dir(text)

    mh = re.search(r"влажность\s*([^,]+)", text, re.I)
    dp.humidity_pct = R.humidity_pct(mh.group(1)) if mh else None

    mp = re.search(r"давление\s*([^,]+)", text, re.I)
    dp.pressure_mmhg = R.pressure_mmhg(mp.group(1)) if mp else None

    if dp.temp_c is None:
        return None
    if dp.condition:
        dp.condition = R.sentence(dp.condition)
    dp.icon = R.icon_key(dp.condition, night=(name == "ночь"))
    return dp


def _day_from_dom(card: Any, *, today: dt.date,
                  title: str | None) -> Day | None:
    """Tier 3. Walk the day card's cells in document order, split them into
    parts on each caption, and classify every value by content shape."""
    date = _date_from_text(title or "", today=today)
    if date is None:
        return None
    day = Day(date=date.isoformat(), title=title)

    cur: DayPart | None = None
    nodes = card.xpath(
        './/*[contains(@class,"AppForecastDayPart_caption")'
        ' or contains(@class,"AppForecastDayPart_value")'
        ' or contains(@class,"AppForecastDayPart_direction")]'
    )
    for n in nodes:
        klass = n.get("class") or ""
        txt = R.clean(n.text_content())
        if not txt:
            continue
        if "AppForecastDayPart_caption" in klass:
            part = _part_of(txt.lower())
            if part is not None:
                if cur is not None:
                    day.parts.append(cur)
                cur = DayPart(name=part)
                continue
            if cur is not None and cur.condition is None:
                c = R.condition(txt)
                if c:
                    cur.condition = c
            continue
        if cur is None:
            continue
        if "AppForecastDayPart_direction" in klass:
            if cur.wind_dir is None:
                cur.wind_dir = R.wind_dir(txt)
            continue
        hit = R.classify(txt)
        if hit is None:
            continue
        name, value = hit
        if name == "temp_c":
            # First temperature in the part is the air temperature; the second
            # is "feels like". The DOM gives no label, only order.
            if cur.temp_c is None:
                cur.temp_c = value
            elif cur.feels_like_c is None:
                cur.feels_like_c = value
        elif getattr(cur, name, None) is None:
            setattr(cur, name, value)
    if cur is not None:
        day.parts.append(cur)

    if not day.parts:
        return None
    _summarise(day)
    return day


def _summarise(day: Day) -> None:
    temps = [p.temp_c for p in day.parts if p.temp_c is not None]
    if temps:
        day.temp_min_c, day.temp_max_c = min(temps), max(temps)
    for want in ("день", "вечер", "утро", "ночь"):
        for p in day.parts:
            if p.name == want and p.condition:
                day.condition = p.condition
                day.icon = p.icon or R.icon_key(p.condition)
                return


# --- hourly ----------------------------------------------------------------

def _hours(doc: Any) -> tuple[list[Hour], dict[str, int]]:
    """The main page carries a full hourly strip.

    Worth flagging against the handover docs, which routed hourly to Open-Meteo
    "by design -- the scrape has no reliable hourly series". It has one now,
    with accessible labels, so hourly comes from Yandex like everything else
    and Open-Meteo goes back to being purely a referee.
    """
    items = doc.xpath('//*[contains(@class,"AppHourlyItem_container")]')
    out: list[Hour] = []
    seen: set[str] = set()
    tier = int(Tier.ABSENT)

    for it in items:
        a = it.xpath(f'.//*[{_A11Y}]')
        prose = R.clean(a[0].text_content()) if a else ""
        if prose:
            tier = min(tier, int(Tier.LABELLED))
            h = _hour_from_prose(prose)
        else:
            tier = min(tier, int(Tier.SHAPE))
            h = _hour_from_dom(it)
        if h is None or h.time in seen:
            continue
        seen.add(h.time)
        out.append(h)
    if not out:
        return [], {"hourly": int(Tier.ABSENT)}
    return out, {"hourly": tier}


_TIME_RE = re.compile(r"(?<!\d)(\d{1,2}:\d{2})")


def _hour_from_prose(prose: str) -> Hour | None:
    """"суббота, 00:00: +14°, малооблачно, Ощущается как +14°." """
    m = _TIME_RE.search(prose)
    if not m:
        return None
    body = prose[m.end() :]
    feels = None
    fm = re.search(r"ощущается\s+как\s*([^,.]+)", body, re.I)
    if fm:
        feels = R.temperature(fm.group(1))
        body = body[: fm.start()] + " " + body[fm.end() :]
    temp = R.temperature(body)
    if temp is None:
        return None
    cond = R.condition(body)
    if cond:
        cond = R.sentence(cond)
    # Day or night is decided once, centrally, in `service._sunlit` -- computed
    # from the place and the clock rather than guessed here. This line used to
    # read `hour >= 21 or hour < 5`, which is right in Yoshkar-Ola in August
    # and puts a sun in the sky at 07:00 in January.
    return Hour(time=m.group(1), temp_c=temp, feels_like_c=feels,
                condition=cond, icon=R.icon_key(cond))


def _hour_from_dom(item: Any) -> Hour | None:
    txt = R.clean(item.text_content())
    m = _TIME_RE.search(txt)
    if not m:
        return None
    temp = R.temperature(txt[m.end() :])
    if temp is None:
        return None
    cond = R.condition(txt)
    return Hour(time=m.group(1), temp_c=temp, condition=cond,
                icon=R.icon_key(cond))


# --- dates -----------------------------------------------------------------

def _date_from_text(text: str, *, today: dt.date) -> dt.date | None:
    """"Сегодня, 31 июля" / "Воскресенье, 2 августа" -> a real date.

    **The stated date wins over the relative word.** A header reading
    «Сегодня, 31 июля» carries both, and they can disagree: the page was
    fetched yesterday and is being read now, or the cache is serving something
    from before midnight, or -- the case that actually bit -- a test fixture
    recorded on the 31st is parsed on the 1st. `today` is our guess about when
    we are reading; «31 июля» is the page telling us what it is about, and the
    page wins.

    Reading it the other way round is a quiet, seasonal bug: every date shifts
    by one, the last day of the series falls off the end, and the suite that
    passed all afternoon goes red at midnight UTC for reasons nobody remembers
    an hour later.

    The page never states the year. Pick the candidate year that puts the date
    nearest to today, which handles the December-to-January rollover without a
    special case and without believing a forecast eleven months out.
    """
    t = R.clean(text).lower()
    m = R.DATE_RE.search(t)
    if not m:
        if t.startswith("сегодня"):
            return today
        if t.startswith("завтра"):
            return today + dt.timedelta(days=1)
        if t.startswith("послезавтра"):
            return today + dt.timedelta(days=2)
        return None
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
    return best


def _hhmm(text: str) -> str | None:
    m = _TIME_RE.search(R.clean(text))
    return m.group(1) if m else None
