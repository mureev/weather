"""Take the real page and break it the way reality breaks it.

Every corruption in here is a failure mode that has actually been observed --
in this project's research pass, in its predecessor, or in the wild -- not an
invented one. The assertion is never "it still works". It is **"it degrades
instead of serving nonsense"**, which is a different and much more useful
property.

The thing worth internalising: a parser that returns nothing gets caught by the
first `if not data` in the call chain and costs you nothing. A parser that
returns 743 because a redesign moved the pressure cell will tell you it is +743
degrees, or a plausible +55 after some well-meaning clamp, and you will believe
it. These tests are about the second kind.
"""

import datetime as dt
import re

import pytest

from app import extract as X
from app import validation as V
from app.models import Current, Day, DayPart, Hour, ParseError

TODAY = dt.date(2026, 7, 31)


@pytest.fixture(scope="module")
def raw(request) -> str:
    return (request.path.parent / "fixtures" / "current.html").read_text(
        encoding="utf-8", errors="replace")


class TestHostileResponses:
    def test_captcha_interstitial(self):
        with pytest.raises(ParseError, match="captcha"):
            X.parse("<html><body><h1>Ой, captcha</h1>"
                    "Подтвердите, что запросы отправляли вы</body></html>")

    def test_soft_404_that_returns_200(self):
        """The worst kind of error page: HTTP 200, valid HTML, no data."""
        with pytest.raises(ParseError):
            X.parse("<html><head><title>Страница не найдена</title></head>"
                    "<body><h1>Ничего не найдено</h1></body></html>")

    def test_empty_body(self):
        with pytest.raises(ParseError):
            X.parse("<html><body></body></html>")

    def test_truncated_response(self, raw):
        """A connection cut mid-stream. Half a flight payload must not become
        half a forecast."""
        with pytest.raises(ParseError):
            X.parse(raw[:40_000], today=TODAY)


class TestWrongPlace:
    def test_wrong_city_parses_perfectly_and_is_still_rejected(self, raw):
        """This is *the* dangerous failure.

        `/pogoda` geolocates the requesting IP when its addressing hints go
        stale, and hands back a beautifully-formed, entirely parseable forecast
        for somewhere else. The research pass asked for Yoshkar-Ola and got
        Columbus, Ohio. Nothing downstream can catch this -- the numbers are
        internally consistent, in range, smooth, and completely wrong.
        """
        swapped = (raw.replace("Йошкар-Ола", "Колумбус")
                      .replace("yoshkar-ola", "columbus"))
        got = X.parse(swapped, today=TODAY)
        assert got.current.temp_c is not None          # it parses fine
        assert X.check_identity(got.ident, expect_slug="yoshkar-ola") is not None

    def test_identity_survives_a_missing_flight_stream(self, raw):
        """If the RSC payload disappears entirely, identity falls back to the
        <h1>. Losing the JSON must not mean losing the safety check."""
        stripped = re.sub(r"self\.__next_f\.push\(.*?\)</script>", "</script>",
                          raw, flags=re.S)
        doc_ident = X.identity(stripped, __import__("lxml.html", fromlist=["x"])
                               .fromstring(stripped), "")
        assert doc_ident.h1 and "Йошкар-Ол" in doc_ident.h1


class TestUnitAndRangeDefences:
    """Layer 1 and 2: the number is impossible, and here is why."""

    def test_pressure_in_the_temperature_field_is_dropped_not_clamped(self):
        rep = V.Report()
        cur = Current(temp_c=743.0)
        V.validate_current(cur, rep)
        assert cur.temp_c is None, "clamping 743 to +55 is worse than a blank"
        assert "pressure" in rep.warnings[0]

    def test_hpa_in_the_mmhg_field(self):
        rep = V.Report()
        cur = Current(pressure_mmhg=1013.0)
        V.validate_current(cur, rep)
        assert cur.pressure_mmhg is None
        assert "hPa" in rep.warnings[0]

    def test_humidity_as_a_fraction(self):
        """The interesting one: 0.81 passes the 0-100 bounds cleanly. Only the
        unit signature notices it is a fraction."""
        rep = V.Report()
        cur = Current(humidity_pct=0.81)
        V.validate_current(cur, rep)
        assert cur.humidity_pct is None
        assert "fraction" in rep.warnings[0]

    def test_wind_bearing_mistaken_for_wind_speed(self):
        rep = V.Report()
        cur = Current(wind_ms=270.0)
        V.validate_current(cur, rep)
        assert cur.wind_ms is None

    def test_oymyakon_still_clears_the_bounds(self):
        """Contracts must be generous enough that real weather never trips
        them. The coldest inhabited place on earth is the test case."""
        rep = V.Report()
        cur = Current(temp_c=-67.7)
        V.validate_current(cur, rep)
        assert cur.temp_c == -67.7
        assert rep.ok

    def test_one_bad_field_does_not_take_the_others_with_it(self):
        rep = V.Report()
        cur = Current(temp_c=16.0, pressure_mmhg=1013.0, humidity_pct=90.0)
        V.validate_current(cur, rep)
        assert (cur.temp_c, cur.humidity_pct) == (16.0, 90.0)
        assert cur.pressure_mmhg is None
        assert rep.dropped == ["pressure_mmhg"]


class TestSeriesDefences:
    """Layer 3: the numbers are individually fine and collectively impossible."""

    def test_degenerate_hourly_is_rejected(self):
        """24 identical values means a selector matched one node and the loop
        read it 24 times. Real days are never perfectly flat."""
        rep = V.Report()
        hours = [Hour(time=f"{h:02d}:00", temp_c=16.0) for h in range(24)]
        assert V.check_series(hours, rep) == []
        assert "degeneracy" in rep.warnings[0]

    def test_discontinuity_is_flagged(self):
        rep = V.Report()
        hours = [Hour(time="01:00", temp_c=16.0), Hour(time="02:00", temp_c=16.5),
                 Hour(time="03:00", temp_c=78.0), Hour(time="04:00", temp_c=17.0),
                 Hour(time="05:00", temp_c=17.2), Hour(time="06:00", temp_c=17.4)]
        V.check_series(hours, rep)
        assert any("discontinuity" in w for w in rep.warnings)

    def test_a_real_day_passes(self, request):
        rep = V.Report()
        raw = (request.path.parent / "fixtures" / "current.html").read_text(
            encoding="utf-8", errors="replace")
        got = X.parse(raw, today=TODAY)
        assert V.check_series(got.hourly, rep) == got.hourly
        assert rep.ok


class TestContinuity:
    """Layer 5: catches the parser that broke *between* two fetches, where
    every other check sees a self-consistent page."""

    def test_a_normal_change_is_fine(self):
        rep = V.Report()
        assert not V.check_continuity(16.0, 14.0, gap_s=600, rep=rep)
        assert rep.ok

    def test_an_impossible_jump_is_flagged(self):
        rep = V.Report()
        assert V.check_continuity(81.0, 16.0, gap_s=600, rep=rep)
        assert "suspect the parser" in rep.warnings[0]

    def test_a_long_outage_never_trips_it(self):
        """The allowance grows with the gap, so coming back after two days of
        downtime in a different season is not an alarm."""
        rep = V.Report()
        assert not V.check_continuity(-5.0, 16.0, gap_s=48 * 3600, rep=rep)


class TestDayValidation:
    def test_a_corrupt_part_does_not_drop_the_day(self):
        rep = V.Report()
        day = Day(date="2026-07-31", temp_min_c=14.0, temp_max_c=20.0, parts=[
            DayPart(name="утро", temp_c=19.0, humidity_pct=76.0),
            DayPart(name="день", temp_c=20.0, humidity_pct=0.62),   # a fraction
        ])
        out = V.validate_days([day], rep)
        assert len(out) == 1
        assert out[0].parts[1].temp_c == 20.0
        assert out[0].parts[1].humidity_pct is None

    def test_short_forecast_is_called_out(self):
        rep = V.Report()
        V.validate_days([Day(date="2026-07-31", temp_max_c=20.0)], rep)
        assert any("survived validation" in w for w in rep.warnings)
