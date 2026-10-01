"""What happens when the ground actually moves.

This is the test file for the thing the project is *for*. Everything else
checks that the parsers read today's HTML correctly; these check what happens
on the day they do not, which is the day that matters and the one you cannot
schedule.

The design claim under test is that extraction is a ladder of three
**independent mechanisms**, not three flavours of CSS selector:

    tier 1  NAMED     embedded state JSON      their data contract changes
    tier 2  LABELLED  accessibility prose      their information architecture changes
    tier 3  SHAPE     content-classified DOM   their class names change

Independence is the whole claim. Three selectors against the same markup all
break on the same Tuesday; three mechanisms do not. So each test here removes
one rung from **real captured HTML** and asserts two things:

1. something lower still answers, and
2. it answers with **the same numbers**.

The second assertion is the one that earns its keep. A fallback that produces
*a* forecast is not a fallback, it is a second chance to be confidently wrong --
and this codebase's founding failure mode is a plausible wrong number, not a
missing one. Comparing tiers against each other on the same page is the only
place that can be checked without an oracle.

And when every rung is gone, the requirement inverts: the parser must fail
loudly rather than return a shape full of `None`s that reads downstream as a
working forecast for a very quiet day.
"""

from __future__ import annotations

import re

import pytest
from lxml import html as LH

from app import extract as X
from app.models import ParseError, Tier

FLIGHT = re.compile(r"self\.__next_f\.push\(\[1,.*?\]\)", re.S)
A11Y = re.compile(r'class="([^"]*\bvisuallyHidden\b[^"]*)"')


def without_flight(html: str) -> str:
    """Tier 1 gone: they moved off Next.js, or renamed their state object."""
    return FLIGHT.sub("", html)


def without_a11y(html: str) -> str:
    """Tier 2 gone: the screen-reader text is dropped, or its class is renamed
    in a build -- which is exactly what a CSS-modules hash rotation looks
    like."""
    return A11Y.sub('class="gone"', html)


@pytest.fixture(scope="module")
def full(current_html):
    return X.parse(current_html, today=None)


class TestTierOneRemoved:
    """The RSC flight stream disappears. This is not hypothetical: it is one
    framework upgrade away, and it is the rung carrying `fact`, the object
    whose keys mirror the official API."""

    @pytest.fixture(scope="class")
    @classmethod
    def degraded(cls, current_html):
        return X.parse(without_flight(current_html))

    def test_it_still_produces_a_forecast(self, degraded):
        assert degraded.current is not None
        assert degraded.current.temp_c is not None

    def test_it_admits_it_dropped_a_rung(self, degraded, full):
        """The number being right is not enough. If nothing recorded that the
        mechanism changed, the next redesign lands on a parser already one edit
        from reading the wrong cell, with nothing on the health page to say
        so."""
        assert full.provenance["temp_c"] == int(Tier.NAMED)
        assert degraded.provenance["temp_c"] > int(Tier.NAMED)

    def test_the_lower_rung_agrees_with_the_higher_one(self, degraded, full):
        """The assertion that matters. Two mechanisms, same page, same answer:
        that is evidence the fallback reads the cell it thinks it reads.

        Half a degree of slack because the visible DOM rounds where the state
        blob does not -- a real difference in the page, not in the parser."""
        assert degraded.current.temp_c == pytest.approx(full.current.temp_c, abs=0.5)

    def test_the_city_is_still_checked(self, current_html):
        """Identity does not get to degrade. A page that cannot be identified
        is rejected whether or not its numbers parse -- see `DECISIONS.md` §2,
        the wrong-city failure nothing downstream can catch."""
        stripped = without_flight(current_html)
        ident = X.identity(LH.fromstring(stripped), "")
        assert ident.name and "ошкар" in ident.name

    def test_the_daily_series_survives_too(self, degraded):
        assert len(degraded.daily) >= 7
        assert all(d.temp_max_c is not None for d in degraded.daily)


class TestTierTwoRemoved:
    """The accessibility prose goes. Most likely cause is mundane: a class name
    changes in a build. Tier 3 is content-shaped -- it classifies a cell by
    what is *in* it -- so it should not care."""

    @pytest.fixture(scope="class")
    @classmethod
    def degraded(cls, current_html):
        return X.parse(without_a11y(current_html))

    def test_it_still_produces_a_forecast(self, degraded):
        assert degraded.current.temp_c is not None

    def test_the_numbers_are_unchanged(self, degraded, full):
        assert degraded.current.temp_c == pytest.approx(full.current.temp_c, abs=0.5)


class TestBothRungsRemoved:
    """Down to content-shaped DOM alone. This is the state the health endpoint
    calls `fallback_profile`, and it is meant to be survivable but noisy."""

    @pytest.fixture(scope="class")
    @classmethod
    def degraded(cls, current_html):
        return X.parse(without_a11y(without_flight(current_html)))

    def test_something_still_comes_back(self, degraded):
        assert degraded.current is not None
        assert degraded.current.temp_c is not None

    def test_the_temperature_is_still_right(self, degraded, full):
        assert degraded.current.temp_c == pytest.approx(full.current.temp_c, abs=0.5)

    def test_the_profile_says_the_ground_moved(self, degraded):
        """`fallback_profile` exists for this moment: everything answered by
        the bottom rung, on a day when the numbers still happen to be right.
        That is the warning you want on a calm Tuesday rather than on the
        morning the forecast finally matters."""
        tiers = [v for v in degraded.provenance.values() if v != int(Tier.ABSENT)]
        assert tiers, "nothing was extracted at all"
        assert max(tiers) >= int(Tier.SHAPE)


class TestNothingLeft:
    """Every rung gone. The requirement inverts: fail, do not improvise."""

    def test_an_empty_page_raises_rather_than_returning_zero(self):
        with pytest.raises(ParseError):
            X.parse("<html><body></body></html>")

    def test_a_page_about_something_else_entirely_raises(self):
        with pytest.raises(ParseError):
            X.parse("<html><body><h1>Расписание поездов</h1>"
                    "<p>Отправление 14:30</p></body></html>")

    def test_a_page_with_numbers_but_no_weather_raises(self):
        """The nastiest input: plenty of plausible-looking figures and nothing
        that means a temperature. A shape-matching parser with no content
        classification would return something here."""
        with pytest.raises(ParseError):
            X.parse("<html><body><h1>Погода в Йошкар-Оле</h1>"
                    "<table><tr><td>743</td><td>1013</td><td>56.6</td></tr>"
                    "</table></body></html>")
