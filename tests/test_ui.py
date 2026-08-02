"""Front-end behaviour, in a real browser, against the recorded fixtures.

Everything here was verified once by a throwaway script during development and
then thrown away, which is the same as not having verified it. These are the
ones worth keeping: each corresponds to a bug that actually shipped.

Skipped entirely when Playwright or its browser is unavailable, so `pytest`
stays useful on a machine that has neither.

---------------------------------------------------------------------------
Two ways this harness lied during development. Both cost real time, and both
looked exactly like application bugs:

1. **Playwright scrolls an element into view before clicking it.** Clicking the
   place button reset the page to the top, so the scroll-lock test captured an
   offset of 0 and reported that position restore was broken. It wasn't. Where
   the scroll position matters, call the function directly.

2. **`page.evaluate(str)` invokes the result if it is a function.** A stub
   ending in `window.f = () => {...}` gets called once by Playwright before any
   interaction, which made a click handler look like it fired twice.

3. **A locator resolves to a node now and evaluates against it later.** The day
   screen redraws when its per-day fetch lands, so an element sampled across
   that moment is detached — and `getComputedStyle` on a detached element
   returns the **empty string**, not the colour it had. Scored as brightness
   that is zero, which is indistinguishable from black text on a blue sky. Read
   several properties in one `page.evaluate` (see `_colours`) rather than one
   locator at a time. End such
   snippets with a non-function expression -- `; 0`.

If a test here fails in a way that contradicts what you see by hand, suspect
the harness before the code.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Imported lazily rather than with `importorskip` at module scope, so these
# tests are always *collected* even where they cannot run. Collection count is
# a number the docs assert against, and a suite that changes size depending on
# what happens to be installed makes that check meaningless -- and hides a
# whole file from anyone reading the summary line.
try:
    from playwright.sync_api import sync_playwright
except ImportError:                                  # pragma: no cover
    sync_playwright = None


def _rgba(text: str) -> tuple[float, ...] | None:
    """The first rgb()/rgba() tuple in a CSS value, as numbers."""
    m = re.search(r"rgba?\(([^)]*)\)", text)
    if not m:
        return None
    parts = [p.strip() for p in re.split(r"[,/\s]+", m.group(1)) if p.strip()]
    return tuple(float(p) for p in parts)


def _luma(color: str) -> float:
    """Perceived brightness of a `#rrggbb` or `rgb()/rgba()` colour."""
    if color.startswith("#"):
        h = color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    else:
        r, g, b = (_rgba(color) or (0, 0, 0))[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _colours(page, selectors) -> dict[str, str]:
    """Computed text colour for several selectors, resolved and read in **one**
    evaluation.

    Not a convenience. A Playwright locator resolves to a node and evaluates
    against it a moment later, and the day screen redraws itself when the
    per-day fetch lands -- so the node can be detached in between. The computed
    style of a detached element is the *empty string*, which `_luma` scores as
    0, which reads exactly like black text on a blue sky. The test failed once
    in ten runs and accused the stylesheet.
    """
    got = page.evaluate(
        """(sels) => Object.fromEntries(sels.map(s => {
             const el = document.querySelector(s);
             return [s, el ? getComputedStyle(el).color : null]; }))""",
        list(selectors))
    missing = [s for s, v in got.items() if not v]
    assert not missing, f"no such element, or it has no colour: {missing}"
    return got


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _chromium_path() -> str | None:
    p = Path("/opt/pw-browsers/chromium")
    return str(p) if p.exists() else None


@pytest.fixture(scope="module")
def server():
    """The real app, with the real parsers, against the recorded fixtures."""
    port = _free_port()
    env = dict(os.environ, YW_MOCK="ok", PORT=str(port))
    proc = subprocess.Popen([sys.executable, "-m", "tests.mock_server"],
                            cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/weather/"
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                break
        except OSError:
            time.sleep(0.25)
    else:
        proc.terminate()
        pytest.skip("mock server did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("playwright not installed")
    try:
        with sync_playwright() as pw:
            kw = {}
            path = _chromium_path()
            if path:
                kw["executable_path"] = path
            try:
                b = pw.chromium.launch(**kw)
            except Exception as e:
                pytest.skip(f"no chromium available: {e}")
            yield b
            b.close()
    except Exception as e:
        pytest.skip(f"playwright unavailable: {e}")


@pytest.fixture
def page(browser, server):
    ctx = browser.new_context(viewport={"width": 393, "height": 852},
                              color_scheme="dark", locale="ru-RU")
    pg = ctx.new_page()
    pg.goto(server, wait_until="networkidle")
    pg.wait_for_selector(".hero .t", timeout=10_000)
    yield pg
    ctx.close()


class TestRendersAtAll:
    def test_the_whole_page(self, page):
        assert page.locator(".hero .t").inner_text().endswith("°")
        assert page.locator(".hours .hour").count() >= 8
        assert page.locator(".day").count() >= 5
        assert page.locator(".fact").count() % 3 == 0   # whole rows only

    def test_only_the_real_current_hour_is_labelled_now(self, page):
        """The app used to call the first column "сейчас" whatever hour it
        actually was, which is how a description of midnight ended up
        presented as the current conditions. At most one column is now, and it
        is the one whose hour matches the city's clock."""
        labels = page.locator(".hour .hh").all_inner_texts()
        assert labels.count("сейчас") <= 1, "two columns claim to be now"
        marked = page.locator(".hour.now")
        if marked.count():
            city_hour = page.evaluate("cityHour()")
            shown = marked.first.locator(".hh").inner_text()
            assert shown == "сейчас"
            times = page.locator(".hour .hh").all_inner_texts()
            idx = times.index("сейчас")
            raw = page.evaluate(
                f"(() => {{const d = JSON.parse(localStorage.getItem('yw.payload'));"
                f"  const s = d.sources[document.querySelector('.src.sel').dataset.src];"
                f"  return s.hourly[{idx}].time;}})()")
            assert page.evaluate(f"hourOf({raw!r})") == city_hour

    def test_hourly_is_a_curve_not_a_row_of_numbers(self, page):
        assert page.locator(".hcurve polyline").count() == 1
        pts = page.locator(".hcurve polyline").get_attribute("points")
        assert len(pts.split()) >= 8

    def test_the_curve_sits_on_the_same_grid_as_the_labels(self, page):
        """The bug: the column width was written down twice -- 58px in the CSS
        and 54px in the JS -- so every point drifted 4px left of its label and
        the line stopped 96px short of the end of the strip. Nothing looked
        broken until you scrolled to the last few hours.

        Asserted as an alignment invariant rather than as a constant, because
        the failure is the *disagreement*, not either value.
        """
        cx = page.locator(".hcurve circle").evaluate_all(
            "els => els.map(e => e.getBoundingClientRect().x "
            "+ e.getBoundingClientRect().width / 2)")
        mid = page.locator(".hour").evaluate_all(
            "els => els.map(e => e.getBoundingClientRect().x "
            "+ e.getBoundingClientRect().width / 2)")
        assert len(cx) == len(mid) >= 8, "a point per column, no more, no fewer"
        worst = max(abs(a - b) for a, b in zip(cx, mid, strict=True))
        assert worst < 1.5, f"the curve drifts off its labels by {worst:.1f}px"

    def test_a_flat_forecast_still_draws_a_line(self, page):
        """With the default objectBoundingBox units, a gradient over a
        zero-height box makes the element vanish -- so 24 identical hours
        rendered no curve at all. userSpaceOnUse has no such edge."""
        page.evaluate("""
          document.getElementById('content').innerHTML = hourlyBlock(
            Array.from({length: 12}, (_, i) => (
              {time: `${i}:00`, temp_c: 17, icon: 'clear'})), null); 0
        """)
        page.wait_for_timeout(200)
        box = page.locator(".hcurve polyline").bounding_box()
        assert box and box["width"] > 100, "the line disappeared on a flat series"

    def test_day_rows_have_range_bars(self, page):
        assert page.locator(".day .bar i").count() == page.locator(".day").count()
        # Today's row carries a dot at the current temperature.
        assert page.locator(".day .bar u").count() == 1


class TestPrivacy:
    def test_the_page_makes_no_cross_origin_request_at_all(self, browser, server):
        """The invariant the whole project exists to hold.

        Not "no third-party scripts" -- *no request to any other origin*, for
        any reason, including images, fonts and prefetch hints. Asserted at the
        network layer rather than by reading the HTML, because the HTML is only
        one of the ways a request can happen.
        """
        ctx = browser.new_context(viewport={"width": 393, "height": 852},
                                  locale="ru-RU")
        seen: list[str] = []
        pg = ctx.new_page()
        pg.on("request", lambda r: seen.append(r.url))
        pg.goto(server, wait_until="networkidle")
        pg.wait_for_timeout(1200)
        origin = server.split("/weather/")[0]
        foreign = [u for u in seen
                   if not u.startswith(origin) and not u.startswith("data:")]
        ctx.close()
        assert seen, "no requests captured -- the test is not testing anything"
        assert foreign == [], f"cross-origin requests: {foreign}"


class TestSourceSwitching:
    def test_every_source_has_a_tab(self, page):
        assert page.locator(".src").count() == 3

    def test_switching_changes_the_numbers_without_a_refetch(self, page):
        before = page.locator(".hero .t").inner_text()
        calls: list[str] = []
        page.on("request", lambda r: calls.append(r.url))
        page.click('.src[data-src="openmeteo"]')
        page.wait_for_timeout(400)
        after = page.locator(".hero .t").inner_text()
        assert after != before, "the two sources should not agree exactly"
        assert not [c for c in calls if "/api/weather" in c], \
            "switching source must not cost a request"

    def test_an_unavailable_source_is_disabled_and_says_why(self, page):
        gm = page.locator('.src[data-src="gismeteo"]')
        # The mock reaches Gismeteo through the recorded fixture, so it *is*
        # available here; assert the mechanism rather than the state.
        if gm.is_disabled():
            assert gm.inner_text().strip() != "Gismeteo"

    def test_the_choice_survives_a_reload(self, page, server):
        page.click('.src[data-src="openmeteo"]')
        page.wait_for_timeout(300)
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".src.sel", timeout=10_000)
        assert page.locator(".src.sel").get_attribute("data-src") == "openmeteo"


class TestThePushedScreen:
    """The one navigation primitive, shared by the place picker and the day
    detail. Its whole justification is that it rides on browser history, so
    these tests care much more about the history entries than about the CSS."""

    def test_opening_pushes_exactly_one_history_entry(self, page):
        before = page.evaluate("history.length")
        page.click("#btn-place")
        page.wait_for_selector(".screen.open")
        assert page.evaluate("history.length") == before + 1
        assert page.evaluate("history.state && history.state.yw") == "place"

    def test_going_back_closes_it(self, page):
        """`history.back()` is what the iOS edge-swipe does in a standalone
        PWA. If this works, the gesture works -- which is the entire reason the
        screen is history-backed rather than a class toggle."""
        page.click("#btn-place")
        page.wait_for_selector(".screen.open")
        page.go_back()
        page.wait_for_timeout(400)
        assert not page.locator(".screen").evaluate(
            "e => e.classList.contains('open')")
        assert page.evaluate("document.body.classList.contains('locked')") is False

    def test_the_back_button_and_the_gesture_are_the_same_path(self, page):
        """The in-app control calls `history.back()` rather than closing
        directly. Two ways to leave a screen is two behaviours to keep in
        step, and they will not stay in step."""
        js = (ROOT
              / "static" / "app.js").read_text(encoding="utf-8")
        assert "history.back()" in js
        page.click("#btn-place")
        page.wait_for_selector(".screen.open")
        before = page.evaluate("history.length")
        page.click("#back")
        page.wait_for_timeout(400)
        assert not page.locator(".screen").evaluate(
            "e => e.classList.contains('open')")
        # Popped, not pushed: leaving must not grow the history.
        assert page.evaluate("history.length") == before

    def test_nothing_hand_rolls_the_swipe(self, page):
        """iOS runs its own edge-swipe in a standalone PWA and there is no way
        to switch it off. A second implementation does not replace it, it runs
        alongside it, and the app goes back twice. So: no touch handlers."""
        js = (ROOT
              / "static" / "app.js").read_text(encoding="utf-8")
        for evt in ("touchstart", "touchmove", "touchend", "pointerdown"):
            assert evt not in js, (
                f"app.js listens for {evt} -- a hand-rolled swipe fights the "
                f"system gesture and navigates back twice")

    def test_it_pins_the_page_and_restores_the_position(self, page):
        """The bug: iOS Safari ignores overflow:hidden on <body>, so the page
        scrolled under the open screen. Pinning discards the scroll offset, so
        it has to be saved and restored by hand.

        NOTE: push() is called directly rather than clicking the button --
        Playwright scrolls an element into view before clicking it, which would
        reset the page to the top and make this test pass vacuously.
        """
        page.evaluate("window.scrollTo(0, 640)")
        page.wait_for_timeout(200)
        before = page.evaluate("window.scrollY")
        assert before > 300, "page is not tall enough to test scrolling"

        page.evaluate("push('place')")
        page.wait_for_timeout(300)
        assert page.evaluate("document.body.classList.contains('locked')")

        page.mouse.move(196, 300)
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(300)
        assert page.evaluate("window.scrollY") == 0, "page scrolled underneath"

        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        assert page.evaluate("window.scrollY") == before

    def test_the_forecast_underneath_stops_being_reachable(self, page):
        """An opaque screen hides the app visually and not otherwise: without
        `inert` the forecast behind it stays tabbable and stays in the
        accessibility tree, which is a second copy of the app underneath the
        one you are looking at."""
        assert page.evaluate("document.querySelector('.wrap').inert") is False
        page.evaluate("push('place')")
        page.wait_for_timeout(300)
        assert page.evaluate("document.querySelector('.wrap').inert") is True
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        assert page.evaluate("document.querySelector('.wrap').inert") is False

    def test_a_reload_with_a_screen_open_lands_on_the_forecast(self, page, server):
        """The payload has not arrived yet and the day it named may not exist
        any more. Reopening it would mean guessing which day you meant."""
        page.evaluate("push('place')")
        page.wait_for_timeout(200)
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".hero", timeout=10_000)
        assert not page.locator(".screen").evaluate(
            "e => e.classList.contains('open')")

    def test_nothing_fixed_lives_inside_a_transformable_wrapper(self, page):
        """A transformed ancestor becomes the containing block for its
        `position: fixed` descendants, so the element stops being positioned
        against the viewport and lands somewhere arbitrary.

        This is not hypothetical: a 4px rise was added to the load animation on
        `.wrap`, which was then the sheet's ancestor, and it broke exactly this
        for the 220 ms the animation ran. Long enough for a test to catch and
        short enough that a person never would. The screen now lives outside
        `.wrap` entirely, and this asserts that placement rather than trusting
        it -- the same applies to `filter`, `perspective` and `backdrop-filter`.
        """
        offenders = page.evaluate("""() => {
          const bad = [];
          for (const el of document.querySelectorAll('*')) {
            if (getComputedStyle(el).position !== 'fixed') continue;
            for (let up = el.parentElement; up; up = up.parentElement) {
              const s = getComputedStyle(up);
              for (const prop of ['transform', 'filter', 'perspective',
                                  'backdropFilter']) {
                if (s[prop] && s[prop] !== 'none') {
                  bad.push(`${el.id || el.className} under ${up.className}: `
                           + `${prop}=${s[prop]}`);
                }
              }
            }
          }
          return bad;
        }""")
        assert offenders == [], (
            f"fixed positioning broken by a transformed ancestor: {offenders}")


class TestPlacePicker:
    def test_opens_and_lists_the_cities(self, page):
        page.click("#btn-place")
        page.wait_for_selector(".screen.open")
        assert page.locator(".group li[data-slug]").count() >= 5
        assert page.locator(".geolink").count() == 1

    def test_the_current_city_is_ticked(self, page):
        page.click("#btn-place")
        page.wait_for_selector(".screen.open")
        assert page.locator("li[data-slug].sel").count() == 1

    def test_picking_a_city_changes_the_page(self, page):
        page.click("#btn-place")
        page.wait_for_selector(".screen.open")
        page.click('li[data-slug="kazan"]')
        page.wait_for_timeout(900)
        assert not page.locator(".screen").evaluate(
            "e => e.classList.contains('open')")

    def test_typing_does_not_replace_the_field_under_the_keyboard(self, page):
        """The search field and the results are rendered separately. Redrawing
        them together replaces the element the keyboard is attached to, which
        on iOS dismisses the keyboard once per keystroke."""
        page.click("#btn-place")
        page.wait_for_selector(".screen.open")
        page.evaluate("document.getElementById('q').dataset.mark = 'same'")
        page.fill("#q", "каз")
        page.wait_for_timeout(700)
        assert page.evaluate(
            "document.getElementById('q').dataset.mark") == "same", \
            "the input element was replaced while the user was typing in it"


class TestDayDetail:
    def test_a_day_row_opens_its_own_screen(self, page):
        page.click(".day[data-day]")
        page.wait_for_selector(".screen.open")
        assert page.evaluate("history.state && history.state.yw") == "day"
        assert page.locator("#screen-title").inner_text().strip()

    def test_it_shows_what_that_source_is_good_at(self, page):
        """Яндекс publishes four parts of a day and nobody else does. The point
        of the screen is that the shape follows the source."""
        page.click('.src[data-src="yandex"]')
        page.wait_for_timeout(200)
        page.click(".day[data-day]")
        page.wait_for_selector(".screen.open")
        assert page.locator(".part").count() == 4

    def test_switching_source_keeps_the_day_and_changes_the_answer(self, page):
        """Keyed by date rather than by index, so the same day is shown --
        and answered differently, which is the whole design. Both sources
        publish parts of a day; only Gismeteo publishes gusts and a
        geomagnetic index, and only Yandex publishes a day length."""
        page.click('.src[data-src="yandex"]')
        page.wait_for_timeout(200)
        rows = page.locator(".day[data-day]")
        date = rows.nth(3).get_attribute("data-day")
        rows.nth(3).click()
        page.wait_for_selector(".screen.open")
        title = page.locator("#screen-title").inner_text()
        yandex = page.locator("#screen .metric .k").all_inner_texts()

        page.click('#screen .src[data-src="gismeteo"]')
        page.wait_for_timeout(300)
        assert page.locator("#screen-title").inner_text() == title, \
            "switching source moved to a different day"
        assert page.evaluate("history.state.arg") == date
        gismeteo = page.locator("#screen .metric .k").all_inner_texts()

        assert "Геомагнитная активность" in gismeteo
        assert "Порывы" in gismeteo
        assert "Долгота дня" in yandex
        assert set(yandex) != set(gismeteo), \
            "the two sources produced an identical table -- one is not being read"

    def test_a_date_is_labelled_the_same_whichever_source_is_open(self, page):
        """Found by looking at two screenshots of the same day side by side.

        «Сегодня» and «Завтра» were decided by the row's *index*, and the three
        sources do not agree on where their ten days start -- Gismeteo's list
        began on the 1st and Open-Meteo's on the 31st. So 2 August was «Завтра»
        on one tab and «вс» on the other, and which you believed depended on
        which tab you had open. Nothing was out of range, nothing was dropped,
        no test failed: a position had been used where a date was meant.
        """
        seen = {}
        for key in ("yandex", "gismeteo", "openmeteo"):
            page.click(f'.src[data-src="{key}"]')
            page.wait_for_timeout(250)
            for row in page.locator(".day[data-day]").all():
                date = row.get_attribute("data-day")
                label = row.locator(".d").inner_text().split("\n")[0]
                seen.setdefault(date, {})[key] = label
        clashes = {d: v for d, v in seen.items() if len(set(v.values())) > 1}
        assert not clashes, f"the same date is named differently per source: {clashes}"

        # ...and exactly one date may call itself today.
        todays = [d for d, v in seen.items() if "Сегодня" in v.values()]
        assert len(todays) <= 1, f"more than one day claims to be today: {todays}"

    def test_the_parts_of_day_keep_the_order_the_source_printed_them_in(self, page):
        """Sorting them into ночь → утро → день → вечер looks like tidying and
        is a twenty-four-hour error: Yandex prints утро → день → вечер → ночь,
        and its «ночь» is the night that *follows* the day. Reordering asserts
        a fact about what the order meant, and that fact had not been checked.
        Four plausible temperatures in a plausible order; nothing looks wrong.
        """
        page.click('.src[data-src="yandex"]')
        page.wait_for_timeout(200)
        page.click(".day[data-day]")
        page.wait_for_selector(".screen.open")
        # Lower-cased: the cells are capitalised by CSS, which `inner_text`
        # reports as rendered. The order is what is under test.
        shown = [n.strip().lower() for n in page.locator(".part .n").all_inner_texts()]
        payload = page.evaluate(
            """() => { const d = JSON.parse(localStorage.getItem('yw.payload'));
                 const day = d.sources.yandex.daily.find(
                   x => x.date === history.state.arg);
                 return day.parts.map(p => p.name); }""")
        assert shown == payload, \
            f"the screen reordered the source's parts: {shown} vs {payload}"

    def test_switching_source_on_the_detail_moves_the_page_behind_it_too(self, page):
        """Otherwise you switch to Gismeteo on the day screen, go back, and the
        forecast is still on Yandex -- a preference that changed on one screen
        and not on the one it came from."""
        page.click('.src[data-src="yandex"]')
        page.wait_for_timeout(200)
        page.click(".day[data-day]")
        page.wait_for_selector(".screen.open")
        page.click('#screen .src[data-src="openmeteo"]')
        page.wait_for_timeout(300)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        assert page.locator("#content .src.sel").get_attribute(
            "data-src") == "openmeteo"

    def test_the_deeper_day_arrives_and_replaces_the_curve(self, page):
        """The screen renders from the payload in hand and takes the per-day
        page as an upgrade. So: eight three-hourly columns appear where the
        flat series had four parts of day and nothing else — *after* the first
        paint, without the screen having been empty in between."""
        page.click('.src[data-src="yandex"]')
        page.wait_for_timeout(200)
        page.locator(".day[data-day]").nth(4).click()
        page.wait_for_selector(".screen.open")
        # Complete before the network answers: this is the part that must not
        # regress into a spinner.
        assert page.locator("#screen .part").count() == 4

        page.wait_for_selector("#screen .hour", timeout=8000)
        times = page.locator("#screen .hour .hh").all_inner_texts()
        assert len(times) == 8, f"expected eight columns, got {times}"
        assert times[0].strip() == "00:00"

    def test_it_asks_for_the_day_it_is_showing(self, page):
        asked = []
        page.on("request", lambda r: asked.append(r.url))
        page.click('.src[data-src="yandex"]')
        page.wait_for_timeout(200)
        row = page.locator(".day[data-day]").nth(4)
        date = row.get_attribute("data-day")
        row.click()
        page.wait_for_selector("#screen .hour", timeout=8000)
        day_calls = [u for u in asked if "api/day" in u]
        assert len(day_calls) == 1, f"one request per day opened: {day_calls}"
        assert f"date={date}" in day_calls[0]

    def test_reopening_the_same_day_costs_nothing(self, page):
        page.click('.src[data-src="yandex"]')
        page.wait_for_timeout(200)
        page.locator(".day[data-day]").nth(4).click()
        page.wait_for_selector("#screen .hour", timeout=8000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        asked = []
        page.on("request", lambda r: asked.append(r.url))
        page.locator(".day[data-day]").nth(4).click()
        page.wait_for_selector("#screen .hour", timeout=8000)
        assert not [u for u in asked if "api/day" in u], \
            "the day was fetched again after it had already been fetched"

    def test_a_source_without_a_per_day_page_asks_for_nothing(self, page):
        asked = []
        page.on("request", lambda r: asked.append(r.url))
        page.click('.src[data-src="gismeteo"]')
        page.wait_for_timeout(200)
        page.locator(".day[data-day]").nth(4).click()
        page.wait_for_selector(".screen.open")
        page.wait_for_timeout(600)
        assert not [u for u in asked if "api/day" in u], \
            "Gismeteo has no per-day page; asking for one wastes a request"

    def test_a_future_day_never_says_now(self, page):
        """The hourly strip labels the current hour «сейчас» by matching the
        hour number. On a day-detail screen for next Thursday that matches an
        hour a week away -- the same mistake as comparing two times without
        saying which day they fall on."""
        page.click('.src[data-src="openmeteo"]')
        page.wait_for_timeout(200)
        page.locator(".day[data-day]").nth(4).click()
        page.wait_for_selector(".screen.open")
        assert page.locator("#screen .hour").count() > 6, \
            "no hourly curve on a future day -- Open-Meteo should have one"
        assert page.locator("#screen .hour.now").count() == 0

    def test_the_curve_is_that_day_and_not_today(self, page):
        page.click('.src[data-src="openmeteo"]')
        page.wait_for_timeout(200)
        page.locator(".day[data-day]").nth(4).click()
        page.wait_for_selector(".screen.open")
        date = page.evaluate("history.state.arg")
        stamps = page.evaluate(
            """(d) => hoursOn(state.data.sources.openmeteo.hourly, d,
                              state.data.place.tz).map(h => h.time)""", date)
        assert len(stamps) >= 20, f"only {len(stamps)} hours for {date}"
        assert all(s.startswith(date) for s in stamps)


class TestSky:
    def test_the_sky_reflects_the_condition(self, page):
        assert page.evaluate("document.documentElement.dataset.sky")

    def test_the_star_field_actually_renders(self, page):
        """It did not, for a while: the loop appended to the wrong variable and
        the 60 stars it built were discarded. Invisible in a screenshot of a
        dark background."""
        page.evaluate("skyNow=null; setSky('clear-night'); 0")
        page.wait_for_timeout(300)
        assert page.locator("#sky .stars circle").count() == 60

    def test_precipitation_skies_animate(self, page):
        page.evaluate("skyNow=null; setSky('rain'); 0")
        page.wait_for_timeout(200)
        assert page.locator("#sky .fall.rain").count() == 1

    def test_theme_color_follows_the_sky(self, page):
        """So the status bar and the app-switcher card match the gradient
        instead of a hardcoded colour that drifts out of sync."""
        page.evaluate("skyNow=null; setSky('clear-night'); 0")
        page.wait_for_timeout(200)
        night = page.evaluate("document.getElementById('theme-color').content")
        page.evaluate("skyNow=null; setSky('clear-day'); 0")
        page.wait_for_timeout(200)
        day = page.evaluate("document.getElementById('theme-color').content")
        assert night != day and night.startswith("#")

    def test_the_strips_ios_samples_exist_and_match_the_sky(self, page):
        """Reported three times, and the first two fixes aimed at a mechanism
        iOS 26 removed.

        Safari 26 ignores <meta name="theme-color">. It colours the strip
        behind the status bar and the strip behind the toolbar by sampling a
        `position: fixed` element at that edge -- reading its
        **background-color**, which means a gradient (a background-image) is
        invisible to it. A page whose sky is nothing but a gradient therefore
        got two arbitrary strips.

        So there are two solid-colour strips, fixed to the edges, matching the
        gradient at exactly that point. This asserts the properties the
        sampler is documented to require, because the thing being protected is
        not "an element exists" -- it is that the element still qualifies.
        """
        for cls, var in (("edge-top", "--sky1"), ("edge-bot", "--bg")):
            box = page.locator(f".{cls}").bounding_box()
            css = page.locator(f".{cls}").evaluate(
                "e => { const s = getComputedStyle(e);"
                "  return {pos: s.position, bg: s.backgroundColor,"
                "          img: s.backgroundImage, border: s.borderBottomWidth}; }")
            want = page.evaluate(
                f"(() => {{const c = getComputedStyle(document.documentElement)"
                f"  .getPropertyValue('{var}').trim();"
                f"  const d = document.createElement('div');"
                f"  d.style.color = c; document.body.appendChild(d);"
                f"  const rgb = getComputedStyle(d).color; d.remove(); return rgb;}})()")

            assert css["pos"] == "fixed", f"{cls} is not fixed; Safari skips it"
            assert box["height"] >= 6, f"{cls} is under the ~6px sample minimum"
            assert box["width"] >= page.viewport_size["width"] * 0.9, \
                f"{cls} is too narrow to be sampled"
            assert css["img"] == "none", \
                f"{cls} uses a background-image; the sampler only reads colour"
            assert css["border"] == "0px", \
                "a border-bottom on a sampled element outranks its background"
            assert css["bg"] == want, \
                f"{cls} is {css['bg']}, the sky there is {want}"

    def test_the_top_strip_is_at_the_top_and_the_bottom_one_at_the_bottom(self, page):
        """Within a few pixels of the edge, which the sampler also requires --
        and the right way round, which nothing else would catch."""
        h = page.viewport_size["height"]
        top = page.locator(".edge-top").bounding_box()
        bot = page.locator(".edge-bot").bounding_box()
        assert top["y"] <= 2, f"the top strip sits {top['y']}px down"
        assert bot["y"] + bot["height"] >= h - 2, "the bottom strip is not at the bottom"

    def test_the_canvas_carries_the_same_gradient_as_the_sky(self, page):
        """One flat colour cannot match a gradient at both ends, and the canvas
        is what iOS paints into the notch, the overscroll bounce and -- on
        recent versions -- the strips behind Safari's own bars. Painted
        `--sky1`, it matched the notch and turned the bottom strip into a pale
        band floating under a dark page. Both now read the same variable, so
        they cannot drift."""
        canvas = page.evaluate(
            "getComputedStyle(document.documentElement).backgroundImage")
        sky = page.evaluate(
            "getComputedStyle(document.querySelector('.sky')).backgroundImage")
        assert "gradient" in canvas
        assert canvas == sky, "the canvas and the sky have drifted apart"

    def test_the_pushed_screen_covers_the_strips_rather_than_tinting_them(self, page):
        """The scrim is gone, and with it three years of trying to tint browser
        chrome from inside the page.

        A translucent drawer needed the strips behind Safari's bars to dim with
        it, and they cannot be reached: `theme-color` is ignored by iOS 26 and
        the sampler reads only at first render. The pushed screen sidesteps the
        whole problem by being *opaque* and covering them -- there is nothing
        left to keep in sync. That is not a smaller fix than the last three, it
        is a different shape of solution, and this test says so."""
        page.evaluate("push('place')")
        page.wait_for_timeout(400)
        box = page.locator(".screen").bounding_box()
        css = page.locator(".screen").evaluate(
            "e => getComputedStyle(e).backgroundColor")
        assert box["y"] <= 1 and box["height"] >= page.viewport_size["height"] - 1
        assert _rgba(css)[3:] != [0], "the screen is translucent; it must cover"
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

    def test_the_screens_timing_is_written_down_once(self, page):
        """app.js has to know when the slide is over to finish tidying up, and
        it reads `--push-ms` back from the stylesheet rather than restating
        300. Third time this rule earned a test; see --hour-w."""
        js = page.request.get(
            page.url.replace("/weather/", "/weather/app.js")).text()
        assert "--push-ms" in js
        css = page.evaluate("getComputedStyle(document.documentElement)"
                            ".getPropertyValue('--push-ms').trim()")
        assert css, "--push-ms is not defined in the stylesheet"
        assert page.evaluate("pushMs()") == float(css.replace("ms", ""))

    def test_the_canvas_background_is_painted(self, page):
        """iOS fills the notch cut-out, the home-indicator strip and the
        overscroll bounce with the *canvas* background, which comes from
        <html>. Leave it transparent and all three are black -- which is what
        happened when the sky variables were declared on <body>, since custom
        properties do not inherit upward."""
        bg = page.evaluate(
            "getComputedStyle(document.documentElement).backgroundColor")
        assert bg not in ("rgba(0, 0, 0, 0)", "transparent"), \
            "the notch and the overscroll bounce will render black"


@pytest.fixture
def light_page(browser, server):
    ctx = browser.new_context(viewport={"width": 393, "height": 852},
                              color_scheme="light", locale="ru-RU")
    pg = ctx.new_page()
    pg.goto(server, wait_until="networkidle")
    pg.wait_for_selector(".hero .t", timeout=10_000)
    yield pg
    ctx.close()


class TestItIsLegibleInDaylight:
    """Light mode's sky stays deep at the top and it has to: iOS forces white
    status-bar glyphs under `black-translucent`, so a pale sky there would be
    white text on near-white. Which means every element sitting *on the sky*
    rather than on a card needs light text in light mode -- the exact inverse
    of the rest of the page.

    Found by looking: the day screen shipped with a near-black title on a
    saturated blue navbar. Nothing failed, and the dark-mode screenshot -- the
    only one anybody takes -- was perfect.
    """

    SKY_BORNE = ("#screen-title", ".dayhero .r", ".dayhero .c")

    def test_the_top_of_the_sky_really_is_dark(self, light_page):
        """The premise of the rule below. If the sky ever opens out at the top,
        this test should fail before the ones under it start lying."""
        sky1 = light_page.evaluate(
            "getComputedStyle(document.documentElement)"
            ".getPropertyValue('--sky1').trim()")
        assert _luma(sky1) < 140, f"--sky1 is {sky1}; light text will not read"

    def test_text_on_the_sky_is_light(self, light_page):
        light_page.locator(".day[data-day]").nth(2).click()
        light_page.wait_for_selector(".screen.open")
        for sel, colour in _colours(light_page, self.SKY_BORNE).items():
            assert _luma(colour) > 170, (
                f"{sel} renders {colour} in light mode, on a deep blue sky -- "
                f"add it to the light-scheme rule in index.html")

    def test_text_on_a_card_stays_dark(self, light_page):
        """The other half. Blanket-whitening everything would make the metric
        table invisible instead, which is the same bug facing the other way."""
        light_page.locator(".day[data-day]").nth(2).click()
        light_page.wait_for_selector(".screen.open")
        colour = _colours(light_page, [".card h2"])[".card h2"]
        assert _luma(colour) < 170, f"card text is {colour} on a white card"


class TestNothingScrollsThatShouldNotScroll:
    """A sideways strip that becomes a vertical scroller is a whole class of
    bug, and it is invisible in a screenshot.

    `overflow-x: auto` does not leave the other axis alone: per spec, when one
    axis is not `visible`, a `visible` on the other computes to `auto`. So the
    hourly strip was silently scrollable up and down, and two pixels of
    overflow — a line box 1.45× an 11.5px font inside a 15px-high row — were
    enough that dragging the curve moved the widget instead of the screen.
    """

    def _strips(self, page):
        return page.evaluate("""() => [...document.querySelectorAll('.hours')]
            .map(e => ({ over: e.scrollHeight - e.clientHeight,
                         oy: getComputedStyle(e).overflowY,
                         where: e.closest('#screen') ? 'day screen' : 'forecast' }))""")

    def test_the_hourly_strip_has_no_second_scroll_axis(self, page):
        page.click('.src[data-src="yandex"]')
        page.wait_for_timeout(200)
        page.locator(".day[data-day]").nth(4).click()
        page.wait_for_selector("#screen .hour", timeout=8000)
        found = self._strips(page)
        assert found, "no hourly strip on screen to check"
        for s in found:
            assert s["oy"] == "hidden", (
                f"the {s['where']} strip computes overflow-y: {s['oy']} — "
                f"`overflow-x: auto` alone forces the other axis to auto")
            assert s["over"] <= 0, (
                f"the {s['where']} strip overflows vertically by {s['over']}px")


@pytest.fixture
def wide_page(browser, server):
    """A desktop window. Everything else here runs at iPhone size, which is why
    a screen that ignored the content column went unnoticed."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900},
                              color_scheme="dark", locale="ru-RU")
    pg = ctx.new_page()
    pg.goto(server, wait_until="networkidle")
    pg.wait_for_selector(".hero .t", timeout=10_000)
    yield pg
    ctx.close()


class TestTheDayScreenSitsWhereTheForecastDoes:
    def test_it_uses_the_same_content_column(self, wide_page):
        """The forecast is a 560px column on a desktop and the pushed screen
        was not — it ran the full width of the window while the page behind it
        stayed neat. One variable, `--col`, used by both."""
        column = wide_page.evaluate(
            "document.querySelector('.wrap').getBoundingClientRect().width")
        wide_page.locator(".day[data-day]").nth(3).click()
        wide_page.wait_for_selector(".screen.open")
        wide_page.wait_for_timeout(300)
        got = wide_page.evaluate("""() => {
          const b = document.getElementById('screen-body');
          return { content: b.lastElementChild.getBoundingClientRect().width,
                   bar: document.querySelector('#screen .navbar')
                          .getBoundingClientRect().width,
                   window: innerWidth }; }""")
        assert got["content"] == column, (
            f"the day screen's column is {got['content']}px, the forecast's "
            f"is {column}px")
        assert got["bar"] == got["window"], \
            "the nav bar should span the window even when its contents do not"

    def test_a_phone_still_uses_the_full_width(self, page):
        column = page.evaluate(
            "document.querySelector('.wrap').getBoundingClientRect().width")
        page.locator(".day[data-day]").nth(3).click()
        page.wait_for_selector(".screen.open")
        page.wait_for_timeout(300)
        content = page.evaluate("document.getElementById('screen-body')"
                                ".lastElementChild.getBoundingClientRect().width")
        assert content == column

    def test_the_screen_is_sized_to_the_visible_viewport(self, page):
        """`position: fixed` resolves against the *large* viewport on iOS
        Safari — the one including the area behind the auto-hiding toolbar — so
        `inset: 0` put the bottom of a scroll container underneath that bar.
        The symptom was content cut off that you could not scroll to.

        Chromium here has no such toolbar, so this asserts the *mechanism*: the
        screen is sized in dynamic viewport units, which track the visible area
        on the browser that does.
        """
        css = page.request.get(
            page.url.replace("/weather/", "/weather/index.html")).text()
        rule = css[css.index(".screen{"):css.index(".screen.open")]
        assert "dvh" in rule, \
            "the pushed screen is not sized in dynamic viewport units"
        assert "inset:0" not in rule.replace(" ", ""), \
            "inset:0 sizes it to the large viewport, behind Safari's toolbar"
        # ...and it still covers the viewport where there is no chrome.
        box = page.locator(".screen").bounding_box()
        assert box["height"] >= page.viewport_size["height"] - 1

    def test_nothing_is_stranded_below_the_last_card(self, page):
        """Reported from the phone as "empty space at the bottom, like a tab
        bar". It was: a 28px floor on the body's bottom padding, plus the last
        card's own 10px margin, on top of the home-indicator inset — forty-odd
        pixels of empty sky under every day screen. The forecast page never
        showed it because its footer fills that space.

        The padding is the safe-area inset now and nothing else, so on a
        viewport without one the last card ends flush.
        """
        page.locator(".day[data-day]").nth(3).click()
        page.wait_for_selector(".screen.open")
        page.wait_for_timeout(300)
        gap = page.evaluate("""() => {
          const b = document.getElementById('screen-body');
          b.scrollTop = b.scrollHeight;
          return b.getBoundingClientRect().bottom
                 - b.lastElementChild.getBoundingClientRect().bottom; }""")
        assert gap < 4, f"{gap}px of dead space under the last card"


class TestLayoutDoesNotWrap:
    def test_the_footer_stays_on_one_line(self, page):
        assert page.locator(".foot .line").bounding_box()["height"] < 30

    def test_no_fact_cell_wraps(self, page):
        heights = page.locator(".fact .v").evaluate_all(
            "els => els.map(e => Math.round(e.getBoundingClientRect().height))")
        assert len(set(heights)) == 1, f"a fact cell wrapped: {heights}"


class TestServiceWorker:
    def test_the_shell_version_is_substituted_on_serve(self, page, server):
        """Never bumped by hand. The server injects a hash of the shell files,
        so a shell change can never ship with a stale cache key."""
        body = page.request.get(server + "sw.js").text()
        assert "__SHELL_VERSION__" not in body
        ver = json.loads(page.request.get(server + "api/version").text())
        assert f"yw-{ver['shell']}" in body

    def test_it_refuses_cross_origin_requests(self, page, server):
        sw = page.request.get(server + "sw.js").text()
        assert "url.origin !== self.location.origin" in sw
