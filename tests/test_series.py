"""Where an hourly series starts, and which entry is "now".

Two questions that sound like one, and were treated as one, and are not:

    covering(hours, when)    which entry best *describes* this instant
    align_to_now(hours, …)   which entry the strip should *open on*

`covering` wants the nearest, because it is used to compare two readings of the
same moment. `align_to_now` wants the one that actually contains the moment,
because a strip that opens on a forecast and calls it now is lying. At 11:20
against a series beginning 12:00 the nearest entry is 12:00 -- forty minutes
into the future -- and treating that as "now" is what made the current hour
vanish from the Gismeteo tab.

The three sources each begin somewhere different, and each is sensible on its
own page: Gismeteo's `/hourly/` starts at the next whole hour because the page
shows current conditions in a separate card, Open-Meteo returns the whole
calendar day so a third of it is already past by lunchtime, and Yandex starts
at the current hour. Rendered identically by us, the same strip meant three
different things depending on which tab was open.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.models import Current, Hour
from app.series import align_to_now, covering, label_hour

TZ = "Europe/Moscow"
MSK = dt.timezone(dt.timedelta(hours=3))


def epoch(hour: int, minute: int = 0) -> int:
    return int(dt.datetime(2026, 7, 31, hour, minute, tzinfo=MSK).timestamp())


def hours(spec, *, stamped: bool = True) -> list[Hour]:
    return [Hour(time=f"{h:02d}:00", at=epoch(h) if stamped else None,
                 temp_c=15.0 + h, icon="clear") for h in spec]


NOW = Current(temp_c=21.0, icon="partly", condition="Малооблачно")


class TestCoveringPicksTheNearest:
    def test_it_uses_real_timestamps_when_they_exist(self):
        """The case that started everything: a reading taken at 23:00 against a
        strip running 00:00..21:00. By hour label with a wraparound, 00:00 is
        an hour away and wins. By actual time it is twenty-three hours away and
        21:00 wins, which is the truth."""
        got = covering(hours(range(0, 24, 3)), epoch(23), TZ)
        assert got.time == "21:00"

    def test_it_falls_back_to_labels_when_there_are_none(self):
        got = covering(hours([10, 11, 12], stamped=False), epoch(11, 10), TZ)
        assert got.time == "11:00"

    def test_the_fallback_refuses_to_stretch(self):
        """Two hours away is not "covering". Silence beats a confident wrong
        pairing -- that pairing is the bug this module was extracted for."""
        assert covering(hours([3, 6], stamped=False), epoch(12), TZ) is None

    def test_without_a_timezone_it_will_not_guess_from_labels(self):
        """A bare "11:00" means nothing without a clock to read it against.
        Returning None says so; anything else invents an answer."""
        assert covering(hours([11, 12], stamped=False), epoch(11, 10)) is None

    def test_no_instant_means_no_answer(self):
        assert covering(hours([11, 12]), None, TZ) is None


class TestAlignToNow:
    def test_a_series_starting_in_the_future_gets_the_observation_at_its_head(self):
        """Gismeteo. The strip began at 12:00 while it was 11:20, so the app
        simply had no column for the hour you were standing in.

        The prepended entry is not invented: it is the same observation already
        shown in the hero, at the time it was taken, moved into the series it
        belongs to -- which is what Gismeteo's own page does with its «Сейчас»
        card."""
        got = align_to_now(hours([12, 13, 14]), NOW, epoch(11, 20), TZ)
        assert [h.time for h in got] == ["11:20", "12:00", "13:00", "14:00"]
        assert got[0].temp_c == NOW.temp_c
        assert got[0].icon == NOW.icon
        assert got[0].at == epoch(11, 20)

    def test_a_series_that_starts_this_morning_is_trimmed(self):
        """Open-Meteo returns the calendar day. Half of it has happened."""
        got = align_to_now(hours(range(0, 18)), NOW, epoch(11, 20), TZ)
        assert got[0].time == "11:00"
        assert len(got) == 7

    def test_a_series_already_starting_now_is_left_alone(self):
        before = hours([11, 12, 13])
        got = align_to_now(before, NOW, epoch(11, 20), TZ)
        assert [h.time for h in got] == ["11:00", "12:00", "13:00"]
        assert got[0] is before[0], "it rebuilt an entry it should have kept"

    def test_the_current_hour_counts_as_now_even_late_in_it(self):
        """11:59 is still the eleven o'clock hour. Rounding to the nearest
        would push it into 12:00 and drop the hour you are in."""
        got = align_to_now(hours([11, 12]), NOW, epoch(11, 59), TZ)
        assert got[0].time == "11:00"

    def test_it_declines_without_an_observation_time(self):
        got = align_to_now(hours([12, 13]), NOW, None, TZ)
        assert [h.time for h in got] == ["12:00", "13:00"]

    def test_it_declines_without_a_usable_observation(self):
        """No temperature means nothing worth putting at the head. Trim, and
        leave the head to the source."""
        got = align_to_now(hours([12, 13]), Current(), epoch(11, 20), TZ)
        assert [h.time for h in got] == ["12:00", "13:00"]

    def test_an_empty_series_stays_empty(self):
        assert align_to_now([], NOW, epoch(11), TZ) == []

    def test_a_series_entirely_in_the_past_yields_the_observation(self):
        """Stale upstream data. One honest entry beats four hours of history
        presented as a forecast."""
        got = align_to_now(hours([6, 7, 8]), NOW, epoch(11, 20), TZ)
        assert [h.time for h in got] == ["11:20"]


class TestLabelHour:
    @pytest.mark.parametrize("text,want", [
        ("21:00", 21), ("07:30", 7), ("2026-07-31T14:00", 14),
        ("", None), ("сейчас", None), (None, None),
    ])
    def test_it_reads_both_shapes_and_refuses_junk(self, text, want):
        assert label_hour(text) == want
