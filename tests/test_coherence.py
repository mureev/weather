"""Fields that are each perfect and jointly nonsense.

The four validation layers this file joins are all *vertical*: they look at one
value, or at one series, and ask whether it could be real. Between them they
catch a temperature that is impossible, one that is secretly a pressure, a
series that repeats twenty-four times, and a reading that jumped twenty degrees
since the last fetch.

Not one of them could catch what actually shipped: a headline reading
«Малооблачно, туман» beside an hourly column for the same instant reading
«Безоблачно», because the headline was describing midnight and the column was
describing now. Every number was in range, in the right unit, in a well-formed
series, and continuous. They were individually correct and collectively a lie,
and the only place that shows is when two of them are held up against each
other.

That is what this layer does, and it is worth naming the general shape, because
this is the second time the same shape has bitten (the first was the wrong-city
page, `DECISIONS.md` §2): **the dangerous failures here are never a bad value.
They are a right value describing the wrong thing** -- the wrong city, the
wrong hour, the wrong cell. No amount of bounds-checking sees any of them.
Cross-checking two fields that must describe the same moment does.

It warns rather than dropping. A disagreement is evidence about the parser, not
about the sky, and this codebase does not overrule an upstream quietly.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.models import Current, Day, Hour
from app.validation import Report, check_coherence

TZ = "Europe/Moscow"
MSK = dt.timezone(dt.timedelta(hours=3))


def at(hour: int) -> int:
    return int(dt.datetime(2026, 7, 31, hour, tzinfo=MSK).timestamp())


def series(overrides: dict | None = None) -> list[Hour]:
    base = {h: (15.0 + h * 0.5, "clear") for h in range(0, 24, 3)}
    base.update(overrides or {})
    return [Hour(time=f"{h:02d}:00", temp_c=t, icon=i, condition=i)
            for h, (t, i) in sorted(base.items())]


class TestTheBugThatMotivatedIt:
    def test_a_headline_describing_a_different_hour_is_reported(self):
        """The shipped failure, in miniature: the reading was taken at 23:00
        and the condition came from the 00:00 column."""
        rep = Report()
        check_coherence(
            Current(temp_c=26.0, icon="fog", observed_epoch=at(23)),
            series(), [], rep, TZ)
        assert any("disagrees" in w for w in rep.warnings)

    def test_agreement_is_silent(self):
        rep = Report()
        check_coherence(
            Current(temp_c=26.5, icon="clear", observed_epoch=at(21)),
            series(), [], rep, TZ)
        assert rep.warnings == []

    def test_nothing_is_dropped_over_a_disagreement(self):
        """Two fields disagreeing says something about our parser, not about
        the weather. The app keeps serving and says so on the health page --
        the same reasoning as `DECISIONS.md` §4."""
        rep = Report()
        check_coherence(
            Current(temp_c=26.0, icon="rain", observed_epoch=at(23)),
            series(), [], rep, TZ)
        assert rep.warnings and rep.dropped == []


class TestTemperatureAgreement:
    def test_a_wildly_different_headline_temperature_is_reported(self):
        rep = Report()
        check_coherence(Current(temp_c=2.0, observed_epoch=at(12)), series(), [], rep, TZ)
        assert any("disagrees" in w for w in rep.warnings)

    def test_ordinary_rounding_is_not(self):
        """The headline is an observation and the column is a forecast for the
        hour; a couple of degrees between them is the normal state of affairs,
        and a check that fires on it would be turned off within a week."""
        rep = Report()
        check_coherence(Current(temp_c=22.0, observed_epoch=at(12)), series(), [], rep, TZ)
        assert rep.warnings == []


class TestIconFamilies:
    @pytest.mark.parametrize("current,column", [
        ("rain", "rain-light"),      # a disagreement about degree
        ("clear", "clear-night"),    # the same sky, after dark
        ("cloudy", "partly"),        # two words for one thing
    ])
    def test_near_relatives_do_not_trip_it(self, current, column):
        rep = Report()
        check_coherence(Current(temp_c=21.0, icon=current, observed_epoch=at(12)),
                        series({12: (21.0, column)}), [], rep, TZ)
        assert rep.warnings == []

    @pytest.mark.parametrize("current,column", [
        ("clear", "rain"),
        ("snow", "clear"),
        ("thunder", "overcast"),
    ])
    def test_genuinely_different_weather_does(self, current, column):
        rep = Report()
        check_coherence(Current(temp_c=21.0, icon=current, observed_epoch=at(12)),
                        series({12: (21.0, column)}), [], rep, TZ)
        assert any("condition" in w for w in rep.warnings)


class TestAgainstTodaysOwnRange:
    def test_a_headline_outside_todays_min_max_is_reported(self):
        """Both numbers come off the same page. If the current reading sits
        outside the range that page publishes for the same day, one of the two
        is being read out of the wrong cell."""
        rep = Report()
        today = Day(date="2026-07-31", temp_min_c=13.0, temp_max_c=21.0)
        check_coherence(Current(temp_c=34.0, observed_epoch=at(12)),
                        series(), [today], rep, TZ)
        assert any("outside today's own range" in w for w in rep.warnings)

    def test_the_edges_of_the_day_get_slack(self):
        """A daily min/max is a forecast and the current reading is an
        observation. They are allowed to part company a little."""
        rep = Report()
        today = Day(date="2026-07-31", temp_min_c=13.0, temp_max_c=21.0)
        check_coherence(Current(temp_c=23.5, observed_epoch=at(12)),
                        series(), [today], rep, TZ)
        assert rep.warnings == []


class TestItDeclinesToGuess:
    def test_without_an_observation_time_it_stays_quiet(self):
        """Silence is the honest answer. Comparing the headline to whichever
        column happens to be first is the exact bug this exists to catch, and
        doing it *inside the check* would make the check certify it."""
        rep = Report()
        check_coherence(Current(temp_c=2.0, icon="rain"), series(), [], rep, TZ)
        assert rep.warnings == []

    def test_without_an_hourly_series_it_stays_quiet(self):
        rep = Report()
        check_coherence(Current(temp_c=21.0, observed_epoch=at(12)), [], [], rep, TZ)
        assert rep.warnings == []

    def test_it_survives_an_hourly_series_with_junk_labels(self):
        rep = Report()
        check_coherence(Current(temp_c=21.0, observed_epoch=at(12)),
                        [Hour(time="", temp_c=21.0),
                         Hour(time="not a time", temp_c=21.0)], [], rep, TZ)
        assert rep.warnings == []

    def test_it_understands_open_meteos_iso_labels(self):
        """Open-Meteo ships a full ISO stamp where the scrapers ship "21:00".
        A check that only understood one of them would silently never run for
        the other -- which is the failure mode of every "it passed" check."""
        rep = Report()
        hours = [Hour(time=f"2026-07-31T{h:02d}:00", temp_c=15.0, icon="clear")
                 for h in range(24)]
        check_coherence(Current(temp_c=2.0, icon="rain", observed_epoch=at(12)),
                        hours, [], rep, TZ)
        assert any("disagrees" in w for w in rep.warnings)
