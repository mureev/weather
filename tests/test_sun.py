"""Is the sun up, and does the icon agree?

The bug: at 01:25 the app drew a blazing midday sun. Gismeteo's tooltips say
«Безоблачно» and nothing else -- no day, no night -- and Open-Meteo's WMO codes
have no concept of it at all, so two of the three sources shipped a daytime
icon around the clock. Only Yandex knew, and only because its icon codes carry
a `_d`/`_n` suffix.

The fix is arithmetic, applied centrally on serve. Which means it can be tested
properly rather than eyeballed: solar position is a published quantity, so
these assertions are against **Gismeteo's own printed sunrise and sunset for
the very page the bug appeared on** -- 03:48 and 19:59, Yoshkar-Ola, 1 August
2026. Agreeing with the source to the minute is a stronger claim than "looks
dark to me", and it is the reason a fixed evening window was not good enough:
the same window is wrong by two and a half hours in December.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app import sun

MSK = ZoneInfo("Europe/Moscow")
YO = (56.6375, 47.8908)                 # Yoshkar-Ola
MURMANSK = (68.97, 33.08)               # far enough north to have no sunrise


def msk(y, m, d, hh, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=MSK)


class TestAgainstPublishedTimes:
    """The numbers on the page the bug was reported from."""

    def test_sunrise_matches_gismeteo_to_the_minute(self):
        got = sun.sunrise(*YO, dt.date(2026, 8, 1)).astimezone(MSK)
        assert got.strftime("%H:%M") == "03:48"

    def test_sunset_matches_gismeteo_to_the_minute(self):
        got = sun.sunset(*YO, dt.date(2026, 8, 1)).astimezone(MSK)
        assert got.strftime("%H:%M") == "19:59"

    def test_daylight_length_matches(self):
        """Gismeteo prints «Долгота дня: 16 ч 11 мин»."""
        d = dt.date(2026, 8, 1)
        span = sun.sunset(*YO, d) - sun.sunrise(*YO, d)
        assert abs(span - dt.timedelta(hours=16, minutes=11)) < dt.timedelta(minutes=2)


class TestTheReportedCase:
    def test_half_past_one_in_august_is_night(self):
        """The screenshot. −12.9° below the horizon, and we drew a sun."""
        assert sun.is_night(*YO, msk(2026, 8, 1, 1, 25))

    def test_and_noon_is_not(self):
        assert not sun.is_night(*YO, msk(2026, 8, 1, 12))


class TestWhyNotAFixedWindow:
    """`hour >= 21 or hour < 5` -- the code this replaced. Each of these is a
    case where it gives the wrong answer, and none of them is exotic."""

    @pytest.mark.parametrize("hh,dark", [(4, False), (20, True)])
    def test_summer_edges(self, hh, dark):
        """Sunrise 03:48 and sunset 19:59 both sit *inside* the old window."""
        assert sun.is_night(*YO, msk(2026, 8, 1, hh, 30)) is dark

    @pytest.mark.parametrize("hh,dark", [(7, True), (8, True), (17, True)])
    def test_december_mornings_and_afternoons(self, hh, dark):
        """Sunrise is after 08:30 and sunset before 16:00, so the old window
        called two and a half hours of darkness "day" at each end."""
        assert sun.is_night(*YO, msk(2026, 12, 15, hh)) is dark

    def test_polar_night_has_no_sunrise_at_all(self):
        assert sun.sunrise(*MURMANSK, dt.date(2026, 12, 21)) is None
        assert sun.is_night(*MURMANSK, msk(2026, 12, 21, 12))

    def test_polar_day_has_no_sunset_at_all(self):
        assert sun.sunset(*MURMANSK, dt.date(2026, 6, 21)) is None
        assert not sun.is_night(*MURMANSK, msk(2026, 6, 21, 0, 30))

    def test_longitude_matters_not_just_the_hour(self):
        """Two places on the same clock, 40° of longitude apart. Whatever the
        rule is, it cannot be a function of local time alone."""
        kaliningrad = (54.71, 20.51)
        when = dt.datetime(2026, 12, 15, 8, 30, tzinfo=dt.timezone(dt.timedelta(hours=3)))
        assert sun.is_night(*YO, when) != sun.is_night(*kaliningrad, when)


class TestNightify:
    def test_it_adds_the_night_form(self):
        assert sun.nightify("clear", True) == "clear-night"
        assert sun.nightify("partly", True) == "partly-night"

    def test_it_also_removes_one(self):
        """Bidirectional on purpose: it runs over whatever the parser produced,
        so it has to correct a wrong guess, not only fill in a missing one."""
        assert sun.nightify("clear-night", False) == "clear"

    def test_it_is_idempotent(self):
        """It runs on every serve, including on a cached payload it has already
        been through."""
        once = sun.nightify("clear", True)
        assert sun.nightify(once, True) == once

    @pytest.mark.parametrize("icon", ["rain", "overcast", "fog", "snow", "thunder"])
    def test_conditions_with_no_night_form_are_untouched(self, icon):
        """Rain looks like rain at midnight. A `rain-night` icon would mean
        drawing a moon nobody could see."""
        assert sun.nightify(icon, True) == icon

    def test_it_survives_a_missing_icon(self):
        assert sun.nightify(None, True) is None


class TestHourTimes:
    def test_a_series_that_crosses_midnight_rolls_the_date(self):
        """The one thing a bare "HH:MM" cannot tell you, and it happens once
        per series."""
        now = msk(2026, 8, 1, 22, 10)
        got = sun.hour_times(["22:00", "23:00", "00:00", "01:00"],
                             "Europe/Moscow", now)
        assert [t.day for t in got] == [1, 1, 2, 2]

    def test_iso_stamps_pass_through(self):
        got = sun.hour_times(["2026-08-01T15:00"], "Europe/Moscow",
                             msk(2026, 8, 1, 15))
        assert got[0].hour == 15 and got[0].tzinfo is not None

    def test_a_series_starting_before_now_belongs_to_tomorrow(self):
        """Fetched at 23:50, a run beginning 00:00 is not fourteen hours ago."""
        now = msk(2026, 8, 1, 23, 50)
        got = sun.hour_times(["00:00", "01:00"], "Europe/Moscow", now)
        assert [t.day for t in got] == [2, 2]

    def test_junk_becomes_none_rather_than_an_exception(self):
        got = sun.hour_times(["nonsense", "12:00"], "Europe/Moscow",
                             msk(2026, 8, 1, 12))
        assert got[0] is None and got[1] is not None


class TestAppliedToAPayload:
    def test_every_source_gets_the_same_treatment(self, monkeypatch):
        """The actual defect: two of three sources had no day/night at all, so
        fixing it inside one parser would have left the other two sunny at
        midnight."""
        from app import cities, service
        from app.models import Current, Hour, SourceView, Weather

        weather = Weather(place=cities.get("yoshkar-ola"),
                          fetched_at="2026-08-01T01:25:00+03:00")
        for key in ("yandex", "gismeteo", "openmeteo"):
            weather.sources[key] = SourceView(
                key=key, label=key, available=True,
                current=Current(temp_c=14.0, icon="clear"),
                hourly=[Hour(time="01:00", temp_c=14.0, icon="clear"),
                        Hour(time="12:00", temp_c=23.0, icon="clear")])

        monkeypatch.setattr(service, "local_now", lambda tz: msk(2026, 8, 1, 1, 25))
        service._sunlit(weather)

        for key, sv in weather.sources.items():
            assert sv.current.icon == "clear-night", key
            assert sv.hourly[0].icon == "clear-night", key
            assert sv.hourly[1].icon == "clear", f"{key}: noon is not night"

    @pytest.mark.parametrize("date", ["2026-03-21", "2026-06-21",
                                      "2026-08-04", "2026-12-04"])
    def test_a_part_of_the_day_is_dark_exactly_when_the_sun_is_down(self, date):
        """The «ночь» row on the day screen drew a sun behind a cloud, because
        `nightify` reached the current reading and the hourly strip and nothing
        else. Found by looking at the screen, not by a test.

        Checked against this module's own sunrise and sunset rather than
        against a table of expected icons -- those two are themselves validated
        against Gismeteo's published times above, so the chain ends somewhere
        outside our own arithmetic.
        """
        import datetime as dt

        from app import cities, service
        from app.models import Day, DayPart

        place = cities.get("yoshkar-ola")
        day = Day(date=date, parts=[DayPart(name=n, temp_c=5.0, icon="clear")
                                    for n in ("утро", "день", "вечер", "ночь")])
        service._sunlit_parts(day, place)

        # Compared as local *times of day*, which is both how a person reads a
        # sunrise and how the sources publish one. `sun.sunrise` scans a UTC
        # day by contract, and at MSK in midsummer the sunrise inside UTC-21
        # June is 23:56Z -- local 02:56 on the 22nd. The clock time is right
        # either way; only the calendar date shifts, so the date is what this
        # comparison leaves out.
        on = dt.date.fromisoformat(date)
        here = sun.zone(place.tz)
        up = sun.sunrise(place.lat, place.lon, on).astimezone(here).time()
        down = sun.sunset(place.lat, place.lon, on).astimezone(here).time()
        for part in day.parts:
            centre = dt.time(service._PART_HOUR[part.name])
            daylight = up <= centre <= down
            assert (part.icon == "clear") == daylight, (
                f"{date} {part.name}: icon {part.icon} but the sun is "
                f"{'up' if daylight else 'down'} "
                f"(rise {up:%H:%M}, set {down:%H:%M}, part at {centre:%H:%M})")

    def test_a_white_night_is_not_drawn_as_a_dark_one(self):
        """Yoshkar-Ola is at 56.6°N: on the solstice the sun is up before three
        in the morning, so even «ночь» gets a daylight icon. A rule keyed on
        the word rather than on the sky would never produce that."""
        import datetime as dt

        from app import cities, service
        from app.models import Day, DayPart

        day = Day(date="2026-06-21",
                  parts=[DayPart(name="ночь", temp_c=11.0, icon="clear")])
        service._sunlit_parts(day, cities.get("yoshkar-ola"))
        assert day.parts[0].icon == "clear"
        assert dt.date.fromisoformat("2026-06-21").month == 6   # solstice, not a typo
