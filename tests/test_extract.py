"""Parser tests against **real** 2026 Yandex HTML.

The previous build of this project never ran against the live page -- its
container had no outbound HTTP to Yandex -- so its selectors were hypotheses
and its fixtures were reconstructed markup. These fixtures were captured from
`yandex.ru/pogoda/ru/yoshkar-ola` on 31 July 2026 from a real browser-shaped
request. That makes these tests the difference between "the logic is verified"
and "the parser is correct against reality".

Re-record them any time the app looks off::

    curl -H "X-Debug-Token: $DEBUG_TOKEN" \\
      "https://your-host/weather/api/debug/raw?city=yoshkar-ola" \\
      > tests/fixtures/current.html
    pytest

Tests passing against re-recorded HTML means the parser still matches reality.
Tests failing tells you exactly which assumption broke. That two-minute loop is
what this whole project is designed around.
"""

import datetime as dt
import pathlib
import re
from itertools import pairwise

import pytest

from app import extract as X
from app.models import ParseError, Tier

# --- facts read out of the fixture, never pasted in -------------------------
#
# Every number below used to be a literal — `== 16.0`, `== "2026-07-31"` — and
# every `make fixtures` broke a dozen tests whose only repair was to paste in
# the new weather. That is the documented trap: such a test would bless a
# parser that had started reading the wrong row just as cheerfully as a correct
# one, because the only thing it checks is that somebody updated the number.
#
# So they are derived, by mechanisms that share nothing with `extract.py`: a
# regex over the raw markup rather than its XPath, and the page's own prose
# date rather than `_date_from_text`. Two independent readings that agree are
# evidence; one reading checked against a hand-typed constant is not.
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
HTML = (FIXTURES / "current.html").read_text(encoding="utf-8", errors="replace")

_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def _recorded_date(html: str) -> dt.date:
    """The day the page says it is, from «Сегодня, 13 августа»."""
    m = re.search(r"Сегодня,\s*(\d{1,2})\s+([а-я]+)", html)
    if not m:
        raise AssertionError("the fixture no longer states its own date")
    day, month = int(m.group(1)), m.group(2)
    year = int(re.search(r"20\d\d", html).group(0))
    return dt.date(year, _MONTHS.index(month) + 1, day)


def _headline_temp(html: str) -> float:
    """The observed temperature, straight out of the flight stream's `fact`.

    `\\\\?"` because the stream is JSON embedded in JavaScript string literals,
    so the key arrives as `temperature\\":12` as often as `"temperature":12`.
    The first version of this matched only the unescaped form, found nothing,
    and raised -- which is the right failure, but it is worth saying why the
    pattern looks like that.

    **It is anchored on `fact`, and the reason is the best argument in this
    file for never reading by position.** The version before this one took the
    *first* `temperature` in the document. On the July capture that was the
    city's. On the very next recording it was `userLocationLaasFact` -- the
    weather where Yandex believes *our server* is, which on a Latvian box is a
    different country -- and every derived assertion in this module and in
    `test_api.py` quietly became about Riga.

    So a helper written specifically to stop tests being "tests of the weather"
    reached for the first match it found and picked up the one value in the
    whole stream the parser exists to refuse. `extract.py` has had a dedicated
    test against that field since the beginning; the test's own scaffolding did
    not. Ask what a value *is*, including in the tools that check the tools.
    """
    m = re.search(r'\\?"fact\\?":\s*\{\\?"temperature\\?":(-?\d+(?:\.\d+)?)', html)
    if not m:
        raise AssertionError(
            "no `fact` block in the raw fixture -- if Yandex renamed it, find "
            "the city's own reading again rather than relaxing this to the "
            "first temperature on the page")
    ours = float(m.group(1))
    theirs = re.search(r'userLocationLaasFact\\?":\s*\{\\?"temperature\\?":'
                       r'(-?\d+(?:\.\d+)?)', html)
    if theirs and float(theirs.group(1)) == ours:
        # Not fatal on its own -- two cities can share a temperature -- but on
        # this fixture they differ, and if they ever stop differing the guard
        # below is asleep. Recapture rather than assert against a coincidence.
        raise AssertionError(
            f"the city's reading and the requester's are both {ours}: this "
            f"fixture cannot tell a correct parser from one reading the wrong "
            f"city. Recapture it.")
    return ours


# The eight long forms every source is normalised to. A two-letter
# abbreviation reaching the client means three lookup tables on the front end.
RU_DIRS = ("северный", "северо-восточный", "восточный", "юго-восточный",
           "южный", "юго-западный", "западный", "северо-западный", "штиль")

RECORDED = _recorded_date(HTML)
NOW_C = _headline_temp(HTML)



@pytest.fixture(scope="module")
def parsed(request):
    html = (request.path.parent / "fixtures" / "current.html").read_text(
        encoding="utf-8", errors="replace")
    return X.parse(html, today=RECORDED)


class TestIdentity:
    def test_resolves_the_city_we_asked_for(self, parsed):
        assert parsed.ident.name == "Йошкар-Ола"
        assert parsed.ident.slug == "yoshkar-ola"
        assert parsed.ident.geo_id == 41

    def test_identity_check_passes_for_the_right_slug(self, parsed):
        assert X.check_identity(parsed.ident, expect_slug="yoshkar-ola") is None

    def test_identity_check_rejects_the_wrong_city(self, parsed):
        """The Columbus, Ohio failure.

        `/pogoda` geolocates the requesting IP when its addressing hints go
        stale and returns a perfectly-formed forecast for somewhere else. It
        does not error. This check is the only thing between that page and the
        user believing it.
        """
        why = X.check_identity(parsed.ident, expect_slug="columbus")
        assert why is not None and "yoshkar-ola" in why

    def test_identity_check_rejects_distant_coordinates(self, parsed):
        why = X.check_identity(parsed.ident, expect_lat=39.96, expect_lon=-83.0)
        assert why is not None and "resolved to" in why

    def test_latlon_addressing_resolves_the_same_place(self, request):
        html = (request.path.parent / "fixtures" / "latlon.html").read_text(
            encoding="utf-8", errors="replace")
        got = X.parse(html, today=RECORDED)
        assert got.ident.name == "Йошкар-Ола"
        assert X.check_identity(got.ident, expect_lat=56.6344,
                                expect_lon=47.8999) is None


class TestCurrent:
    def test_comes_from_the_flight_stream(self, parsed):
        """Tier 1: typed JSON from the RSC payload, not scraped text."""
        assert parsed.provenance["temp_c"] == int(Tier.NAMED)
        assert parsed.provenance["pressure_mmhg"] == int(Tier.NAMED)

    def test_values(self, parsed):
        """Units and fields, not weather.

        Every line here used to be a literal off one recording — `== "Ясно"`,
        `== 745.0` — and every re-record broke the lot. Pasting in the new
        numbers is not a repair: it would bless a parser that had started
        reading humidity into pressure exactly as readily, because the only
        thing such a test checks is that somebody typed the new value.

        So this asserts what cannot drift: that each field is in the unit and
        range its name promises, and that the ones with a relationship keep it.
        A pressure of 745 mmHg and one of 993 hPa are both plausible numbers
        and only one of them belongs in this field.
        """
        c = parsed.current
        assert c.temp_c == NOW_C
        assert c.condition and c.condition[0].isupper()
        assert c.icon and c.icon != "unknown"
        assert -70 <= c.feels_like_c <= 60
        assert 0 <= c.humidity_pct <= 100
        # mmHg, never hPa: the same reading is ~745 or ~993 and both look fine.
        assert 600 <= c.pressure_mmhg <= 820
        assert 0 <= c.wind_ms <= 60
        assert c.wind_dir in RU_DIRS

    def test_nowcast(self, parsed):
        """Present and a sentence. Its *content* is the weather -- it says
        either that rain is coming or that none is -- so asserting the words
        pins the test to the hour it was recorded."""
        assert parsed.nowcast and len(parsed.nowcast) > 10
        assert parsed.nowcast[0].isupper()

    def test_missing_temperature_raises_rather_than_returning_zero(self):
        """A scraper that returns 0 shows +0° in January and is believed."""
        with pytest.raises(ParseError):
            X.parse("<html><head><title>Погода в Никуда</title></head>"
                    "<body><h1>Погода в Никуда</h1></body></html>")

    def test_captcha_raises(self):
        with pytest.raises(ParseError, match="captcha"):
            X.parse("<html><body>Подтвердите, что запросы отправляли вы"
                    "</body></html>")


class TestDatesDoNotDependOnWhenYouParse:
    """A fixture recorded on the 31st, parsed on the 1st, used to shift every
    date by a day and drop the last one off the end -- because the header
    «Сегодня, 31 июля» was read as "today" rather than as "31 July".

    That is a bug with a clock in it: the suite passes all afternoon and goes
    red at midnight UTC, and the session that inherits it has no idea why.
    A parser given the same bytes must return the same dates forever.
    """

    @pytest.mark.parametrize("pretend", [
        dt.timedelta(days=-1),     # the day before it was recorded
        dt.timedelta(days=0),      # the day it was recorded
        dt.timedelta(days=1),      # the day after -- the case that bit
        dt.timedelta(days=9),      # a week and a half later
        dt.timedelta(days=155),    # a different year entirely
    ])
    def test_the_stated_date_wins_over_the_clock(self, current_html, pretend):
        got = X.parse(current_html, today=RECORDED + pretend)
        assert got.daily[0].date == RECORDED.isoformat(), \
            f"parsed as if it were {pretend}, and the dates moved"
        assert len(got.daily) == 10

    def test_a_purely_relative_header_still_resolves(self):
        """«Завтра» with no date is the fallback path, and it does need the
        clock -- that is the one case where `today` is all there is."""
        assert X._date_from_text("Завтра", today=RECORDED) == \
            RECORDED + dt.timedelta(days=1)

    def test_the_year_is_chosen_to_be_nearest(self):
        """The page never states one. Late December looking at January."""
        assert X._date_from_text("2 января", today=dt.date(2026, 12, 28)) == \
            dt.date(2027, 1, 2)


class TestDaily:
    def test_day_count(self, parsed):
        assert len(parsed.daily) == 10

    def test_duplicate_layout_blocks_are_collapsed(self, parsed):
        """The page renders the forecast twice -- wide layout and narrow.

        A naive walk yields 10 days followed by the same 10 days again, which
        looks exactly like a working 20-day forecast until you read the dates.
        """
        dates = [d.date for d in parsed.daily]
        assert len(dates) == len(set(dates))

    def test_comes_from_accessibility_prose(self, parsed):
        assert parsed.provenance["daily"] == int(Tier.LABELLED)

    def test_first_day_is_today(self, parsed):
        assert parsed.daily[0].date == RECORDED.isoformat()

    def test_dates_are_consecutive(self, parsed):
        dates = [dt.date.fromisoformat(d.date) for d in parsed.daily]
        for a, b in pairwise(dates):
            assert (b - a).days == 1

    def test_four_parts_per_day(self, parsed):
        assert [p.name for p in parsed.daily[0].parts] == \
            ["утро", "день", "вечер", "ночь"]

    def test_part_values(self, parsed):
        """Same rule as `TestCurrent.test_values`: units and ranges."""
        morning = parsed.daily[0].parts[0]
        assert morning.condition and morning.condition[0].isupper()
        assert -70 <= morning.temp_c <= 60
        assert -70 <= morning.feels_like_c <= 60
        assert 0 <= morning.humidity_pct <= 100
        assert 600 <= morning.pressure_mmhg <= 820
        assert morning.wind_dir in RU_DIRS

    def test_wind_keeps_its_decimal(self, parsed):
        """The a11y prose says "1,7 м/с"; the visible cell rounds it to "2".

        A `[^,]+` capture truncates at the *decimal comma* and yields 1. This
        asserts we read the real value.
        """
        stated = re.search(r"(\d+),(\d+)\s*м/с", HTML)
        assert stated, "the fixture no longer states a decimal wind speed"
        want = float(f"{stated.group(1)}.{stated.group(2)}")
        got = [pt.wind_ms for d in parsed.daily for pt in (d.parts or [])
               if pt.wind_ms is not None]
        assert want in got, (
            f"the page says {want} m/s and no part reports it: {sorted(set(got))}"
            f" -- a `[^,]+` capture truncates at the decimal comma")
        assert any(v % 1 for v in got), "every wind speed is a whole number"

    def test_feels_like_does_not_steal_the_air_temperature(self, parsed):
        """"температура воздуха +19°, ощущается как +21°" -- the first number
        is the air temperature even though the second is larger.

        **Anchored on «утром», and that word is the whole test.** The page
        writes the same clause about two different things:

            Сейчас в Йошкар-Оле пасмурно, температура воздуха +9°, …
            Сегодня, 14 августа: утром температура воздуха +9°, …

        The first is an observation, the second is a part of a day, and this
        test compares against parts. It used to take whichever came *first in
        the document* and got away with it for as long as a part happened to
        carry the same pair -- then a recording arrived where «сейчас» was 9/8
        and every part was something else, and the test accused the parser of a
        bug it does not have.

        Third time in this file, which is enough to call it a pattern: a helper
        written to keep tests from being tests of the weather picked its value
        by position, and position is not a promise about anything. Ask what the
        sentence is *about*.
        """
        stated = re.search(
            r"утром температура воздуха ([+\u2212-]?\d+)°,\s*ощущается как "
            r"([+\u2212-]?\d+)°", HTML)
        assert stated, "the fixture no longer states a morning pair"
        air, feels = (float(g.replace("\u2212", "-").replace("+", ""))
                      for g in stated.groups())
        pairs = [(pt.temp_c, pt.feels_like_c) for d in parsed.daily
                 for pt in (d.parts or [])]
        assert (air, feels) in pairs, (
            f"the page says air {air}, feels {feels}; no part reports that "
            f"pair -- the larger number is being read as the air temperature")

    def test_the_observation_prose_agrees_with_the_current_reading(self, parsed):
        """The other half of the sentence above, and worth its own test now
        that the two are told apart.

        «Сейчас в Йошкар-Оле пасмурно, температура воздуха +9°, ощущается как
        +8°» is the page describing *this moment* in prose, next to the same
        four numbers in its flight stream. Two independent statements of one
        fact, so they have to agree -- and if the parser ever starts reading
        the observation out of a forecast cell, this is what notices.
        """
        # Two traps in one clause, and both make the pattern find nothing at
        # all rather than find the wrong thing -- which is the good failure,
        # but only if you know to look.
        #
        # `Сейчас в\xa0Йошкар-Оле`: a **non-breaking space** between the
        # preposition and the city, because Russian typography does not leave a
        # one-letter preposition at the end of a line. `\s` matches it; a
        # literal space does not. `ru_text.clean` has a table for exactly this
        # and the reason is the same.
        #
        # And one comma, not two: «Сейчас в Йошкар-Оле пасмурно,» runs the city
        # and the sky together with no punctuation between them, so the
        # condition has to be recovered from the tail rather than captured as
        # its own field.
        said = re.search(
            r"Сейчас\s+в\s+([^,]+),\s*температура воздуха ([+\u2212-]?\d+)°,"
            r"\s*ощущается как ([+\u2212-]?\d+)°", HTML)
        assert said, "the page no longer describes the current conditions"
        where, air, feels = said.groups()
        num = lambda g: float(g.replace("\u2212", "-").replace("+", ""))  # noqa: E731
        c = parsed.current
        assert c.temp_c == num(air), f"prose says {air}, parser says {c.temp_c}"
        assert c.feels_like_c == num(feels), (
            f"prose says it feels like {feels}, parser says {c.feels_like_c}")
        assert c.condition and c.condition.lower() in where.lower(), (
            f"the page says «{where}» and the parser read {c.condition!r}")

    def test_extras(self, parsed):
        """Shapes and ranges. Sunrise on 31 July and on 13 August differ by
        half an hour, which says nothing about the parser."""
        d = parsed.daily[0]
        assert 0 <= d.uv_index <= 12
        assert -5 <= d.water_temp_c <= 40
        for t in (d.sunrise, d.sunset):
            assert re.fullmatch(r"[0-2]\d:[0-5]\d", t or ""), t
        assert d.sunrise < d.sunset, "the sun sets before it rises"
        assert d.daylight and re.search(r"\d", d.daylight)

    def test_min_max_summary(self, parsed):
        """The summary has to bracket the parts it summarises. That is a
        property of a correct read and survives any weather; `== 14.0` is a
        property of one afternoon."""
        d = parsed.daily[0]
        assert d.temp_min_c <= d.temp_max_c
        temps = [pt.temp_c for pt in (d.parts or []) if pt.temp_c is not None]
        if temps:
            assert d.temp_min_c <= min(temps) and max(temps) <= d.temp_max_c, (
                f"summary {d.temp_min_c}..{d.temp_max_c} does not contain the "
                f"parts {sorted(temps)}")


class TestHourly:
    def test_present_and_deduplicated(self, parsed):
        """The handover docs routed hourly to Open-Meteo "by design -- the
        scrape has no reliable hourly series". The 2026 page has one."""
        assert len(parsed.hourly) == 24
        assert len({h.time for h in parsed.hourly}) == 24

    def test_values(self, parsed):
        h = parsed.hourly[0]
        assert re.fullmatch(r"[0-2]\d:[0-5]\d", h.time), h.time
        assert h.temp_c == NOW_C, \
            "the strip does not start at the observed hour"
        assert h.condition and h.condition[0].isupper()

    def test_not_degenerate(self, parsed):
        temps = [h.temp_c for h in parsed.hourly]
        assert len(set(temps)) > 1


class TestDates:
    @pytest.mark.parametrize("text,expect", [
        ("Сегодня, 31 июля", "2026-07-31"),
        ("Завтра, 1 августа", "2026-08-01"),
        ("Воскресенье, 2 августа", "2026-08-02"),
    ])
    def test_parsing(self, text, expect):
        got = X._date_from_text(text, today=dt.date(2026, 7, 31))
        assert got.isoformat() == expect

    def test_year_rollover_picks_the_nearest_year(self):
        """The page never states a year. On 28 December, "3 января" is next
        year -- not eleven months ago."""
        got = X._date_from_text("3 января", today=dt.date(2026, 12, 28))
        assert got.isoformat() == "2027-01-03"

    def test_rollover_the_other_way(self):
        got = X._date_from_text("29 декабря", today=dt.date(2027, 1, 2))
        assert got.isoformat() == "2026-12-29"


class TestFlightStream:
    def test_decodes(self, request):
        html = (request.path.parent / "fixtures" / "current.html").read_text(
            encoding="utf-8", errors="replace")
        s = X.flight(html)
        # Several pushes' worth, decoded and joined. The fixture keeps only
        # the pushes holding a value something reads (tools/trim_fixtures.py);
        # the whole stream of the recorded page decoded to ~480 kB.
        assert len(s) > 5_000
        assert '"fact"' in s

    def test_never_reads_the_requester_location_fact(self, request):
        """The stream also carries `userLocationLaasFact` -- the weather where
        Yandex thinks *we* are. On a foreign-hosted server that is a different
        city, and reading it would reproduce the Columbus failure from inside
        our own parser."""
        html = (request.path.parent / "fixtures" / "current.html").read_text(
            encoding="utf-8", errors="replace")
        s = X.flight(html)
        assert "userLocationLaasFact" in s          # it really is in there
        got = X._current_from_flight(s)
        assert got is not None
        cur, _ = got
        assert cur.temp_c == NOW_C                  # the city's, not ours
