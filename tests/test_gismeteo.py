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
from itertools import pairwise

import pytest

from app import cities
from app.models import ParseError, Tier
from app.sources import gismeteo as G

TODAY = dt.date(2026, 7, 31)


@pytest.fixture(scope="module")
def parsed(request):
    d = request.path.parent / "fixtures"
    return G.parse(
        (d / "gm-current.html").read_text(encoding="utf-8", errors="replace"),
        days_html=(d / "gm-10days.html").read_text(encoding="utf-8",
                                                   errors="replace"),
        today=TODAY,
    )


class TestAddressing:
    def test_built_in_cities_have_ids(self):
        for slug in ("yoshkar-ola", "cheboksary", "kazan",
                     "nizhny-novgorod", "moscow", "saint-petersburg"):
            assert G.city_id(cities.get(slug)) is not None

    def test_urls_use_the_clean_path_form(self):
        now, hourly, days = G.urls_for(cities.get("yoshkar-ola"))
        assert now == "https://www.gismeteo.ru/weather-yoshkar-ola-11975/"
        assert hourly.endswith("/hourly/")
        assert days.endswith("/10-days/")
        # robots.txt disallows /*?* -- every URL with a query string.
        assert not any("?" in u for u in (now, hourly, days))

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
        position is the fallback, anchored on today."""
        assert parsed.daily[3].title == "пн 3"
        assert parsed.daily[3].date == "2026-08-03"

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


class TestIndependence:
    def test_it_actually_disagrees_with_yandex(self, parsed, request):
        """The whole point of a second source. Same city, same minute, from a
        different model: 15° against Yandex's 16°, 748 mmHg against 745, 100%
        humidity against 90%.

        If these ever match exactly, suspect that one parser is reading the
        other's page.
        """
        from app import extract as X
        ya = X.parse((request.path.parent / "fixtures" / "current.html")
                     .read_text(encoding="utf-8", errors="replace"), today=TODAY)
        assert parsed.current.temp_c != ya.current.temp_c
        assert abs(parsed.current.temp_c - ya.current.temp_c) < 3.0


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
    def mirror(self, request):
        d = request.path.parent / "fixtures"
        cur = d / "mf-current.html"
        if not cur.exists():
            pytest.skip("no mirror fixture -- capture one with `make fixtures-gm`")
        read = lambda f: (f.read_text(encoding="utf-8", errors="replace")  # noqa: E731
                          if f.exists() else None)
        return G.parse(read(cur),
                       days_html=read(d / "mf-10days.html"),
                       hourly_html=read(d / "mf-hourly.html"))

    def test_the_hourly_page_begins_at_the_next_whole_hour(self, request, mirror):
        """Recorded because the app now depends on it.

        Gismeteo's `/hourly/` page does not include the hour you are standing
        in -- the observation at 12:00 is followed by a strip starting 13:00,
        because their own page shows current conditions in a separate card
        above it. That is why `series.align_to_now` puts the observation at the
        head of the series; without it the strip simply had no column for now.

        If this ever stops being true, `align_to_now` will find a covering
        entry and leave the series alone, so the behaviour degrades correctly
        -- but the reason for the code will have evaporated, and that is worth
        knowing.
        """
        if not (request.path.parent / "fixtures" / "mf-hourly.html").exists():
            pytest.skip("no hourly fixture")
        first = mirror.hourly[0]
        assert first.at is not None and mirror.current.observed_epoch is not None
        gap = first.at - mirror.current.observed_epoch
        assert 0 < gap <= 3600, (
            f"the hourly page starts {gap}s after the observation; it used to "
            f"start at the next whole hour")

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

    def test_the_state_blob_is_there_too(self, mirror):
        """Tier 1. If the mirror only yielded tier 3, it would still work and
        the parser would be one redesign from reading the wrong cell -- so it
        is worth knowing which is true before relying on it."""
        # Per *field*, because that is how provenance is keyed -- there is no
        # "current" entry and asserting one passed vacuously as `None != 1`
        # until a real fixture existed to run it against.
        for field in ("temp_c", "humidity_pct", "pressure_mmhg", "wind_ms"):
            assert mirror.provenance.get(field) == int(Tier.NAMED), field
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
