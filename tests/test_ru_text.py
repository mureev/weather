"""The two traps that are invisible in July, plus the shape classifier."""

import pytest

from app import ru_text as R


class TestMinusSign:
    """Yandex renders minus as U+2212, not ASCII hyphen.

    Miss this and every winter temperature comes out positive -- a bug you
    cannot possibly notice while testing in July, which is when this project
    was built. Hence a test rather than a comment.
    """

    @pytest.mark.parametrize("dash", ["−", "–", "—", "‐", "-"])
    def test_all_dash_characters_are_minus(self, dash):
        assert R.temperature(f"{dash}12°") == -12.0

    def test_ascii_hyphen_still_works(self):
        assert R.temperature("-7°") == -7.0

    def test_plus_is_positive(self):
        assert R.temperature("+22°") == 22.0

    def test_bare_zero(self):
        assert R.temperature("0°") == 0.0

    def test_minus_in_a11y_prose(self):
        line = "ночью −18°, ясно, скорость ветра 1,7 м/с"
        assert R.temperature(line) == -18.0


class TestNumberGuard:
    """`(\\d{1,2})\\s*°` matches "743°" as +43.

    A pressure reading silently becomes a plausible two-digit temperature: in
    range, smooth against its neighbours, and invisible to every downstream
    bounds check. The `(?<![\\d.,])` guard is the fix.
    """

    def test_pressure_is_not_read_as_temperature(self):
        assert R.temperature("743°") is None

    def test_four_digits_too(self):
        assert R.temperature("1013°") is None

    def test_decimal_tail_is_not_a_temperature(self):
        assert R.temperature("2,9°") == 2.9
        assert R.temperature("12,5°") == 12.5

    def test_real_temperature_after_a_number(self):
        # "745" is pressure, "+16°" is the temperature. Only one should match.
        assert R.temperature("745 +16°") == 16.0

    def test_humidity_guard(self):
        assert R.humidity_pct("1076%") is None
        assert R.humidity_pct("76%") == 76.0


class TestRussianNumbers:
    def test_comma_decimal(self):
        assert R.to_float("2,9") == 2.9

    def test_wind_with_comma_decimal(self):
        assert R.wind_ms("скорость ветра 1,7 м/с") == 1.7

    def test_pressure(self):
        assert R.pressure_mmhg("давление 744 мм рт. ст.") == 744.0

    def test_hpa_is_converted_not_dropped(self):
        assert R.pressure_mmhg("1013 гПа") == pytest.approx(759.8, abs=0.2)

    def test_nbsp_and_narrow_nbsp(self):
        assert R.clean("31 июля г.") == "31 июля г."


class TestClassify:
    """Content-shaped parsing: what a cell *is*, not where it sits.

    `/details` shuffles nothing today, but the day it does, a positional parser
    reads 78% as a temperature and this one does not.
    """

    @pytest.mark.parametrize("cell,expect", [
        ("744", None),                      # bare number: genuinely ambiguous
        ("744 мм рт. ст.", "pressure_mmhg"),
        ("2,9 м/с", "wind_ms"),
        ("78%", "humidity_pct"),
        ("+19°", "temp_c"),
        ("−19°", "temp_c"),
    ])
    def test_classification(self, cell, expect):
        got = R.classify(cell)
        assert (got[0] if got else None) == expect

    def test_order_is_shuffle_proof(self):
        cells = ["78%", "+19°", "744 мм рт. ст.", "2,9 м/с"]
        found = {R.classify(c)[0]: R.classify(c)[1] for c in cells}
        assert found == {"humidity_pct": 78.0, "temp_c": 19.0,
                         "pressure_mmhg": 744.0, "wind_ms": 2.9}
        # Same values, opposite order, same answer.
        found2 = {R.classify(c)[0]: R.classify(c)[1] for c in reversed(cells)}
        assert found == found2


class TestConditions:
    def test_longest_match_wins(self):
        assert R.condition("облачно с прояснениями") == "облачно с прояснениями"

    def test_substring_does_not_truncate(self):
        assert R.condition("Малооблачно") == "Малооблачно"

    def test_unknown_condition_is_none_not_a_crash(self):
        assert R.condition("розовый туманчик высокой интенсивности") == "туман"


class TestIcons:
    @pytest.mark.parametrize("cond,key", [
        ("Ясно", "clear"), ("Малооблачно", "partly"),
        ("Облачно с прояснениями", "cloudy"), ("Пасмурно", "overcast"),
        ("Небольшой дождь", "rain-light"), ("Сильный дождь", "rain-heavy"),
        ("Гроза", "thunder"), ("Снег", "snow"),
    ])
    def test_condition_to_icon(self, cond, key):
        assert R.icon_key(cond) == key

    def test_night_variants(self):
        assert R.icon_key("Ясно", night=True) == "clear-night"
        # Rain looks the same at night; only sky icons get a night variant.
        assert R.icon_key("Дождь", night=True) == "rain"

    def test_yandex_icon_codes(self):
        assert R.icon_from_yandex("skc_n") == "clear-night"
        assert R.icon_from_yandex("bkn_d") == "partly"
        assert R.icon_from_yandex("ovc_ra") == "rain"


class TestCaptcha:
    def test_detects_block_page(self):
        assert R.looks_like_captcha(
            "<html>Подтвердите, что запросы отправляли вы</html>")

    def test_normal_page_is_not_a_captcha(self):
        assert not R.looks_like_captcha("<html>Погода в Йошкар-Оле +16°</html>")
