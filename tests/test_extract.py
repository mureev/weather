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
from itertools import pairwise

import pytest

from app import extract as X
from app.models import ParseError, Tier


@pytest.fixture(scope="module")
def parsed(request):
    html = (request.path.parent / "fixtures" / "current.html").read_text(
        encoding="utf-8", errors="replace")
    return X.parse(html, today=dt.date(2026, 7, 31))


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
        got = X.parse(html, today=dt.date(2026, 7, 31))
        assert got.ident.name == "Йошкар-Ола"
        assert X.check_identity(got.ident, expect_lat=56.6344,
                                expect_lon=47.8999) is None


class TestCurrent:
    def test_comes_from_the_flight_stream(self, parsed):
        """Tier 1: typed JSON from the RSC payload, not scraped text."""
        assert parsed.provenance["temp_c"] == int(Tier.NAMED)
        assert parsed.provenance["pressure_mmhg"] == int(Tier.NAMED)

    def test_values(self, parsed):
        c = parsed.current
        assert c.temp_c == 16.0
        assert c.feels_like_c == 17.0
        assert c.condition == "Ясно"
        assert c.humidity_pct == 90.0
        assert c.pressure_mmhg == 745.0
        assert c.wind_ms == 1.0
        assert c.wind_dir == "западный"
        assert c.icon == "clear-night"

    def test_nowcast(self, parsed):
        assert parsed.nowcast == "Сегодня осадков не ожидается"

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
        dt.date(2026, 7, 30),      # the day before it was recorded
        dt.date(2026, 7, 31),      # the day it was recorded
        dt.date(2026, 8, 1),       # the day after -- the case that bit
        dt.date(2026, 8, 9),       # a week later
        dt.date(2027, 1, 15),      # a different year entirely
    ])
    def test_the_stated_date_wins_over_the_clock(self, current_html, pretend):
        got = X.parse(current_html, today=pretend)
        assert got.daily[0].date == "2026-07-31", \
            f"parsed as if it were {pretend}, and the dates moved"
        assert len(got.daily) == 10

    def test_a_purely_relative_header_still_resolves(self):
        """«Завтра» with no date is the fallback path, and it does need the
        clock -- that is the one case where `today` is all there is."""
        assert X._date_from_text("Завтра", today=dt.date(2026, 7, 31)) == \
            dt.date(2026, 8, 1)

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
        assert parsed.daily[0].date == "2026-07-31"

    def test_dates_are_consecutive(self, parsed):
        dates = [dt.date.fromisoformat(d.date) for d in parsed.daily]
        for a, b in pairwise(dates):
            assert (b - a).days == 1

    def test_four_parts_per_day(self, parsed):
        assert [p.name for p in parsed.daily[0].parts] == \
            ["утро", "день", "вечер", "ночь"]

    def test_part_values(self, parsed):
        morning = parsed.daily[0].parts[0]
        assert morning.temp_c == 19.0
        assert morning.feels_like_c == 21.0
        assert morning.condition == "Небольшой дождь"
        assert morning.humidity_pct == 76.0
        assert morning.pressure_mmhg == 744.0
        assert morning.wind_dir == "северный"

    def test_wind_keeps_its_decimal(self, parsed):
        """The a11y prose says "1,7 м/с"; the visible cell rounds it to "2".

        A `[^,]+` capture truncates at the *decimal comma* and yields 1. This
        asserts we read the real value.
        """
        assert parsed.daily[0].parts[0].wind_ms == 1.7

    def test_feels_like_does_not_steal_the_air_temperature(self, parsed):
        """"температура воздуха +19°, ощущается как +21°" -- the first number
        is the air temperature even though the second is larger."""
        m = parsed.daily[0].parts[0]
        assert (m.temp_c, m.feels_like_c) == (19.0, 21.0)

    def test_extras(self, parsed):
        d = parsed.daily[0]
        assert d.uv_index == 5.0
        assert d.water_temp_c == 18.0
        assert d.sunrise == "03:46"
        assert d.sunset == "20:02"
        assert d.daylight and "16" in d.daylight

    def test_min_max_summary(self, parsed):
        d = parsed.daily[0]
        assert d.temp_min_c == 14.0
        assert d.temp_max_c == 20.0


class TestHourly:
    def test_present_and_deduplicated(self, parsed):
        """The handover docs routed hourly to Open-Meteo "by design -- the
        scrape has no reliable hourly series". The 2026 page has one."""
        assert len(parsed.hourly) == 24
        assert len({h.time for h in parsed.hourly}) == 24

    def test_values(self, parsed):
        h = parsed.hourly[0]
        assert h.time == "21:00"
        assert h.temp_c == 16.0
        assert h.condition == "Ясно"

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
        assert len(s) > 100_000
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
        assert cur.temp_c == 16.0                   # the city's, not ours (20)
