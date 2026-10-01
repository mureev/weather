"""Gismeteo parser, against real HTML captured 31 July 2026.

Worth noting what makes this source *easier* than Yandex rather than harder,
because it is the opposite of what you would guess from the two sites:

* `window.M.state` is a plain JSON object, not a React flight stream, and it
  carries the city's own coordinates — so the identity check is arithmetic
  rather than an argument about Russian declension.
* Forecast temperatures are `<temperature-value value="21">`: an attribute,
  already signed, already numeric. The U+2212 trap that dominates the Yandex
  parser is structurally impossible here.
* Their CSS class names are not build-hashed, so tier 3 has something stable
  to hold on to.

The one thing that is *worse*: addressing. `robots.txt` disallows every URL
with a query string, so a city can only be reached by a numeric id we have no
way to derive.
"""

import datetime as dt
import pathlib
import re
from itertools import pairwise

import lxml.html as LH
import pytest

from app import cities
from app.models import ParseError, Tier
from app.sources import gismeteo as G

TODAY = dt.date(2026, 7, 31)
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
RAW_DAYS = (FIXTURES / "mf-10days.html").read_text(encoding="utf-8",
                                                   errors="replace")


def _row_pairs(html: str, row: str) -> list[tuple[float | None, float | None]]:
    """The (min, max) a chart row states, read straight out of the markup.

    A second opinion on the parser, obtained by the crudest possible means: cut
    the row out of the raw text and regex the typed values inside it. It shares
    no code with `gismeteo._row_values` -- no lxml, no XPath, no notion of
    cells -- which is the entire point. Two readings that agree are evidence;
    one reading checked against numbers somebody typed in by hand is not.

    Pairs are built by *column*, so a column missing its `mint` yields a `None`
    rather than borrowing the next one, which is the failure being guarded.
    """
    # Note the quote characters: Gismeteo writes `class="value"` on the column
    # and `class='maxt'` inside it, in the same document. Assuming one of them
    # is how the first version of this found nothing at all.
    def side(cell: str, which: str) -> float | None:
        m = re.search(rf"""class=['"]{which}['"][^>]*>\s*"""
                      rf"""<[a-z-]+-value value=['"](-?[\d.]+)['"]""", cell)
        return float(m.group(1)) if m else None

    start = html.find(f'data-row="{row}"')
    if start < 0:
        return []
    end = html.find("data-row=", start + 1)
    block = html[start: end if end > 0 else len(html)]
    out: list[tuple[float | None, float | None]] = []
    for cell in re.split(r"""<div class=['"]value['"]""", block)[1:]:
        lo, hi = side(cell, "mint"), side(cell, "maxt")
        if lo is None and hi is None:
            continue
        out.append((lo, hi))
    return out


@pytest.fixture(scope="module")
def parsed(request):
    d = request.path.parent / "fixtures"
    return G.parse(
        (d / "gm-current.html").read_text(encoding="utf-8", errors="replace"),
        days_html=(d / "gm-10days.html").read_text(encoding="utf-8",
                                                   errors="replace"),
        today=TODAY,
    )


@pytest.fixture(scope="module")
def mf(request):
    """The mirror's four pages, parsed together.

    Module-level so anything can ask for it. Two classes below define their own
    `mf` with the same contents and those still shadow this one inside their
    own scope -- left alone deliberately, because merging them is a tidy-up
    with a real risk of changing which pages a test is reading, and this file
    exists to be sure about exactly that.
    """
    d = request.path.parent / "fixtures"
    read = lambda n: (d / n).read_text(encoding="utf-8", errors="replace")  # noqa: E731
    return G.parse(read("mf-current.html"),
                   days_html=read("mf-10days.html"),
                   hourly_html=read("mf-hourly.html"),
                   parts_html=read("mf-3days.html"))


class TestAddressing:
    def test_built_in_cities_have_ids(self):
        for slug in ("yoshkar-ola", "cheboksary", "kazan",
                     "nizhny-novgorod", "moscow", "saint-petersburg"):
            assert G.city_id(cities.get(slug)) is not None

    def test_urls_use_the_clean_path_form(self):
        now, hourly, days, parts = G.urls_for(cities.get("yoshkar-ola"))
        assert now == "https://www.gismeteo.ru/weather-yoshkar-ola-11975/"
        assert hourly.endswith("/hourly/")
        assert days.endswith("/10-days/")
        # Named /3-days/ by Gismeteo and showing ten of them, four columns a
        # day. The URL is theirs; the surprise is documented in `urls_for`.
        assert parts.endswith("/3-days/")
        # robots.txt disallows /*?* -- every URL with a query string.
        assert not any("?" in u for u in (now, hourly, days, parts))

    def test_a_gps_place_has_no_id_and_says_so(self):
        """No id means the tab is disabled with a reason. It must NOT quietly
        borrow a nearby city's numbers."""
        assert G.city_id(cities.ad_hoc(56.63, 47.90)) is None
        assert G.urls_for(cities.ad_hoc(56.63, 47.90)) is None


class TestIdentity:
    def test_resolves_the_right_city(self, parsed):
        assert parsed.ident.geo_id == 11975
        assert parsed.ident.slug == "yoshkar-ola"
        assert parsed.ident.lat == pytest.approx(56.6375, abs=0.01)

    def test_accepts_the_city_we_asked_for(self, parsed):
        assert G.check_identity(parsed.ident, cities.get("yoshkar-ola")) is None

    def test_rejects_a_different_city(self, parsed):
        """If the id in our table ever points somewhere else -- a typo, or a
        renumbering on their side -- this is what catches it."""
        why = G.check_identity(parsed.ident, cities.get("kazan"))
        assert why is not None and "11975" in why

    def test_coordinates_are_checked_not_just_names(self, parsed):
        import copy

        from app.models import Place
        far = Place(slug="yoshkar-ola", name="Йошкар-Ола", lat=39.96, lon=-83.0)
        ident = copy.copy(parsed.ident)
        ident.geo_id = None                 # force the coordinate path
        assert "resolved to" in (G.check_identity(ident, far) or "")


class TestCurrent:
    def test_comes_from_the_state_blob(self, parsed):
        for f in ("temp_c", "humidity_pct", "pressure_mmhg", "wind_ms"):
            assert parsed.provenance[f] == int(Tier.NAMED)

    def test_values(self, parsed):
        c = parsed.current
        assert c.temp_c == 15.0
        assert c.feels_like_c == 15.0
        assert c.humidity_pct == 100.0
        assert c.pressure_mmhg == 748.0
        assert c.wind_ms == 1.0

    def test_wind_bearing_becomes_a_russian_direction(self, parsed):
        """`windDirection` is 311 degrees, not a compass index."""
        assert parsed.current.wind_dir == "северо-западный"

    def test_condition_is_honestly_a_lower_tier(self, parsed):
        """The state blob gives `description: "nebulosity.type.0"` -- a
        translation key with no dictionary shipped on the page. So the readable
        text comes from a column tooltip, and that is recorded as tier 2 rather
        than pretending the JSON answered."""
        assert parsed.provenance["condition"] == int(Tier.LABELLED)

    def test_the_condition_describes_the_moment_the_reading_was_taken(self, parsed):
        """This assertion used to read `== "Малооблачно, туман"`, and that was
        the bug rather than the specification.

        The headline condition came from the *first* tooltip on the page, which
        is the strip's leftmost column: midnight. In this fixture the reading
        was taken at 23:00 and the leftmost column is 00:00, so the app showed
        a temperature observed at eleven at night beside a description of the
        previous midnight -- twenty-three hours apart, both perfectly plausible,
        and wrong together.

        It survived because the fixture was captured at 00:54, the one hour of
        the day when the first column *is* roughly now, and because the hourly
        strip came from the same page, so the two agreed on screen. Fetching a
        dedicated `/hourly/` page moved the hourly series to real hours and the
        disagreement finally became visible.
        """
        MSK = dt.timezone(dt.timedelta(hours=3))
        observed = dt.datetime.fromtimestamp(parsed.current.observed_epoch, tz=MSK)
        assert observed.strftime("%H:%M") == "23:00"

        nearest = min(parsed.hourly,
                      key=lambda h: abs(int(h.time[:2]) - observed.hour))
        assert nearest.time == "21:00"
        assert parsed.current.condition == nearest.condition == "Безоблачно"
        assert parsed.current.icon == nearest.icon

    def test_the_fixture_is_not_one_where_the_bug_could_hide(self, parsed):
        """A guard on the *fixture*, not the parser.

        The whole failure above was invisible for one reason: the captured page
        happened to be one where the first column and the observation time
        coincide. Re-record at 00:30 some morning and the regression test above
        passes while asserting nothing.

        So: refuse a fixture whose leftmost column is the observed hour. If
        `make fixtures-gm` ever produces one, this fails and tells you to
        recapture later in the day -- which is a strange-looking demand until
        you have lost an afternoon to it once.
        """
        MSK = dt.timezone(dt.timedelta(hours=3))
        observed = dt.datetime.fromtimestamp(parsed.current.observed_epoch, tz=MSK)
        first = int(parsed.hourly[0].time[:2])
        assert abs(first - observed.hour) > 1, (
            "this fixture was captured when the strip's first column was also "
            "'now'. Recapture it at another time of day: as it stands it cannot "
            "distinguish a correct parser from the one that reads column zero.")

    def test_missing_temperature_raises(self):
        with pytest.raises(ParseError):
            G.parse("<html><body><h1>Погода в Никуда</h1></body></html>")

    def test_captcha_raises(self):
        with pytest.raises(ParseError, match="captcha"):
            G.parse("<html><body>Подтвердите, что запросы отправляли вы"
                    "</body></html>")


class TestHourly:
    def test_present(self, parsed):
        assert len(parsed.hourly) == 8
        assert len({h.time for h in parsed.hourly}) == 8

    def test_times_use_the_citys_offset_not_the_servers(self, parsed):
        """The box is in Latvia; the weather is not. Times come from the
        city's own `timeZone` field in the state blob."""
        assert parsed.hourly[0].time == "00:00"
        assert all(len(h.time) == 5 and ":" in h.time for h in parsed.hourly)

    def test_temperatures_are_real(self, parsed):
        temps = [h.temp_c for h in parsed.hourly]
        assert all(t is not None for t in temps)
        assert len(set(temps)) > 1          # not a degenerate single-node read

    def test_a_broken_hourly_page_keeps_the_landing_page_series(self, request):
        """`/hourly/` is an upgrade, not a dependency. The landing page carries
        the same series at three-hour resolution, so if the dedicated page ever
        redesigns out from under the parser the forecast gets coarser rather
        than disappearing -- and the richer of the two always wins, so this
        cannot silently downgrade a working fetch either."""
        d = request.path.parent / "fixtures"
        got = G.parse(
            (d / "gm-current.html").read_text(encoding="utf-8", errors="replace"),
            hourly_html="<html><body>nothing the parser recognises</body></html>",
            today=TODAY)
        assert len(got.hourly) == 8


class TestDaily:
    def test_ten_days(self, parsed):
        assert len(parsed.daily) == 10

    def test_dates_are_consecutive_from_today(self, parsed):
        dates = [dt.date.fromisoformat(d.date) for d in parsed.daily]
        assert dates[0] == TODAY
        for a, b in pairwise(dates):
            assert (b - a).days == 1

    def test_later_columns_drop_the_month_and_still_resolve(self, parsed):
        """Column 0 says "пт 31 июля"; column 3 says only "пн 3". The sequence
        position is the fallback, anchored on the first column that states a
        month."""
        assert parsed.daily[3].title == "пн 3"
        assert parsed.daily[3].date == "2026-08-03"

    def test_an_abbreviated_month_is_still_a_month(self):
        """«сб 1 авг» is what the ten-day header actually says, and until the
        three-letter forms were in the table it matched nothing -- so every
        Gismeteo date came from "today plus the column index" instead of from
        the page. That fallback is right on any day the page's first column is
        today, which is every day but the one it exists for."""
        assert G._date_from("сб 1 авг", today=dt.date(2026, 7, 30),
                            index=0) == dt.date(2026, 8, 1)
        assert G._date_from("пт 31 июля", today=TODAY, index=0) == TODAY
        # No month named at all: say so, rather than inventing one.
        assert G._date_from("вс 2", today=TODAY, index=1) is None

    def test_the_sequence_is_anchored_on_the_page_not_on_our_clock(self):
        """The failure this prevents leaves no broken value behind.

        Column 0 carries a month and resolves from its label; columns 1..n
        carry only a day number and used to be counted from *today*. Let those
        two disagree by a day -- a payload cached across midnight -- and the
        first two columns land on the same date, one date vanishes, and every
        row after it describes the wrong day under a plausible heading."""
        got = G._column_dates(["сб 1 авг", "вс 2", "пн 3"], 3,
                              today=dt.date(2026, 7, 31))
        assert [d.isoformat() for d in got] == \
            ["2026-08-01", "2026-08-02", "2026-08-03"]

    def test_no_label_anywhere_falls_back_to_today(self):
        got = G._column_dates(["", "", ""], 3, today=TODAY)
        assert got[0] == TODAY and (got[2] - got[0]).days == 2

    def test_highs_and_lows(self, parsed):
        d = parsed.daily[0]
        assert (d.temp_min_c, d.temp_max_c) == (13.0, 21.0)
        assert all(x.temp_max_c >= x.temp_min_c for x in parsed.daily)

    def test_conditions_from_tooltips(self, parsed):
        assert parsed.daily[0].condition == "Малооблачно, дождь, туман"
        assert parsed.daily[2].condition == "Безоблачно"

    def test_precipitation_wins_the_icon(self, parsed):
        """"малооблачно, дождь, туман" is three conditions in one string. The
        one you need to know about is the rain."""
        assert parsed.daily[0].icon == "rain"
        assert parsed.daily[1].icon == "rain-light"

    def test_bezoblachno_is_not_read_as_cloudy(self, parsed):
        """"безоблачно" *contains* "облачно". Substring order in the icon table
        is load-bearing, and this is the test that says so."""
        assert parsed.daily[2].icon == "clear"

    def test_a_short_forecast_is_rejected_rather_than_shown(self):
        """Fewer than three days is a parse failure wearing a short list's
        clothes."""
        days, prov = G._days(
            __import__("lxml.html", fromlist=["x"]).fromstring(
                "<div><div class='widget-row-chart'>"
                "<div class='widget-row-caption'>Температура воздуха,</div>"
                "<div class='maxt'><temperature-value value='20'>"
                "</temperature-value></div></div></div>"),
            today=TODAY)
        assert days == []
        assert prov["daily"] == int(Tier.ABSENT)


class TestTheMetricRows:
    """Thirteen rows the ten-day page has always carried and we never read.

    Nothing was broken while they went unread -- that is the whole difficulty.
    A `Day` with `humidity_pct=None` is indistinguishable from a source that
    does not publish humidity, and the page was publishing it in a labelled row
    with one cell per day the entire time.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def mf(cls, request):
        d = request.path.parent / "fixtures"
        return G.parse(
            (d / "mf-current.html").read_text(encoding="utf-8", errors="replace"),
            days_html=(d / "mf-10days.html").read_text(encoding="utf-8",
                                                       errors="replace"),
            hourly_html=(d / "mf-hourly.html").read_text(encoding="utf-8",
                                                         errors="replace"),
            today=dt.date(2026, 8, 1))

    def test_every_modelled_metric_arrives(self, mf):
        day = mf.daily[0]
        for name in ("feels_min_c", "feels_max_c", "avg_temp_c", "humidity_pct",
                     "pressure_min_mmhg", "pressure_max_mmhg", "wind_ms",
                     "wind_gust_ms", "wind_dir", "uv_index", "kp_index"):
            assert getattr(day, name) is not None, f"{name} is empty"

    @pytest.mark.parametrize("row,lo,hi", [
        ("temperature-air", "temp_min_c", "temp_max_c"),
        ("temperature-heat-index", "feels_min_c", "feels_max_c"),
        ("pressure", "pressure_min_mmhg", "pressure_max_mmhg"),
    ])
    def test_the_values_are_the_ones_on_the_page(self, mf, row, lo, hi):
        """Read back out of the raw HTML by a deliberately different route.

        This used to assert `(15.0, 25.0)` and friends, which made it a test of
        *the weather on 31 July*: every `make fixtures-gm` broke it, and the
        only available repair was to paste in whatever the new capture said --
        which is not a test, it is a transcription. Worse, a parser that had
        genuinely started reading the wrong row would have been "fixed" the
        same way, by hand, without anybody noticing.

        So the expectation comes from the page instead, found by a plain regex
        over the raw text rather than by the parser's own XPath. Two mechanisms
        on one page: if they agree, the parser is reading the row it thinks it
        is -- on any capture, for ever.
        """
        want = _row_pairs(RAW_DAYS, row)
        assert want, f"no {row} values found in the raw page"
        got = [(getattr(d, lo), getattr(d, hi)) for d in mf.daily]
        assert got == want[: len(got)]

    def test_a_missing_half_does_not_shift_its_neighbours(self):
        """The reason cells are counted as containers rather than as a flat
        list of typed elements.

        Gismeteo's pressure row has published a max for ten days and a min for
        only the first eight. Read flat, that is eighteen values where twenty
        are expected, and the ninth day silently takes the eighth day's
        minimum -- a real pressure, in range, in the right unit, attached to
        the wrong day. Nothing downstream can see it.

        On synthetic markup, because whether any given capture *has* a gap is
        Gismeteo's business: the July page had one, today's does not, and
        asserting it against a fixture was testing the weather again.
        """
        cells = "".join(
            '<div class="value"><div class="maxt">'
            f'<pressure-value value="{750 + i}" from-unit="mmhg"></pressure-value>'
            "</div>"
            + (f'<div class="mint"><pressure-value value="{740 + i}" '
               f'from-unit="mmhg"></pressure-value></div>' if i < 3 else "")
            + "</div>"
            for i in range(5))
        doc = __import__("lxml.html", fromlist=["x"]).fromstring(
            f'<div data-row="pressure" class="widget-row-chart '
            f'widget-row-chart-pressure"><div class="values">{cells}</div></div>')
        assert G._row_values(doc, "pressure", "maxt") == [750, 751, 752, 753, 754]
        # The gap stays where the page put it: three minima, then two holes --
        # not three minima slid under days four and five.
        assert G._row_values(doc, "pressure", "mint") == [740, 741, 742, None, None]

    def test_wherever_both_ends_exist_they_belong_to_the_same_day(self, mf):
        """The property the test above protects, over whatever was recorded."""
        for d in mf.daily:
            if d.pressure_min_mmhg is not None:
                assert d.pressure_min_mmhg <= d.pressure_max_mmhg, d.date
            if d.temp_min_c is not None:
                assert d.temp_min_c <= d.temp_max_c, d.date

    def test_wind_direction_speaks_the_same_language_as_every_other_source(self, mf):
        """The cell says «СЗ». Open-Meteo says «северо-западный». One
        vocabulary reaches the client or the front end needs three tables.

        This read `== "северо-западный"` and broke on the first re-record,
        because on that day the wind was westerly. That is the documented trap:
        a test that hardcodes a value out of a fixture is a test of the
        weather, and its only repair is to paste in the new number -- which
        would just as happily bless a parser that had started reading the wrong
        row. So it asserts the *property*, and cross-checks the vocabulary
        against the raw markup by a different mechanism, the way `_row_pairs`
        does for the chart.
        """
        dirs = [d.wind_dir for d in mf.daily if d.wind_dir]
        assert dirs, "no wind direction survived at all"
        for got in dirs:
            assert got in G._DIRS or got == "штиль", (
                f"{got!r} is not one of the eight long Russian forms -- an "
                f"abbreviation reaching the client means three lookup tables "
                f"on the front end instead of one")
        # The abbreviations the page actually prints, found without the parser.
        said = set(re.findall(r">\s*(С|Ю|В|З|СВ|СЗ|ЮВ|ЮЗ)\s*<", RAW_DAYS))
        assert said, "no abbreviation found in the markup to check against"
        assert len(set(dirs)) > 1 or len(said) == 1, (
            "every day has the same direction while the page prints several -- "
            "the column is being read by position")
        assert all(d.wind_dir is None or " " not in d.wind_dir
                   for d in mf.daily)

    def test_each_row_records_which_rung_answered(self, mf):
        """`data-row="wind-speed"` is Gismeteo's own semantic key, so every one
        of these should be tier 1 today. The value of recording it is the day
        one of them is not."""
        for name in ("temp", "feels", "wind", "pressure", "humidity", "uv"):
            assert mf.provenance[f"daily.{name}"] == int(Tier.NAMED), name

    def test_the_caption_answers_when_the_key_is_gone(self):
        """Tier 2. Their `data-row` attribute is an internal contract and will
        change without warning; the Russian caption is what a human reads."""
        doc = __import__("lxml.html", fromlist=["x"]).fromstring(
            '<div><div class="widget-row widget-row-humidity">'
            '<p class="widget-row-caption">Относительная влажность, %</p>'
            '<div class="row-item">81</div></div></div>')
        row, tier = G._find_row(doc, "humidity")
        assert tier == int(Tier.LABELLED)
        assert G._cell_value(G._cells(row)[0]) == 81.0

    def test_the_class_answers_when_the_caption_is_gone(self):
        """Tier 3, and the reason the class token is `row-wind-speed` rather
        than `widget-row-wind`: three separate rows carry the latter."""
        doc = __import__("lxml.html", fromlist=["x"]).fromstring(
            '<div><div class="widget-row widget-row-wind row-wind-gust">'
            '<div class="row-item"><speed-value value="9"/></div></div>'
            '<div class="widget-row widget-row-wind row-wind-speed">'
            '<div class="row-item"><speed-value value="4"/></div></div></div>')
        row, tier = G._find_row(doc, "wind")
        assert tier == int(Tier.SHAPE)
        assert G._cell_value(G._cells(row)[0]) == 4.0


class TestThePartsOfDayGrid:
    """`/3-days/` is a ten-day grid at four columns a day, and the name of the
    page is the only thing about it that says three."""

    @pytest.fixture(scope="class")
    @classmethod
    def mf(cls, request):
        d = request.path.parent / "fixtures"

        def read(n):
            return (d / n).read_text(encoding="utf-8", errors="replace")

        return G.parse(read("mf-current.html"),
                       days_html=read("mf-10days.html"),
                       hourly_html=read("mf-hourly.html"),
                       parts_html=read("mf-3days.html"),
                       today=dt.date(2026, 8, 1))

    def test_the_grid_is_ten_days_of_four(self, mf):
        with_parts = [d for d in mf.daily if d.parts]
        assert len(with_parts) >= 8, \
            f"only {len(with_parts)} of {len(mf.daily)} days got parts"
        assert all(len(d.parts) == 4 for d in with_parts)

    def test_the_parts_keep_gismeteos_own_order(self, mf):
        """Night first here, and *last* on Yandex's page -- where it means the
        following night. Two sources, two conventions, neither reordered."""
        day = next(d for d in mf.daily if d.parts)
        assert [p.name for p in day.parts] == ["ночь", "утро", "день", "вечер"]

    def test_every_part_carries_the_metrics_the_page_publishes(self, mf):
        day = next(d for d in mf.daily if d.parts)
        for p in day.parts:
            for name in ("temp_c", "feels_like_c", "condition", "icon",
                         "humidity_pct", "pressure_mmhg", "wind_gust_ms"):
                assert getattr(p, name) is not None, f"{p.name}.{name} is empty"

    def test_a_calm_part_says_so_instead_of_inventing_a_zero(self, mf):
        """Gismeteo prints «штиль» and no number at all when there is no wind.
        The speed must stay `None` -- a 0 would be a value we made up, and this
        codebase drops rather than fills."""
        calm = [p for d in mf.daily for p in d.parts if p.wind_dir == "штиль"]
        assert calm, "no calm part in the fixture -- has the page changed?"
        assert all(p.wind_ms is None for p in calm)

    def test_parts_are_matched_to_days_by_date_not_by_position(self):
        """The two pages are fetched together but they are still two pages, and
        a set recorded across midnight has them starting on different mornings.

        Asserted on synthetic input rather than on the fixtures, deliberately.
        Whether the recorded pages happen to agree depends on the minute
        somebody ran `make fixtures-gm`, and a test that encodes today's
        accident fails tomorrow for no reason -- or, worse, starts passing for
        no reason. What is being protected is that a day only ever gets the
        parts labelled with *its own date*.
        """
        from lxml import html as LH

        def grid(first_date: str) -> str:
            cells = "".join(f'<div class="row-item">{n}</div>'
                            for _ in range(2) for n in ("Ночь", "Утро", "День",
                                                        "Вечер"))
            return (f'<div><div class="widget-row widget-row-tod-date">'
                    f'<div class="row-item">{first_date}</div>'
                    f'<div class="row-item">вс 9</div></div>'
                    f'<div class="widget-row widget-row-datetime-time">{cells}'
                    f'</div><div class="widget-row widget-row-humidity">'
                    + "".join('<div class="row-item">70</div>' for _ in range(8))
                    + "</div></div>")

        parts, _ = G._parts(LH.fromstring(grid("сб, 8 августа")),
                            today=dt.date(2026, 8, 8))
        assert sorted(parts) == ["2026-08-08", "2026-08-09"]
        assert all(len(v) == 4 for v in parts.values())

        # The same grid, stated as starting a day later. Every part moves with
        # it; nothing is left hanging off the date it used to be under.
        later, _ = G._parts(LH.fromstring(grid("вс, 9 августа")),
                            today=dt.date(2026, 8, 8))
        assert sorted(later) == ["2026-08-09", "2026-08-10"]

    def test_a_day_only_ever_holds_parts_of_its_own_date(self, mf):
        """The property, over whatever the recorded pages happen to say. If the
        two were captured a day apart, some days have no parts and none has the
        wrong ones."""
        grid, _ = G._parts(
            __import__("lxml.html", fromlist=["x"]).fromstring(
                (FIXTURES / "mf-3days.html").read_text(encoding="utf-8",
                                                       errors="replace")),
            today=dt.date(2026, 8, 1))
        for day in mf.daily:
            assert day.parts == grid.get(day.date, []), day.date

    def test_a_grid_that_does_not_divide_is_refused(self):
        """Forty columns over ten dates is a grid. Thirty-nine is a page that
        has changed shape, and laying it out by position anyway is how
        Wednesday morning ends up under Tuesday."""
        doc = __import__("lxml.html", fromlist=["x"]).fromstring(
            '<div><div class="widget-row widget-row-tod-date">'
            '<div class="row-item">вс, 2 августа</div>'
            '<div class="row-item">пн, 3 августа</div></div>'
            '<div class="widget-row widget-row-datetime-time">'
            '<div class="row-item">Ночь</div><div class="row-item">Утро</div>'
            '<div class="row-item">День</div></div></div>')
        parts, prov = G._parts(doc, today=TODAY)
        assert parts == {}
        assert prov["parts"] == int(Tier.ABSENT)


class TestIndependence:
    def test_it_actually_disagrees_with_yandex(self, mf, request):
        """The whole point of a second source: same city, same day, different
        model. If the two ever agreed on *everything*, the likely explanation
        is that one parser is reading the other's page.

        Two things changed here. It compared the `gm-` pair against Yandex,
        which after a partial re-record meant comparing July against August --
        the comparison was meaningless before the assertion even ran, so it now
        uses the `mf-` set, which is the same recording session as the Yandex
        fixture. And it asserted `abs(delta) < 3.0`, which is a fact about one
        afternoon: on the day this was rewritten both sources said exactly 12°,
        and two models agreeing to the degree is ordinary rather than
        suspicious.

        So it asserts independence across the *set* of readings rather than
        disagreement in any one of them, and sanity rather than a threshold:
        two forecasts for the same city on the same day cannot be 15° apart.
        """
        from app import extract as X
        ya = X.parse((request.path.parent / "fixtures" / "current.html")
                     .read_text(encoding="utf-8", errors="replace"))
        gm, y = mf.current, ya.current
        assert abs(gm.temp_c - y.temp_c) <= 8.0, (
            f"{gm.temp_c} against {y.temp_c} for the same city on the same "
            f"day -- one of these is not the place we asked for")

        readings = [(gm.temp_c, y.temp_c),
                    (mf.daily[0].temp_max_c, ya.daily[0].temp_max_c),
                    (mf.daily[0].temp_min_c, ya.daily[0].temp_min_c)]
        comparable = [(a, b) for a, b in readings
                      if a is not None and b is not None]
        assert comparable, "nothing comparable survived from either source"
        assert any(a != b for a, b in comparable), (
            f"every reading is identical across both sources: {comparable} -- "
            f"suspect one parser is being handed the other's page")


class TestMirror:
    """`meteofor.lv` is the same forecast service under its export brand -- the
    same numeric city ids, the same page shape -- and it answers the addresses
    `gismeteo.ru` refuses, which is how this project reaches Gismeteo at all
    from a Latvian box (`DECISIONS.md` §7).

    "Same site" is a claim, though, and this file exists because claims about
    someone else's HTML are worth checking. So: capture it and assert the
    parser gets the same *shape* out of it.

        make fixtures-gm

    Skipped when the fixture is absent, so the suite still runs on a machine
    that cannot reach either host. That is a real gap and it is deliberate: a
    fixture recorded on a machine that is not blocked would prove nothing about
    the machine that is, and pretending otherwise is worse than a skip. The
    live check is `make routes`.

    Note what is *not* asserted: matching values. The two fixtures are recorded
    minutes apart, and a mirror that disagreed by half a degree would be fine.
    A mirror that disagreed about which city it was describing would not -- and
    that is the identity check, which runs on every fetch regardless.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def mirror(cls, request):
        d = request.path.parent / "fixtures"
        cur = d / "mf-current.html"
        if not cur.exists():
            pytest.skip("no mirror fixture -- capture one with `make fixtures-gm`")
        read = lambda f: (f.read_text(encoding="utf-8", errors="replace")  # noqa: E731
                          if f.exists() else None)
        return G.parse(read(cur),
                       days_html=read(d / "mf-10days.html"),
                       hourly_html=read(d / "mf-hourly.html"))

    def test_the_hourly_page_never_starts_before_the_observation(self, request,
                                                                 mirror):
        """Recorded because `series.align_to_now` is built around it.

        Gismeteo's `/hourly/` page has historically started at the *next* whole
        hour -- an observation at 12:00 followed by a strip beginning 13:00,
        because their own page shows current conditions in a card above it.
        That is why `align_to_now` puts the observation at the head of the
        series: without it the strip simply had no column for now.

        The July capture had a gap of one hour. Today's has a gap of **zero**:
        the strip now includes the hour you are standing in. Both are fine, and
        the difference between them is not a bug in either direction -- when a
        covering entry exists `align_to_now` finds it and leaves the series
        alone, which is the degradation working. So the assertion is the
        property the alignment actually needs, and no longer the one number
        that happened to be true in July.

        What would be a real problem is a strip starting *before* the
        observation, or more than an hour after it: the first would mean the
        page is showing history, the second that we are matching against the
        wrong day.
        """
        if not (request.path.parent / "fixtures" / "mf-hourly.html").exists():
            pytest.skip("no hourly fixture")
        first = mirror.hourly[0]
        assert first.at is not None

        # `observed_epoch` came from `weather.cw`, which the source removed in
        # August 2026. The parser now takes it from the page's own clock --
        # `<time-value class="current-time" timestamp>`, the thing the site is
        # telling a reader the time is -- so this usually still has a reference
        # point. The fallback below reads the same element by hand, and matters
        # on the day that element moves too.
        #
        # Skipped rather than faked if both go. An alignment test with no
        # reference point is a test that always passes, which is worse than no
        # test: it would have gone on being green through exactly the change
        # that broke everything else here.
        page_now = mirror.current.observed_epoch
        if page_now is None:
            raw = (request.path.parent / "fixtures" / "mf-current.html")
            stamps = LH.fromstring(
                raw.read_text(encoding="utf-8", errors="replace")).xpath(
                '//time-value[contains(@class,"current-time")]/@timestamp')
            page_now = int(stamps[0]) if stamps else None
        if page_now is None:
            pytest.skip("the page no longer states a time to align against")

        gap = first.at - page_now
        assert -3600 <= gap <= 3600, (
            f"the hourly strip starts {gap}s from the page's own clock -- it "
            f"should begin at the current hour or the next one")

    def test_the_dedicated_hourly_page_is_worth_fetching(self, request, mirror):
        """The reason for the third request. The landing page gives eight
        columns at three-hour spacing; /hourly/ gives the actual hours. If this
        ever stops being true, drop the page rather than paying for it."""
        if not (request.path.parent / "fixtures" / "mf-hourly.html").exists():
            pytest.skip("no hourly fixture")
        assert len(mirror.hourly) > 8

    def test_it_is_the_city_we_asked_for(self, mirror):
        """The only assertion that would matter if the mirror ever diverged."""
        place = cities.get("yoshkar-ola")
        assert G.check_identity(mirror.ident, place) is None
        assert mirror.ident.geo_id == 11975

    def test_no_field_has_slipped_to_tier_three(self, mirror):
        """Which rung of the ladder each field arrives on.

        **This test earned its keep in August 2026 and is rewritten because of
        it.** `weather.cw` -- the hydration blob the whole current block was
        read from -- disappeared from all four pages. Nothing failed. The
        temperature kept arriving, because tier 3 takes the first
        `<temperature-value>` on the page whatever it is; everything else
        silently became `None`. What reached the phone was a hero with a
        question mark where the icon goes, and a number found by position.

        So it no longer demands tier 1 for the current block, which is gone.
        It demands what actually protects the reader: **nothing at tier 3.**
        Tier 3 means a value was located by shape, and a value located by
        shape can be any cell on the page -- that is precisely how a pressure
        reading becomes a temperature.
        """
        assert mirror.provenance.get("temp_c") == int(Tier.LABELLED), (
            "the current temperature is not coming from the header sentence; "
            "at tier 3 it is whatever `<temperature-value>` is first in the "
            "document, which is not a promise about anything")
        assert mirror.provenance.get("condition") == int(Tier.LABELLED)
        for field in ("daily.temp", "daily.pressure", "daily.wind"):
            assert mirror.provenance.get(field) == int(Tier.NAMED), field
        slipped = [k for k, v in mirror.provenance.items()
                   if isinstance(v, int) and v >= int(Tier.SHAPE)]
        assert not slipped, f"read by position, not by name: {slipped}"
        assert mirror.ident.lat is not None

    def test_it_yields_a_usable_forecast(self, mirror):
        assert mirror.current.temp_c is not None
        assert len(mirror.hourly) >= 8
        assert len(mirror.daily) >= 5

    def test_the_url_shape_is_identical(self):
        """The id does not change between hosts, which is why the host is a
        parameter rather than a rewrite."""
        place = cities.get("yoshkar-ola")
        gm = G.urls_for(place, "https://www.gismeteo.ru")
        mf = G.urls_for(place, "https://meteofor.lv/ru")
        assert gm[0].endswith("/weather-yoshkar-ola-11975/")
        assert mf[0] == "https://meteofor.lv/ru/weather-yoshkar-ola-11975/"
        assert mf[1].endswith("/hourly/") and mf[2].endswith("/10-days/")
        assert [u.rsplit("/weather-", 1)[1] for u in gm] == \
               [u.rsplit("/weather-", 1)[1] for u in mf], \
            "the paths must differ only in host"

    def test_a_trailing_slash_in_the_host_does_not_double_up(self):
        place = cities.get("yoshkar-ola")
        assert G.urls_for(place, "https://meteofor.lv/ru/")[0] == \
            "https://meteofor.lv/ru/weather-yoshkar-ola-11975/"


# --- what the state blob took with it ---------------------------------------

MSK = dt.timezone(dt.timedelta(hours=3))


def _page_now(html: str) -> int | None:
    """The page's own clock, read without lxml.

    `<time-value class="current-time" timestamp="...">` sits next to the
    breadcrumbs, spread over five lines of markup, so the pattern has to cross
    newlines -- which `[^>]*` does, since a newline is not a `>`. Written the
    obvious way with `\\s+` it matches nothing and every test below passes by
    skipping, which is the failure mode this file keeps having to design around.
    """
    m = re.search(r'current-time"[^>]*timestamp="(\d+)"', html)
    return int(m.group(1)) if m else None


def _strip_stamps(html: str) -> list[int]:
    """The epoch under each column of the landing page's widget, by regex."""
    i = html.find("widget-row-datetime-time")
    if i < 0:
        return []
    j = html.find("widget-row-", i + 30)
    return [int(t) for t in
            re.findall(r'timestamp="(\d+)"', html[i: j if j > 0 else len(html)])]


def _strip_values(html: str, row: str) -> list[float]:
    """One captioned row of that widget, as numbers, sharing no code with the
    parser -- no lxml, no XPath, no `_ROWS` table.

    The same second-opinion trick as `_row_pairs` above, and for the same
    reason: a test that pastes in the numbers a fixture happened to contain
    would bless a parser that had started reading the wrong column just as
    readily as a correct one. Two readings by different means that agree are
    evidence. One reading checked against itself is a tautology.

    Rows come in two shapes on this page -- typed elements (`<speed-value
    value="3">`) and bare text in a cell (`<div class="row-item item-9"> 92
    </div>`) -- so both are tried, typed first.
    """
    start = html.find(f'data-row="{row}"')
    if start < 0:
        return []
    end = html.find("data-row=", start + 1)
    block = html[start: end if end > 0 else len(html)]
    block = block[block.find("</p>") + 4:]                 # past the caption
    typed = re.findall(r'<[a-z-]+-value value="(-?[\d.]+)"', block)
    if typed:
        return [float(v) for v in typed]
    return [float(v.replace(",", ".")) for v in
            re.findall(r'row-item[^>]*>\s*(-?\d+(?:[.,]\d+)?)\s*<', block)]


class TestWhatTheStateBlobTookWithIt:
    """August 2026: `weather.cw` disappeared from all four Gismeteo pages.

    The visible symptom was one question mark where the hero's icon goes, and
    that is the whole problem with this class of failure -- the icon was the
    only part that *looked* wrong. Underneath it, `feels_like_c`,
    `humidity_pct`, `pressure_mmhg`, `wind_ms`, `wind_dir` and the observation
    time had all silently become `None`, which took the entire «Подробности»
    card off the Gismeteo tab. A card that renders nothing is indistinguishable
    from a source that never published those fields, so nothing said why. And
    the temperature -- the one number a weather app cannot be wrong about --
    was still arriving, from tier 3, which finds the first
    `<temperature-value>` in the document whatever it happens to be.

    Everything the blob carried is still on the page, in the captioned grid the
    hourly strip is read from. Two properties make taking it honest rather than
    convenient, and both are tested here:

    * the **column is chosen by time**, not by position -- column 0 is
      midnight, and this parser has already shipped that bug once;
    * the **provenance records the weaker step**. The rows answer at tier 1,
      the alignment that picks a cell out of them is tier 2, and a value is
      only as good as the weakest link that produced it. Claiming tier 1 would
      tell `health.fallback_profile` the ground is firmer than it is.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def raw(cls, request):
        p = request.path.parent / "fixtures" / "mf-current.html"
        if not p.exists():
            pytest.skip("no mirror fixture -- capture one with `make fixtures-gm`")
        return p.read_text(encoding="utf-8", errors="replace")

    def test_the_recording_really_is_one_without_the_blob(self, request):
        """A guard on the fixture, not on the parser.

        Everything below is about a page that has no `weather.cw`. If a future
        `make fixtures-gm` captures one that has it again -- the source
        restores it, or a mirror lags -- these tests keep passing while
        asserting nothing at all about the recovery path. Better to fail here
        and say so.
        """
        d = request.path.parent / "fixtures"
        present = []
        for name in ("mf-current", "mf-10days", "mf-hourly", "mf-3days"):
            f = d / f"{name}.html"
            if not f.exists():
                continue
            st = G.state(f.read_text(encoding="utf-8", errors="replace")) or {}
            if (st.get("weather") or {}).get("cw"):
                present.append(name)
        assert not present, (
            f"`weather.cw` is back on {present}. Good news, but the tests in "
            "this class no longer exercise the recovery they were written for "
            "-- point them at a kept copy of a blob-less page, or delete them "
            "along with the recovery.")

    def test_the_july_capture_still_has_one(self, request):
        """...and the tier-1 path is still exercised by *something*.

        `TestCurrent` asserts `Tier.NAMED` on four fields. The day both
        fixtures are blob-less, those assertions are testing a code path no
        input reaches, and the first person to touch `_current` will delete it
        as dead.
        """
        f = request.path.parent / "fixtures" / "gm-current.html"
        st = G.state(f.read_text(encoding="utf-8", errors="replace")) or {}
        assert (st.get("weather") or {}).get("cw"), (
            "no capture left has the state blob; `_current`'s tier-1 branch is "
            "now untested")

    def test_nothing_it_carried_was_quietly_dropped(self, mf):
        """The regression proper. Every field is present, or the card goes."""
        c = mf.current
        missing = [f for f in ("temp_c", "feels_like_c", "humidity_pct",
                               "pressure_mmhg", "wind_ms", "wind_dir",
                               "condition", "icon", "observed_epoch")
                   if getattr(c, f) is None]
        assert not missing, f"lost with the state blob: {missing}"

    def test_the_recovery_never_claims_to_be_the_blob(self, mf):
        """Tier 2 exactly: not 1, which would be a lie, and not 3, which would
        mean the value was found by position and could be any cell."""
        for f in ("temp_c", "feels_like_c", "humidity_pct", "pressure_mmhg",
                  "wind_ms", "wind_dir", "condition"):
            assert mf.provenance.get(f) == int(Tier.LABELLED), (
                f"{f} is recorded as tier {mf.provenance.get(f)}")

    def test_the_column_is_the_one_covering_now_and_not_the_first(self, mf, raw):
        """The assertion that would catch the bug this parser already made.

        Read by a different mechanism -- regex over the raw markup -- and
        checked against *both* candidates, so it fails whether the parser takes
        column zero or drifts one along. It also refuses to run on a recording
        where the two coincide, because there it proves nothing.
        """
        now, stamps = _page_now(raw), _strip_stamps(raw)
        assert now and stamps, "the page no longer states a time, or has no strip"
        want = max(i for i, t in enumerate(stamps) if t <= now)
        assert want != 0, (
            "this fixture was captured in the strip's first column, where a "
            "parser that reads column zero looks correct. Recapture later in "
            "the day.")

        for field, row in (("humidity_pct", "humidity"),
                           ("pressure_mmhg", "pressure"),
                           ("wind_ms", "wind-speed"),
                           ("feels_like_c", "temperature-heat-index")):
            vals = _strip_values(raw, row)
            assert len(vals) >= len(stamps), f"{row}: {len(vals)} for {len(stamps)}"
            assert getattr(mf.current, field) == vals[want], (
                f"{field} is not the column covering {now}; "
                f"column 0 holds {vals[0]}, column {want} holds {vals[want]}")

    def test_the_observation_time_is_the_pages_own_clock(self, mf, raw):
        assert mf.current.observed_epoch == _page_now(raw)

    def test_a_strip_that_stops_before_now_is_refused(self, raw):
        """Drop, never stretch.

        A page whose newest column is hours behind its own clock is a page
        mid-redesign, and the last column of it is not «сейчас» merely by being
        last. The temptation is to take it anyway -- something beats nothing --
        and that is the reasoning that puts a plausible wrong number in front
        of someone who will dress for it.

        Forged by moving the page's clock a day forward rather than by deleting
        the strip, because deleting it tests the empty case, which is easy.
        """
        now = _page_now(raw)
        moved = raw.replace(f'timestamp="{now}"', f'timestamp="{now + 86400}"', 1)
        assert moved != raw
        got = G.parse(moved, today=dt.datetime.fromtimestamp(now, tz=MSK).date())
        for f in ("feels_like_c", "humidity_pct", "pressure_mmhg", "wind_ms"):
            assert getattr(got.current, f) is None, (
                f"{f} was taken from the last column of a strip that ends "
                f"before the page's own clock")

    def test_the_temperature_no_longer_arrives_by_shape(self, mf):
        """What actually reached the phone while this was broken: a number the
        parser found by being first in the document. It was right, which is the
        least reassuring thing about it."""
        assert mf.provenance["temp_c"] != int(Tier.SHAPE)
        assert mf.current.temp_c == pytest.approx(
            max(h.temp_c for h in mf.hourly[:2]), abs=3.0), (
            "the headline disagrees with the hours either side of it")


class TestTheHourlyStripIsReadByColumn:
    """The ten-day rows were already read as containers (`_cells`), because a
    row missing one value shifts every later day onto its neighbour. The
    hourly strip read its temperatures and tooltips as flat lists, which is
    the same trap one page over."""

    def _hours(self, mutate):
        raw = (FIXTURES / "mf-hourly.html").read_text(encoding="utf-8")
        doc = LH.fromstring(raw)
        mutate(doc)
        hours, _ = G._hours(doc, G.state(raw) or {})
        return {h.time: h for h in hours}

    def test_a_blank_temperature_costs_its_own_hour_only(self):
        good = self._hours(lambda d: None)

        def blank(doc):
            tv = G._temperature_chart(doc).xpath(".//temperature-value")[9]
            tv.getparent().remove(tv)

        bad = self._hours(blank)
        assert len(bad) == len(good) - 1
        assert all(bad[t].temp_c == good[t].temp_c for t in bad)

    def test_a_missing_tooltip_costs_its_own_hour_only(self):
        good = self._hours(lambda d: None)

        def strip(doc):
            cell = G._cells(doc.xpath(G._TOKEN.format(cls="widget-row-icon"))[0])[9]
            del cell.attrib["data-tooltip"]

        bad = self._hours(strip)
        assert sum(bad[t].condition != good[t].condition for t in bad) == 1
