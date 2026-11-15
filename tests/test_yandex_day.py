"""Yandex's per-day page, against real captured HTML.

The page is `…/details/auto/10-day-weather/day-5`, and the fixture is the one
that page returned — which describes a day five days after the capture (first
recorded 2 August 2026 and describing 7 August; re-recorded 15 November,
describing the 20th). That gap is the whole reason the parser checks the date
instead of trusting the URL, and it is why the fixture is worth keeping exactly
as recorded rather than tidied to "today".

Every expectation here is read off the page by a plain regex over its text,
never typed in: a typed value is a test of one day's weather (§45).
"""

import datetime as dt
import pathlib
import re
from itertools import pairwise

import pytest

from app import cities
from app.models import ParseError
from app.sources import yandex_day as YD

RAW = (pathlib.Path(__file__).resolve().parent / "fixtures" / "ya-day5.html"
       ).read_text(encoding="utf-8", errors="replace")

# What the recorded page is actually about, not when it was fetched: its first
# column's own stamp.
PAGE_DAY = dt.date.fromisoformat(
    re.search(r'dateTime="(\d{4}-\d\d-\d\d)T', RAW).group(1))


def _num(s: str) -> float:
    return float(s.replace(",", ".").replace("−", "-"))


# The first column, in the page's screen-reader prose: «: +4°, небольшой дождь,
# Ощущается как -1.» and «, 5,3 Метров в секунду, до 11 Метров в секунду,
# южный.» -- the parser's sentences, read by a different route.
_TEMP = re.search(r":\s*([+−-]?\d+)°,\s*([^,<]+),\s*Ощущается как\s*([−-]?\d+)", RAW)
_WIND = re.search(r",\s*(\d+(?:,\d+)?) Метров в секунду,(?:\s*до (\d+(?:,\d+)?) "
                  r"Метров в секунду,)?\s*([а-я-]+)\.", RAW)


def _card(label: str) -> str:
    """A value from the astronomy card: «Восход» then its value span."""
    m = re.search(rf">{label}</span>.*?__value[^>]*>([^<]+)<", RAW, re.S)
    assert m, f"the page no longer labels {label!r}"
    return m.group(1)


@pytest.fixture(scope="module")
def raw(request) -> str:
    return (request.path.parent / "fixtures" / "ya-day5.html").read_text(
        encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def day(raw):
    return YD.parse(raw, want=PAGE_DAY)


class TestAddressing:
    def test_the_url_is_built_from_an_offset(self):
        url = YD.url_for(cities.get("yoshkar-ola"), 5)
        assert url.endswith("/pogoda/ru/yoshkar-ola"
                            "/details/auto/10-day-weather/day-5")
        assert "?" not in url

    def test_a_gps_fix_has_no_per_day_page(self):
        """`/pogoda/?lat=&lon=` has no per-day equivalent. Saying so is better
        than inventing a slug: the day screen already has four parts of day
        from the main payload and simply stays as it is."""
        assert YD.url_for(cities.ad_hoc(56.63, 47.90), 3) is None

    @pytest.mark.parametrize("offset", [-1, 10, 400])
    def test_a_day_outside_the_ten_is_refused_without_a_request(self, offset):
        assert YD.url_for(cities.get("yoshkar-ola"), offset) is None


class TestItChecksWhichDayItGot:
    """`day-5` is a *position*, and this codebase has an invariant about
    trusting positions. The offset is computed from the date, and then the
    page's own stated date is held against the date that was asked for."""

    def test_the_right_day_is_accepted(self, day):
        assert day.date == PAGE_DAY.isoformat()

    def test_a_page_about_another_day_is_rejected(self, raw):
        with pytest.raises(ParseError) as e:
            YD.parse(raw, want=PAGE_DAY - dt.timedelta(days=1))
        assert "describes" in str(e.value)

    def test_a_page_with_no_timestamps_is_rejected(self):
        with pytest.raises(ParseError):
            YD.parse("<html><body><p>Погода</p></body></html>", want=PAGE_DAY)

    def test_a_captcha_is_rejected_as_such(self):
        with pytest.raises(ParseError) as e:
            YD.parse("<html><body>Подтвердите, что запросы отправляли вы, "
                     "а не робот</body></html>", want=PAGE_DAY)
        assert "captcha" in str(e.value)


class TestTheColumns:
    def test_eight_of_them_three_hours_apart(self, day):
        assert len(day.hours) == 8
        stamps = [h.at for h in day.hours]
        assert all(b - a == 3 * 3600 for a, b in pairwise(stamps))

    def test_the_block_is_not_read_twice(self, day):
        """It renders twice — wide and narrow layouts — which is the same trap
        that once turned a ten-day forecast into twenty days."""
        assert len({h.at for h in day.hours}) == 8

    def test_every_column_carries_what_the_page_shows(self, day):
        for h in day.hours:
            assert h.temp_c is not None
            assert h.feels_like_c is not None
            assert h.condition and h.icon
            assert h.wind_ms is not None and h.wind_dir

    def test_the_values_are_the_ones_on_the_page(self, day):
        first = day.hours[0]
        assert first.time.startswith(f"{PAGE_DAY.isoformat()}T00:00")
        assert _TEMP and _WIND, "the page's prose no longer reads as it did"
        assert (first.temp_c, first.feels_like_c) == (
            _num(_TEMP.group(1)), _num(_TEMP.group(3)))
        assert first.condition.lower() == _TEMP.group(2).strip().lower()
        gust = _num(_WIND.group(2)) if _WIND.group(2) else None
        assert (first.wind_ms, first.wind_gust_ms) == (_num(_WIND.group(1)), gust)
        assert first.wind_dir == _WIND.group(3)

    def test_feels_like_survives_having_no_degree_sign(self, day):
        """«Ощущается как 18.» — a bare number, unlike every other temperature
        Yandex writes. The degree-guarded pattern correctly returns nothing for
        it, so the field read as one the page does not publish."""
        assert all(h.feels_like_c is not None for h in day.hours)

    def test_the_gust_is_not_mistaken_for_the_speed(self, day):
        """«, 2,2 Метров в секунду, до 3 Метров в секунду, юго-западный.» Two
        speeds in one sentence, and the first one is the wind."""
        for h in day.hours:
            assert h.wind_gust_ms is None or h.wind_gust_ms >= h.wind_ms

    def test_the_decimal_comma_is_not_read_as_a_separator(self, day):
        """«1,8 Метров в секунду» is 1.8 m/s, not 1. The main parser has the
        same scar. Any column the page writes with a comma will do."""
        commas = [_num(m) for m in re.findall(
            r"(\d+,\d+) Метров в секунду", RAW)]
        assert commas, "no decimal comma on this page to check"
        assert commas[0] in [h.wind_ms for h in day.hours]

    def test_precipitation_probability_where_the_page_states_one(self, day):
        probs = [h.precip_prob for h in day.hours]
        assert any(p is not None for p in probs)
        assert all(p is None or 0 <= p <= 100 for p in probs)


class TestTheAstronomy:
    def test_read_by_label_not_by_position(self, day):
        assert day.sunrise == _card("Восход")
        assert day.sunset == _card("Закат")
        assert day.daylight == _card("Световой день")
        assert day.sunrise != day.sunset

