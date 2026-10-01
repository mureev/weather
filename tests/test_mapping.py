"""Everything the page says, against everything we read.

Three bugs in a row were the same bug wearing different clothes, and none of
them was caught by a test. Each was found by a human looking at two screens
side by side:

* the headline condition described midnight instead of the observed hour,
* hourly precipitation was silently always empty,
* and the second of those was invisible because *dry* hours are the plain text
  `0` while *wet* hours are `<precipitation-value value="3.7">` -- so reading
  the text produced a tidy series of zeros with holes where the rain was, which
  downstream reads as "no precipitation today".

The common shape: **nothing failed.** A field that is always `None` looks
exactly like a field the source does not publish. A series of zeros looks like
a dry day. There is no exception, no dropped value, no warning -- the parser
quietly under-reads and the app quietly shows less than it knows.

So this file inverts the usual direction. Instead of asking "does the parser
return the right thing", it asks **"what does the page contain that the parser
never touches"** -- and makes every such gap either fixed or explicitly
declared. A silent omission becomes a failing test; a deliberate omission
becomes one line in a list, which is a decision someone made rather than a
thing nobody noticed.
"""

from __future__ import annotations

import collections
import datetime as dt
from pathlib import Path
from typing import ClassVar

import pytest
from lxml import html as LH

from app import ru_text as R
from app.sources import gismeteo as G

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
SRC = "".join((ROOT / "app" / p).read_text(encoding="utf-8")
              for p in ("sources/gismeteo.py", "extract.py", "ru_text.py"))

# Typed elements Gismeteo ships that this file's grep cannot see us consume,
# and why. The point of the list is not that it is short -- it is that every
# entry is a decision. Something appearing here that nobody chose is the bug.
#
# All three of these *are* read now, by the daily metric rows. They stay listed
# because the audit above works by looking for the tag name in our source text,
# and the metric parser deliberately does not name tags: it takes whatever
# element in a cell carries a `value` attribute, which is what lets one code
# path read `temperature-value`, `speed-value`, `pressure-value` and
# `snow-value` alike. The grep is a tripwire for element types nobody has
# considered, and it keeps that job; these three are the known cost of it, and
# `TestTheDailyMetricsArrive` below is what actually holds them to account.
DECLARED_UNREAD = {
    "speed-value": "read generically by @value in the wind rows, not by tag",
    "pressure-value": "read generically by @value in the pressure row",
    "snow-value": "read generically by @value in the snow-depth row",
}


def fixtures(prefix: str = "") -> list[Path]:
    """Every Gismeteo-shaped page we hold.

    Both hosts, because they serve the same markup and the audit is about the
    markup: `gm-` is gismeteo.ru, `mf-` is the meteofor mirror. Auditing only
    one of them would have meant auditing only the pages that happen to be
    reachable from wherever the fixtures were last recorded.
    """
    return sorted(p for p in FIX.glob("*.html")
                  if p.name.startswith(("gm-", "mf-")) and prefix in p.name)


def typed_elements(doc) -> collections.Counter:
    """Custom elements carrying a `value` attribute -- the page's own typed
    data, as opposed to text a human is meant to read."""
    return collections.Counter(
        el.tag for el in doc.iter()
        if isinstance(el.tag, str) and "-" in el.tag and el.get("value") is not None)


class TestNothingTypedGoesUnnoticed:
    """The page hands us machine-readable values. Any we ignore should be an
    ignored-on-purpose, not an ignored-by-accident."""

    @pytest.mark.parametrize("path", fixtures(), ids=lambda p: p.name)
    def test_every_typed_element_is_either_read_or_declared(self, path):
        doc = LH.fromstring(path.read_text(encoding="utf-8", errors="replace"))
        found = typed_elements(doc)
        assert found, f"{path.name} has no typed elements -- did the page change?"
        unknown = [tag for tag in found
                   if tag not in SRC and tag not in DECLARED_UNREAD]
        assert not unknown, (
            f"{path.name} ships typed data nothing reads and nothing declares: "
            f"{unknown}. Either parse it or add it to DECLARED_UNREAD with a "
            f"reason -- `precipitation-value` sat here unread for a fortnight.")

    def test_the_declared_list_does_not_rot(self):
        """An entry that no longer appears in any fixture is a stale excuse,
        and stale excuses are how a list like this stops meaning anything."""
        seen: set[str] = set()
        for path in fixtures():
            seen |= set(typed_elements(
                LH.fromstring(path.read_text(encoding="utf-8", errors="replace"))))
        stale = sorted(set(DECLARED_UNREAD) - seen)
        assert not stale, f"declared-unread elements no longer on any page: {stale}"


class TestPublishedFieldsAreNotSilentlyEmpty:
    """If the page carries it and we model it, it must arrive.

    This is the check that would have caught the precipitation bug on the day
    it shipped. `precip_mm` was `None` for every hour, which is indistinguishable
    from a source that does not publish precipitation -- right up until you open
    their page and see the numbers.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def parsed(cls):
        return G.parse(
            (FIX / "gm-current.html").read_text(encoding="utf-8", errors="replace"),
            days_html=(FIX / "gm-10days.html").read_text(encoding="utf-8",
                                                         errors="replace"),
            today=dt.date(2026, 7, 31))

    def test_hourly_precipitation_arrives(self, parsed):
        got = [h.precip_mm for h in parsed.hourly]
        assert any(v is not None for v in got), \
            "every hour has precip_mm=None while the page publishes a row of it"
        assert any(v for v in got if v), \
            "precipitation is all zeros -- the wet hours are typed elements " \
            "and text-only reading skips exactly those"

    def test_precipitation_agrees_with_the_icons(self, parsed):
        """Two independent readings of the same fact: the millimetres come from
        the precipitation row, the icon from the column's tooltip. If they
        disagree, one of them is reading the wrong column."""
        for h in parsed.hourly:
            wet_icon = h.icon in ("rain", "rain-light", "rain-heavy", "drizzle",
                                  "snow", "snow-light", "snow-heavy", "sleet",
                                  "thunder", "hail")
            if h.precip_mm:
                assert wet_icon, f"{h.time}: {h.precip_mm} mm but icon {h.icon!r}"
            elif h.precip_mm == 0.0:
                assert not wet_icon, f"{h.time}: icon {h.icon!r} but 0 mm"

    def test_every_hour_has_a_timestamp(self, parsed):
        """`Hour.at` is what makes lining two series up unambiguous. A source
        that stops shipping it degrades to guessing, so notice immediately."""
        assert all(h.at is not None for h in parsed.hourly)

    def test_the_observation_carries_its_own_instant(self, parsed):
        assert parsed.current.observed_epoch is not None


class TestTheDailyMetricsArrive:
    """The other half of the audit: every metric row the page publishes, held
    against the `Day` field it is supposed to land in.

    This exists because the tag-name grep above cannot see a parser that reads
    typed elements generically, and because a metric that stops arriving looks
    exactly like a metric the source never had.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def days(cls):
        got = G.parse(
            (FIX / "mf-current.html").read_text(encoding="utf-8", errors="replace"),
            days_html=(FIX / "mf-10days.html").read_text(encoding="utf-8",
                                                         errors="replace"),
            today=dt.date(2026, 8, 1))
        return got.daily

    # Row caption on the page -> the field it fills. Written as the caption
    # rather than as our internal key so that reading this list next to the
    # page tells you what is missing.
    PUBLISHED: ClassVar[dict[str, tuple[str, ...]]] = {
        "Температура воздуха": ("temp_min_c", "temp_max_c"),
        "Температура по ощущению": ("feels_min_c", "feels_max_c"),
        "Среднесуточная температура": ("avg_temp_c",),
        "Средняя скорость ветра": ("wind_ms",),
        "Направление ветра": ("wind_dir",),
        "Порывы ветра": ("wind_gust_ms",),
        "Осадки в жидком эквиваленте": ("precip_mm",),
        "Выпадающий снег": ("snow_cm",),
        "Высота снежного покрова": ("snow_depth_cm",),
        "Давление": ("pressure_min_mmhg", "pressure_max_mmhg"),
        "Относительная влажность": ("humidity_pct",),
        "УФ-индекс": ("uv_index",),
        "Геомагнитная активность": ("kp_index",),
    }

    # Rows on the page that nobody has claimed. Pollen is three separate rows
    # of 0-3 scores; it is real information and seasonal, and it is left out
    # deliberately rather than overlooked -- three more fields on every day of
    # every source, to say "0" for eight months of the year.
    UNCLAIMED = ("Пыльца берёзы", "Пыльца злаковых трав", "Пыльца амброзии")

    @pytest.mark.parametrize("caption,fields", sorted(PUBLISHED.items()))
    def test_a_published_row_reaches_its_field(self, days, caption, fields):
        for name in fields:
            got = [getattr(d, name) for d in days]
            assert any(v is not None for v in got), (
                f"the page publishes «{caption}» for ten days and every "
                f"Day.{name} is empty")

    @pytest.fixture(scope="class")
    @classmethod
    def parts(cls):
        got = G.parse(
            (FIX / "mf-current.html").read_text(encoding="utf-8", errors="replace"),
            days_html=(FIX / "mf-10days.html").read_text(encoding="utf-8",
                                                         errors="replace"),
            parts_html=(FIX / "mf-3days.html").read_text(encoding="utf-8",
                                                         errors="replace"),
            today=dt.date(2026, 8, 1))
        return [p for d in got.daily for p in d.parts]

    @pytest.mark.parametrize("name", ["temp_c", "feels_like_c", "condition",
                                      "icon", "humidity_pct", "pressure_mmhg",
                                      "wind_ms", "wind_gust_ms", "wind_dir"])
    def test_the_parts_grid_fills_what_it_publishes(self, parts, name):
        """The same audit one level down. `/3-days/` carries the metric rows
        per part of day, and a part with every field empty is the exact shape
        of the precipitation bug: nothing fails, the app is just smaller than
        the page."""
        assert parts, "no parts parsed at all"
        got = [getattr(p, name) for p in parts]
        assert any(v is not None for v in got), (
            f"the parts grid publishes {name} for every column and every "
            f"DayPart.{name} is empty")

    @pytest.mark.parametrize("page", ["mf-10days.html", "mf-3days.html"])
    def test_the_page_has_no_row_this_list_has_not_considered(self, page):
        """The inverse question, and the one that catches a *new* row.

        Gismeteo adding «Атмосферное электричество» tomorrow would otherwise be
        invisible for ever: no test fails, no value is wrong, the app is simply
        smaller than the page it is reading."""
        doc = LH.fromstring(
            (FIX / page).read_text(encoding="utf-8", errors="replace"))
        captions = set()
        for row in doc.xpath('//*[contains(@class,"widget-row")]'):
            cap = row.xpath('.//*[contains(@class,"widget-row-caption")]')
            if cap:
                captions.add(R.clean(cap[0].text_content()).rstrip(", ").strip())
        known = [*self.PUBLISHED, *self.UNCLAIMED]
        missed = [c for c in captions
                  if not any(c.startswith(k) for k in known)]
        assert not missed, (
            f"the ten-day page carries rows nothing reads and nothing "
            f"declares: {missed}. Parse them or add them to UNCLAIMED.")


class TestTheConditionVocabularyIsFullyMapped:
    """Russian phrase to icon, over every phrase the fixtures actually contain.

    Spot-checking a mapping table proves nothing about the entries you did not
    think of, and a redesign introduces phrasing nobody thought of. So: take
    every condition string on every captured page and assert the icon agrees
    with the *words*.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def phrases(cls) -> list[str]:
        out: set[str] = set()
        for path in fixtures():
            doc = LH.fromstring(path.read_text(encoding="utf-8", errors="replace"))
            # Scoped to the icon row, exactly as the parser scopes it.
            # `data-tooltip` is used all over the page -- the wind row says
            # «слабый, южный ветер», the UV row says «высокий», the pollen row
            # says «низкая» -- and none of those is a sky condition. An audit
            # that collected them all would demand an icon for "moderate storm"
            # and get itself switched off within a day.
            for n in doc.xpath(G._TOKEN.format(cls="widget-row-icon")
                               + "//*[@data-tooltip]"):
                tip = R.clean(n.get("data-tooltip") or "")
                if tip:
                    out.add(tip.lower())
        return sorted(out)

    def test_the_fixtures_actually_contain_some(self, phrases):
        assert len(phrases) >= 4, f"only found {phrases}"

    def test_no_phrase_maps_to_nothing(self, phrases):
        """An unmapped phrase renders as the `unknown` glyph -- visible to a
        user, invisible to every other test."""
        unmapped = [p for p in phrases if R.icon_key(p) is None]
        assert not unmapped, f"no icon for: {unmapped}"

    @pytest.mark.parametrize("word,families", [
        ("гроза", {"thunder"}),
        ("град", {"hail"}),
        ("снег", {"snow", "snow-light", "snow-heavy", "sleet"}),
        ("дожд", {"rain", "rain-light", "rain-heavy", "drizzle", "sleet",
                  "thunder"}),
        ("морос", {"drizzle", "rain-light"}),
    ])
    def test_precipitation_always_beats_cloudiness(self, phrases, word, families):
        """«облачно, небольшой дождь» is two facts, and the one you need is the
        rain. The icon table is ordered so precipitation wins; this asserts the
        outcome rather than the order, so reordering the table cannot quietly
        break it."""
        for phrase in phrases:
            if word in phrase:
                assert R.icon_key(phrase) in families, \
                    f"{phrase!r} mentions {word!r} but maps to {R.icon_key(phrase)!r}"

    def test_a_cloudless_sky_is_not_overcast(self, phrases):
        """«безоблачно» contains «облачно». The trap that started the list."""
        for phrase in phrases:
            if phrase.startswith("безоблачно"):
                assert R.icon_key(phrase) == "clear", phrase

    def test_fog_only_wins_when_nothing_falls(self, phrases):
        """Fog is a visibility fact, rain is a get-wet fact. When a phrase has
        both, the one that changes what you wear should win."""
        for phrase in phrases:
            if "туман" in phrase and any(w in phrase for w in ("дожд", "снег")):
                assert R.icon_key(phrase) != "fog", phrase
