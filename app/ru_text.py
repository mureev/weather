"""Russian vocabulary and content-shaped value extraction.

The design bet of this module: **classify a string by what it contains, not by
where it sits.** `743 мм` is unmistakably pressure and `2,9 м/с` is
unmistakably wind speed, no matter which column they land in or what the CSS
class is called. A positional parser reads `78%` as a temperature the first
time someone reorders a table; a content-shaped one does not.

Two traps live in here, both of which are invisible in July:

1. **Yandex renders minus as U+2212 MINUS SIGN, not ASCII hyphen.** Miss it and
   every winter temperature comes out positive. There is a dedicated test.

2. **A naive ``(\\d{1,2})\\s*°`` matches "743°" as +43.** A pressure reading
   silently becomes a plausible two-digit temperature -- in range, smooth,
   invisible to every downstream bounds check. Every numeric pattern here
   carries a ``(?<![\\d.,])`` guard so a number can never be read out of the
   middle of a longer number.
"""

from __future__ import annotations

import re
import unicodedata

# --- whitespace ------------------------------------------------------------
# Yandex is liberal with U+00A0 and U+202F. Normalising once here means no
# pattern below has to think about it.
_SPACES = dict.fromkeys(
    map(ord, "        　"), " "
)

# --- the minus-sign family -------------------------------------------------
# U+2212 MINUS SIGN, U+2013 EN DASH, U+2014 EM DASH, U+2010 HYPHEN, ASCII -.
MINUSES = "−–—‐‑-"
MINUS_CLASS = f"[{re.escape(MINUSES)}]"


def clean(s: str) -> str:
    """Normalize whitespace and unicode form. Does *not* touch minus signs --
    those are handled where numbers are parsed, so a raw string keeps whatever
    the page actually said."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).translate(_SPACES)
    return re.sub(r"\s+", " ", s).strip()


# --- a Russian name, in Latin letters ----------------------------------------
# For the English interface, and only for names nobody has spelled for us:
# the six built-in cities carry their English names, and a searched place
# carries the geocoder's. What is left is a GPS fix named by Yandex's locality
# or a hand-added city -- Russian places, almost always, for which a
# transliteration *is* the English name (Kozmodemyansk, Zvenigovo).
#
# BGN/PCGN, simplified the way English signage does it: no apostrophes for
# the soft and hard signs, `ye`/`yo` only where the letter starts a syllable.
# Case is kept letter by letter, so «Ростов-на-Дону» is Rostov-na-Donu.
_LAT = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya"}
_SOFT = set("аеёиоуыэюяъь")


def latin(name: str | None) -> str | None:
    if not name:
        return name
    out, prev = [], ""
    for ch in name:
        lo = ch.lower()
        lat = _LAT.get(lo)
        if lat is None:
            out.append(ch)
        else:
            if lo == "е" and (not prev or prev in _SOFT or not prev.isalpha()):
                lat = "ye"
            out.append(lat[:1].upper() + lat[1:] if ch != lo else lat)
        prev = lo
    return "".join(out)


def to_float(num: str) -> float | None:
    """Parse a Russian-formatted number: comma decimal separator, any of the
    five dash characters as a minus."""
    if not num:
        return None
    t = clean(num)
    neg = bool(t) and t[0] in MINUSES
    t = t.lstrip(MINUSES).replace(",", ".").replace(" ", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", t):
        return None
    v = float(t)
    return -v if neg else v


# --- content shapes --------------------------------------------------------
# The guard `(?<![\d.,])` is the load-bearing part of every one of these.
_G = r"(?<![\d.,])"

TEMP_RE = re.compile(
    rf"{_G}(?P<sign>{MINUS_CLASS}|\+)?\s?(?P<val>\d{{1,2}}(?:[.,]\d)?)\s*°"
)
PRESSURE_RE = re.compile(rf"{_G}(?P<val>\d{{3}}(?:[.,]\d)?)\s*мм(?:\s*рт)?")
HPA_RE = re.compile(rf"{_G}(?P<val>\d{{3,4}}(?:[.,]\d)?)\s*(?:гПа|hPa)")
WIND_RE = re.compile(rf"{_G}(?P<val>\d{{1,2}}(?:[.,]\d)?)\s*м/с")
HUMIDITY_RE = re.compile(rf"{_G}(?P<val>\d{{1,3}})\s*%")

WIND_DIRS = {
    "С": "северный", "СВ": "северо-восточный", "В": "восточный",
    "ЮВ": "юго-восточный", "Ю": "южный", "ЮЗ": "юго-западный",
    "З": "западный", "СЗ": "северо-западный", "Ш": "штиль",
}
WIND_DIR_RE = re.compile(r"(?<![А-Яа-яЁё])(СЗ|СВ|ЮЗ|ЮВ|С|Ю|В|З)(?![А-Яа-яЁё])")

DAY_PART_CANON = {
    "ночью": "ночь", "утром": "утро", "днём": "день", "днем": "день",
    "вечером": "вечер", "ночь": "ночь", "утро": "утро", "день": "день",
    "вечер": "вечер",
}

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11,
    "декабря": 12,
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4, "май": 5, "июнь": 6,
    "июль": 7, "август": 8, "сентябрь": 9, "октябрь": 10, "ноябрь": 11,
    "декабрь": 12,
    # Gismeteo's ten-day header writes «сб 1 авг», and without these the label
    # never matched -- so `_date_from` fell through to "today plus the column
    # index" for every Gismeteo day, every time. Nothing failed: positional
    # dates are right whenever column zero is today, which is almost always.
    # The exception is the case the fallback exists for, a page cached across
    # midnight, where every date would be a day out and look perfectly normal.
    # Listed last on purpose: `MONTHS` feeds an alternation and Python's `re`
    # takes the first branch that matches, so the full forms have to come first
    # or «1 августа» would match «авг» and stop.
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "июн": 6, "июл": 7, "авг": 8,
    "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}
DATE_RE = re.compile(
    rf"{_G}(?P<day>\d{{1,2}})\s+(?P<month>{'|'.join(MONTHS)})", re.IGNORECASE
)


# Conditions we expect to see. Used to *recognise* a condition string, never to
# reject one -- an unknown condition is passed through verbatim rather than
# dropped, because Yandex inventing new prose is not a parse failure.
CONDITIONS = (
    "ясно", "безоблачно", "малооблачно", "облачно с прояснениями", "облачно", "пасмурно",
    "небольшой дождь", "дождь", "сильный дождь", "ливень", "гроза",
    "небольшой снег", "снег", "сильный снег", "снег с дождём", "снег с дождем",
    "мокрый снег", "морось", "туман", "метель", "град",
)

# Labels, for the tier-2 "labelled neighbourhood" strategy.
LABELS = {
    "humidity": ("влажность",),
    "pressure": ("давление",),
    "wind": ("ветер",),
    "feels_like": ("ощущается как", "ощущается"),
    "uv": ("уф-индекс", "уф индекс"),
    "water": ("вода",),
    "sunrise": ("восход",),
    "sunset": ("закат",),
}

CAPTCHA_MARKERS = (
    "подтвердите, что запросы отправляли вы",
    "ой, captcha",
    "smartcaptcha",
    "checkcaptcha",
    "showcaptcha",
    "нам очень жаль",
    "робот",
)


# --- extractors ------------------------------------------------------------

def temperature(text: str) -> float | None:
    """First temperature in `text`, or None. Immune to 743° and to U+2212."""
    m = TEMP_RE.search(clean(text))
    if not m:
        return None
    val = to_float(m.group("val"))
    if val is None:
        return None
    sign = m.group("sign") or ""
    return -val if sign and sign in MINUSES else val




def pressure_mmhg(text: str) -> float | None:
    t = clean(text)
    m = PRESSURE_RE.search(t)
    if m:
        return to_float(m.group("val"))
    # Some locales render hPa. Convert rather than drop -- the unit is stated,
    # so there is no ambiguity to be honest about.
    m = HPA_RE.search(t)
    if m:
        v = to_float(m.group("val"))
        return round(v * 0.750062, 1) if v is not None else None
    return None


def wind_ms(text: str) -> float | None:
    m = WIND_RE.search(clean(text))
    return to_float(m.group("val")) if m else None


def humidity_pct(text: str) -> float | None:
    m = HUMIDITY_RE.search(clean(text))
    return to_float(m.group("val")) if m else None


def wind_dir(text: str) -> str | None:
    t = clean(text)
    for full, name in ((v, v) for v in WIND_DIRS.values()):
        if full in t.lower():
            return name
    m = WIND_DIR_RE.search(t)
    return WIND_DIRS.get(m.group(1)) if m else None


def condition(text: str) -> str | None:
    """Recognise a condition phrase. Longest match wins, so "облачно с
    прояснениями" is not truncated to "облачно"."""
    t = clean(text).lower()
    best: str | None = None
    for c in CONDITIONS:
        if c in t and (best is None or len(c) > len(best)):
            best = c
    if best is None:
        return None
    # Return it as it appears on the page, capitalisation and all.
    i = t.find(best)
    return clean(text)[i : i + len(best)]


def sentence(text: str | None) -> str | None:
    """A condition phrase as the app shows it: leading capital, rest untouched.

    Written out by hand at eight call sites before it was a function --
    `cond[0].upper() + cond[1:]`, once per parser, once per series -- and the
    ninth was simply forgotten. Gismeteo's tier-2 recovery reads the site's
    header sentence, «в Йошкар-Оле пасмурно, небольшой дождь», where the phrase
    follows a city and is naturally lowercase. Every other source capitalises,
    so switching tabs changed «Пасмурно» to «пасмурно» and back. Nothing was
    wrong; it just looked like nobody was in charge.

    `str.capitalize()` is the wrong tool and this is the reason it is spelled
    out: it lower-cases the tail. «Небольшой дождь, местами гроза» is fine
    either way, but the day a condition carries a proper noun -- or an already
    capitalised second clause -- `capitalize()` quietly rewrites it.
    """
    if not text:
        return text
    return text[0].upper() + text[1:]


def looks_like_captcha(html: str) -> bool:
    low = html[:200_000].lower()
    return any(m in low for m in CAPTCHA_MARKERS)


# --- icons -----------------------------------------------------------------
# Yandex renders its own icons as CSS sprite offsets (`style="--icon:27"`),
# which are meaningless without their stylesheet -- and loading their
# stylesheet would be a third-party subresource, which this project does not
# do at any price. So icons are derived from the condition text into a local
# vocabulary and drawn by our own inline SVG.
_ICONS: tuple[tuple[str, str], ...] = (
    ("гроза", "thunder"),
    ("град", "hail"),
    ("сильный дождь", "rain-heavy"),
    ("ливень", "rain-heavy"),
    ("небольшой дождь", "rain-light"),
    ("морось", "drizzle"),
    ("дождь", "rain"),
    ("мокрый снег", "sleet"),
    ("снег с дожд", "sleet"),
    ("дождь со снегом", "sleet"),
    ("сильный снег", "snow-heavy"),
    ("небольшой снег", "snow-light"),
    ("метель", "snow-heavy"),
    ("снег", "snow"),
    ("туман", "fog"),
    ("пасмурно", "overcast"),
    # Order matters and is load-bearing: "безоблачно" *contains* "облачно", and
    # "малооблачно" contains it too. Longest and most specific first, or
    # Gismeteo's word for a cloudless sky renders as an overcast icon.
    ("безоблачно", "clear"),         # Gismeteo's word for it
    ("облачно с прояснениями", "cloudy"),
    ("малооблачно", "partly"),
    ("облачно", "cloudy"),
    ("ясно", "clear"),
)

# Yandex's own icon codes, when the flight stream hands us one directly.
_YA_ICON = {
    "skc": "clear", "bkn": "partly", "ovc": "overcast",
    "ovc_ra": "rain", "bkn_ra": "rain-light", "skc_ra": "rain-light",
    "ovc_sn": "snow", "bkn_sn": "snow-light", "ovc_ts_ra": "thunder",
    "ovc_ra_sn": "sleet", "bkn_ra_sn": "sleet", "fg": "fog",
}


def icon_key(condition: str | None, *, night: bool = False) -> str | None:
    """Map a condition phrase to a local icon name."""
    if not condition:
        return None
    t = clean(condition).lower()
    for needle, key in _ICONS:
        if needle in t:
            return f"{key}-night" if night and key in ("clear", "partly") else key
    return None


def icon_from_yandex(code: str | None) -> str | None:
    """`skc_n` / `bkn_d` / `ovc_ra` -> a local icon name."""
    if not code:
        return None
    c = code.strip().lower()
    night = c.endswith("_n")
    if night or c.endswith("_d"):
        c = c[:-2]
    key = _YA_ICON.get(c)
    if key is None:
        key = _YA_ICON.get(c.split("_")[0])
    if key is None:
        return None
    return f"{key}-night" if night and key in ("clear", "partly") else key


def classify(cell: str) -> tuple[str, float] | None:
    """What *is* this cell? The heart of content-shaped parsing.

    Order matters: the more specific unit wins. `743 мм` must be tested before
    anything that could read a bare three-digit number.
    """
    t = clean(cell)
    if not t:
        return None
    for name, fn in (
        ("pressure_mmhg", pressure_mmhg),
        ("wind_ms", wind_ms),
        ("humidity_pct", humidity_pct),
        ("temp_c", temperature),
    ):
        v = fn(t)
        if v is not None:
            return name, v
    return None


