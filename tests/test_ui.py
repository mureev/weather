"""Front-end behaviour, in a real browser, against the recorded fixtures.

Everything here was verified once by a throwaway script during development and
then thrown away, which is the same as not having verified it. These are the
ones worth keeping: each corresponds to a bug that actually shipped.

Skipped entirely when Playwright or its browser is unavailable, so `pytest`
stays useful on a machine that has neither.

---------------------------------------------------------------------------
Three ways this harness lied during development. All three cost real time,
and all three looked exactly like application bugs:

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

import datetime as dt
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import ClassVar

import pytest

from app import cities
from app.sun import zone

ROOT = Path(__file__).resolve().parent.parent

# Read out of `app.js` rather than restated here. A copy of a table is a table
# that disagrees with the original the first time someone adds a condition.
FX_TABLE = set(re.findall(
    r"^\s*'([a-z-]+)':\s*\[", (ROOT / "static" / "app.js").read_text(
        encoding="utf-8").split("const FX_OF")[1].split("};")[0], re.M))

# Imported lazily rather than with `importorskip` at module scope, so these
# tests are always *collected* even where they cannot run. Collection count is
# a number the docs assert against, and a suite that changes size depending on
# what happens to be installed makes that check meaningless -- and hides a
# whole file from anyone reading the summary line.
try:
    from playwright.sync_api import sync_playwright
except ImportError:                                  # pragma: no cover
    sync_playwright = None


def _fixtures_share_a_day() -> bool:
    """Do the Yandex and Gismeteo recordings describe overlapping days?

    `TestTheFixturesAreOneRecording` is the test that *fails* when they do not,
    and it should be the only one -- when a source is down and only one half
    can be re-recorded, half a dozen browser tests otherwise go red at once and
    every one of them reads as a bug in the app. One loud failure with the
    remedy in its message beats six confusing ones.
    """
    def days(name):
        p = ROOT / "tests" / "fixtures" / name
        return set(re.findall(r"20\d\d-[01]\d-[0-3]\d",
                              p.read_text(encoding="utf-8", errors="replace")))
    try:
        return bool(days("current.html") & days("mf-10days.html"))
    except OSError:
        return True


MIXED = "the fixtures are from different days -- see test_the_sources_overlap"


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
    """A Chromium to use instead of the one `playwright install` put in place:
    `$CHROMIUM_PATH` when it is set -- a sandbox or CI image with a browser
    baked in -- and otherwise `None`, which lets Playwright use its own."""
    return os.environ.get("CHROMIUM_PATH") or None


@pytest.fixture(scope="module")
def server():
    """The real app, with the real parsers, against the recorded fixtures."""
    port = _free_port()
    # Both ends on the fixtures' clock: the browser via `_pin`, the server via
    # this. They have to agree or the per-day fetch asks for a date the day
    # page is not about, and the parser rejects it exactly as designed.
    env = dict(os.environ, YW_MOCK="ok", PORT=str(port),
               YW_TODAY=FIXTURE_DAY.isoformat())
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


# The whole browser suite renders fixtures recorded on 13 August 2026, and half
# of what it checks is date-relative: today's row carries a dot, "Сегодня" is a
# label and not a weekday, the day screen fetches detail for the date it is
# showing. All of that quietly stopped being true on 1 August.
#
# It went unnoticed until a container's clock jumped eleven days mid-session
# and nine tests failed at once, none of them for the reason they were written.
# A suite that passes only during the week its fixtures were recorded is a
# suite with an expiry date on it.
#
# So the browser's clock is pinned to the fixtures' own day. `set_fixed_time`
# rather than `install`: it freezes `Date` and leaves timers alone, and the
# sheet's transitions are driven by timers.
#
# **An instant, not a wall-clock time, and the difference is a whole day.**
# `set_fixed_time` takes UTC; the front end asks what day it is **in the city**
# (`cityToday`, via `place.tz`). This was first written as a bare `22:00` -- the
# city's clock, handed to a function that reads UTC. Three hours out, and 22:00
# is close enough to midnight that three hours crosses it: the browser believed
# it was the 14th while the server, pinned through `YW_TODAY`, believed the
# 13th.
#
# Nothing failed. `dayLabel` got a consistent answer and rendered it faithfully,
# so the ten-day list simply opened on yesterday, «Сегодня» sat in the second
# row, the hourly strip put «сейчас» at 01:00, and every screenshot this harness
# produced looked subtly like a bug in the app. Both ends were pinned. They were
# pinned to different moments, which is the same failure as fixtures from two
# recordings, wearing a clock.
#
# So neither end is typed any more. The instant is **read off the fixture** --
# Gismeteo stamps its own pages, `<time-value class="current-time" timestamp>`
# -- and the server's day is that instant *in the city's zone*, not in UTC.
# Both matter, and the second one is the subtle half: a capture at 21:30 UTC is
# already the next morning in Yoshkar-Ola, so a `YW_TODAY` taken from the UTC
# date would put the two ends a day apart again for every recording made after
# nine in the evening. The last one was made at 20:27, with thirty-three
# minutes to spare.
def _fixture_now() -> dt.datetime:
    p = ROOT / "tests" / "fixtures" / "mf-current.html"
    m = re.search(r'current-time"[^>]*timestamp="(\d+)"',
                  p.read_text(encoding="utf-8", errors="replace"))
    if not m:
        raise AssertionError(
            f"{p.name} no longer stamps itself; the browser clock has nothing "
            f"to pin to. Find the page's own time or record it beside them.")
    return dt.datetime.fromtimestamp(int(m.group(1)), tz=dt.UTC)


FIXTURE_NOW = _fixture_now()
FIXTURE_DAY = FIXTURE_NOW.astimezone(zone(cities.get("yoshkar-ola").tz)).date()


def _pin(pg):
    pg.clock.set_fixed_time(FIXTURE_NOW)
    return pg


@pytest.fixture
def page(browser, server):
    ctx = browser.new_context(viewport={"width": 393, "height": 852},
                              color_scheme="dark", locale="ru-RU")
    pg = _pin(ctx.new_page())
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
        if not _fixtures_share_a_day():
            pytest.skip(MIXED)
        # Today's row carries a dot at the current temperature.
        assert page.locator(".day .bar u").count() == 1

    def test_both_halves_of_the_harness_agree_what_day_it_is(self, page):
        """A test of the pins, not of the app -- and it belongs here because
        nothing else was ever going to notice.

        The browser is frozen at an instant and the server is pinned to a date,
        and for a while those were two different days: `FIXTURE_NOW` held the
        *city's* wall clock, `page.clock.set_fixed_time` reads UTC, and three
        hours' error at 22:00 lands on tomorrow. Every assertion in this file
        still passed. The app was internally consistent -- it asks what day it
        is in the city and got one answer -- so the ten-day list simply opened
        with yesterday, «Сегодня» sat in the second row, «сейчас» pointed at
        01:00, and every screenshot the harness produced looked like a bug
        somebody would then go and hunt for in the stylesheet.

        Asserted through what is on the screen rather than by comparing the two
        pinned values to each other, because the thing worth protecting is that
        the picture is honest. The first row of a ten-day forecast is today.
        """
        if not _fixtures_share_a_day():
            pytest.skip(MIXED)
        first = page.locator(".day[data-day]").first
        assert "Сегодня" in first.inner_text(), (
            f"the forecast opens on {first.inner_text()!r}. The browser's clock "
            f"({FIXTURE_NOW.isoformat()}) and the server's YW_TODAY "
            f"({FIXTURE_DAY}) are naming different days in the city's zone -- "
            f"check that FIXTURE_NOW is a UTC instant, not a local one.")
        assert first.get_attribute("data-day") == FIXTURE_DAY.isoformat()


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

    def test_the_three_tabs_are_written_by_the_same_hand(self, page):
        """Reported by eye, and only visible by switching tabs: Gismeteo said
        «пасмурно» where the other two said «Пасмурно».

        The cause was the recovery path added when Gismeteo's state blob went
        away (§27). It reads the site's *header sentence* -- «в Йошкар-Оле
        пасмурно, небольшой дождь» -- where the phrase follows a city name and
        is naturally lowercase, and it was the ninth place in this codebase to
        need `cond[0].upper() + cond[1:]` and the first to forget it. The other
        eight had it written out by hand.

        So the fix was one function in `ru_text`, and this asserts the property
        across all three tabs rather than the eight call sites, because the
        thing that broke was never a call site -- it was that nobody owned the
        rule.
        """
        seen = {}
        for src in ("yandex", "gismeteo", "openmeteo"):
            tab = page.locator(f'.src[data-src="{src}"]')
            if tab.is_disabled():
                continue
            tab.click()
            page.wait_for_timeout(350)
            text = page.locator(".hero .cond").inner_text().strip()
            if text:
                seen[src] = text
        assert len(seen) >= 2, f"only {list(seen)} rendered a condition"
        wrong = {k: v for k, v in seen.items() if v[0] != v[0].upper()}
        assert not wrong, f"lower-cased where the others capitalise: {wrong}"


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
        # `aria-hidden` and the scroll lock flip on the instant. `.open` now
        # carries `visibility: visible` and has to survive the whole exit --
        # visibility used to be transitioned instead, and Safari answered by
        # not rasterising the layer until the animation was two thirds done.
        # So this waits the animation out rather than 400ms flat.
        page.wait_for_timeout(200)
        assert page.locator(".screen").get_attribute("aria-hidden") == "true"
        assert page.evaluate(
            "document.documentElement.classList.contains('locked')") is False
        # Polled rather than `wait_for_function`: the page's CSP is
        # `script-src 'self'` with no `unsafe-eval`, and Playwright's predicate
        # form compiles a string. That CSP is the point of the project.
        page.wait_for_selector(".screen:not(.open)", state="attached", timeout=3000)

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
        page.click("#close")
        # `.open` outlives the click by the length of the exit -- it is what
        # holds `visibility: visible` now. `aria-hidden` is the instant signal.
        page.wait_for_timeout(200)
        assert page.locator(".screen").get_attribute("aria-hidden") == "true"
        page.wait_for_selector(".screen:not(.open)", state="attached",
                               timeout=3000)
        # Popped, not pushed: leaving must not grow the history.
        assert page.evaluate("history.length") == before

    def test_nothing_hand_rolls_the_horizontal_swipe(self, page):
        """iOS runs its own edge-swipe-back in a standalone PWA and there is no
        way to switch it off. A second implementation does not replace it, it
        runs alongside it, and the app goes back twice.

        This used to assert that `app.js` registers **no** touch handlers at
        all, which was the right shape while the day detail was a screen pushed
        in from the right. It is a bottom sheet now, and a vertical drag is the
        one thing that makes a sheet feel like an object rather than an
        animation. Vertical does not collide with the system gesture.

        So the rule is narrowed rather than dropped, and this is the narrowed
        form: whatever `app.js` does with a touch, it must not act on
        **horizontal** movement, and it must not own dismissal. Every way out
        still goes through `history.back()`, which is what keeps the system
        swipe working and the history stack honest.
        """
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        # Matched as *registrations*, not as substrings. The bare-substring
        # form fired on the paragraph explaining why the system owns the
        # edge-swipe -- a test that trips on its own warning label, which the
        # next session fixes by deleting the label.
        listens = set(re.findall(r"addEventListener\(\s*['\"]([a-z]+)['\"]", js))
        for evt in ("pointerdown", "pointermove", "gesturestart", "gesturechange"):
            assert evt not in listens, f"app.js listens for {evt}"
        # `clientX` appears exactly once, and only to *give a gesture back*:
        # a mostly-sideways drag is the hourly strip's, not the sheet's.
        assert js.count("clientX") <= 2, (
            "app.js reads clientX more than the hand-back check needs -- "
            "something is acting on horizontal movement")
        assert "history.back()" in js, \
            "dismissal no longer goes through history; the system swipe breaks"

    def test_it_locks_the_page_without_moving_it(self, page):
        """The page must not scroll under an open sheet, and the scroll
        position must survive — but *nothing may move* to achieve either.

        This used to pin `<body>` to `position: fixed` and put the offset back
        by hand, on a note saying iOS ignores `overflow: hidden`. That was true
        until iOS 16.3. What it cost after that was invisible on a desktop and
        expensive on the phone: switching the body to fixed relayouts the whole
        document, and it happened in the same task that starts the sheet's
        transition, so the animation's first frames went missing. Two screen
        recordings measured the sheet appearing at 505pt and 573pt of a travel
        that starts at 793.

        Hence the strongest assertion here, and the one the old approach could
        never have passed: **`scrollY` never changes at all.** No save, no
        restore, no relayout.

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
        assert page.evaluate(
            "document.documentElement.classList.contains('locked')")
        assert page.evaluate("window.scrollY") == before, \
            "opening the sheet moved the page; the lock is not free"

        page.mouse.move(196, 300)
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(300)
        assert page.evaluate("window.scrollY") == before, \
            "the page scrolled underneath the sheet"

        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
        assert page.evaluate("window.scrollY") == before

    def test_the_sheet_is_visible_from_the_first_frame_of_its_entrance(self, page):
        """The entrance used to lose its first half, and nothing said so.

        `visibility` was in the same `transition` shorthand as `transform`, with
        the same 460ms duration. It does not fade -- it is a discrete property,
        and the flip lands at the midpoint. So for 230ms the sheet was already
        travelling and still `hidden`, and what a person saw was a panel
        materialising a third of the way up the screen, in motion. Reported for
        weeks as "the pop-up starts from the wrong position", fixed twice by
        adjusting positions, and only identified when `static/debug.js` sampled
        it on the phone: first visible Y of 533 against an expected 781, which
        is exactly 781 - (230/460) x 484.

        Asserted where the bug lived -- the computed transition -- because the
        symptom is a frame that never reaches the glass, and a test that waits
        for frames is a test that measures the CI machine's load.
        """
        page.click(".day[data-day]")
        page.wait_for_selector(".screen.open")
        got = page.evaluate(
            "() => getComputedStyle(document.getElementById('screen'))"
            "  .transitionDuration.split(', ')"
            "  .map((d, i) => [getComputedStyle(document.getElementById('screen'))"
            "    .transitionProperty.split(', ')[i], d])")
        vis = [d for prop, d in got if prop == "visibility"]
        assert vis, f"visibility is no longer transitioned at all: {got}"
        assert all(float(d.rstrip("s")) == 0 for d in vis), (
            f"while open, visibility transitions over {vis} -- WebKit flips a "
            f"discrete property at the midpoint, so the sheet spends that long "
            f"invisible and appears already in motion")

    def test_the_sheet_stays_on_screen_until_it_has_finished_leaving(self, page):
        """The other half: on the way out the delay has to be there, or the
        sheet vanishes at the midpoint and the last half of the exit plays to
        an empty screen."""
        closed = page.evaluate(
            "() => { const e = document.getElementById('screen');"
            "  const cs = getComputedStyle(e);"
            "  const p = cs.transitionProperty.split(', ');"
            "  const d = cs.transitionDelay.split(', ');"
            "  return p.map((n, i) => [n, d[i]]); }")
        vis = [d for prop, d in closed if prop == "visibility"]
        assert vis and any(float(d.rstrip("s")) > 0 for d in vis), (
            f"closed, visibility has no exit delay: {closed}")

    def test_the_sheet_gives_the_gesture_back_when_it_should(self, page):
        """The rule that decides between resizing the sheet and scrolling what
        is inside it. Driven as a table rather than by synthesising touch
        sequences, because the failure mode is a *missing* behaviour and a
        synthetic drag that quietly does nothing looks exactly like a pass.

        The case that shipped broken is the third: at the largest detent, an
        upward drag has to go to the content. The sheet has nowhere further to
        go, so claiming it clamps the transform to 0 *and* `preventDefault`s
        the native scroll — which makes a sheet whose content is taller than
        the screen completely unscrollable. Reported as "it sticks to the top
        and not all of the detail is visible".
        """
        cases = [
            # dy,  dx, atTop, sheet's?      why
            (40, 5, False, True, "вниз, не наверху — тянем лист"),
            (40, 5, True, True, "вниз с самого верха — закрываем"),
            (-40, 5, True, False, "вверх наверху — это скролл контента"),
            (-40, 5, False, True, "вверх со среднего — раскрываем"),
            (10, 60, False, False, "вбок — это часовая полоса"),
            (-10, 60, True, False, "вбок наверху — тоже полоса"),
        ]
        for dy, dx, at_top, want, why in cases:
            got = page.evaluate(
                "([dy, dx, t]) => dragBelongsToSheet(dy, dx, t)",
                [dy, dx, at_top])
            assert got is want, (
                f"dragBelongsToSheet({dy}, {dx}, atTop={at_top}) вернул {got}, "
                f"ожидалось {want} — {why}")

    def test_the_diagnostic_is_reachable_and_costs_the_shell_nothing(self, page):
        """`debug.js` runs the whole battery on the device and prints a verdict
        per line, so one screenshot answers what would otherwise be four
        rounds of "try this and tell me what you see".

        Two properties matter and neither is about what it measures. It has to
        be **reachable without a URL** -- a home-screen web app has one fixed
        `start_url` and no address bar -- so it hangs off the build badge. And
        it has to be **fetched, not bundled**: it is the one thing here allowed
        to require the network, so it belongs outside the cold load.
        """
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        assert "debug.js" in js, "nothing loads the diagnostic"
        # Matched as a *reference*, not as a substring: a stylesheet comment
        # may name the file when explaining which measurement it produced, and
        # a test that fires on its own documentation gets the documentation
        # deleted rather than the bug fixed.
        shell = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        assert not re.search(r"""(src|href)\s*=\s*["'][^"']*debug\.js""", shell), \
            "the diagnostic is referenced from the shell; it must be on demand"
        r = page.request.get(page.url.rstrip("/") + "/debug.js")
        assert r.status == 200, "debug.js is not served"
        assert "requestAnimationFrame" in r.text(), \
            "debug.js does not sample frames, which is its whole purpose"

    def test_the_diagnostic_actually_runs_and_reports_every_section(self, page):
        """That it is *served* was all this file checked, and serving a file
        that throws on line one is indistinguishable from serving a good one.

        The diagnostic is the tool of last resort here -- it is what gets used
        when a defect exists only on a phone nobody in the session is holding,
        and the moment it is needed is the worst possible moment to discover it
        has a typo in it. So this runs the whole battery in the harness and
        requires that it finished: every section heading present, a verdict on
        each line, and nothing thrown along the way.

        It cannot check the *values* -- Chromium has no safe area and no iOS
        compositor, which is exactly why the device version exists -- so it
        checks that the instrument works, not what it reads.
        """
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.evaluate("""() => { const s = document.createElement('script');
          s.src = 'debug.js'; document.head.appendChild(s); }""")
        page.wait_for_selector("#dbg", timeout=15_000)
        # The battery drives a full open and close of the sheet; give it the
        # two 900ms samples plus slack rather than guessing at a single number.
        page.wait_for_timeout(4000)
        text = page.locator("#dbg").inner_text()
        assert not errors, f"the diagnostic threw: {errors}"
        for section in ("сборка", "холостой ход", "открытие:", "закрытие:",
                        "верх экрана", "слоёв неба", "маска .fx",
                        "кто сверху", "круг", "зазор справа"):
            assert section in text, (
                f"the diagnostic printed no {section!r} line -- it stopped "
                f"early, or a section was renamed without updating this list")
        assert text.count("\n") > 30, f"only {text.count(chr(10))} lines printed"

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

        page.wait_for_selector("#screen .hour", state="attached", timeout=8000)
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
        page.wait_for_selector("#screen .hour", state="attached", timeout=8000)
        day_calls = [u for u in asked if "api/day" in u]
        assert len(day_calls) == 1, f"one request per day opened: {day_calls}"
        assert f"date={date}" in day_calls[0]

    def test_reopening_the_same_day_costs_nothing(self, page):
        page.click('.src[data-src="yandex"]')
        page.wait_for_timeout(200)
        page.locator(".day[data-day]").nth(4).click()
        page.wait_for_selector("#screen .hour", state="attached", timeout=8000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        asked = []
        page.on("request", lambda r: asked.append(r.url))
        page.locator(".day[data-day]").nth(4).click()
        page.wait_for_selector("#screen .hour", state="attached", timeout=8000)
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

    # Every icon the back end can emit, which is what `setSky` is handed. The
    # night forms are the three `sun.nightify` produces; the rest keep one
    # spelling round the clock, which is exactly why the night flag has to
    # arrive beside the icon rather than inside it.
    EVERY_ICON: ClassVar[list[str]] = [
        "clear", "clear-night", "partly", "partly-night", "cloudy",
        "cloudy-night", "overcast", "fog", "drizzle", "rain-light", "rain",
        "rain-heavy", "thunder", "hail", "sleet", "snow-light", "snow",
        "snow-heavy"]

    @pytest.mark.parametrize("icon", EVERY_ICON)
    def test_every_condition_has_a_sky_of_its_own(self, page, icon):
        """No icon may fall through to the default.

        The old mapping collapsed eighteen conditions into seven, so drizzle
        and a downpour drew the same rain and a thunderstorm drew rain as well.
        The point of the second table is that the motion carries the intensity;
        an icon that quietly lands on `cloudy-night` has lost that and looks
        like a bug in the forecast rather than a gap in a lookup.
        """
        got = page.evaluate(
            "(k) => { fxNow=null; setSky(k, false);"
            " return [...document.querySelectorAll('#fx > *')]"
            "   .map(e => e.getAttribute('class')); }", icon)
        assert got, f"{icon} renders an empty sky"
        assert icon in FX_TABLE, f"{icon} is not in FX_OF"

    def test_the_intensities_are_told_apart(self, page):
        """Drizzle, rain and a downpour have to differ in the thing a glance
        picks up -- how fast and how dense -- not merely in the caption."""
        seen = {}
        for icon in ("drizzle", "rain", "rain-heavy"):
            seen[icon] = page.evaluate(
                "(k) => { fxNow=null; setSky(k, false);"
                " const e = document.querySelector('#fx .p');"
                " const s = getComputedStyle(e);"
                " return [s.animationDuration, s.backgroundSize]; }", icon)
        assert len({tuple(v) for v in seen.values()}) == 3, seen

    def test_night_changes_the_weather_and_not_only_the_palette(self, page):
        """Rain at midnight is still spelled `rain`, so without the envelope's
        night flag the drops stay lit for noon.

        Asserted on the drops, which are what the flag now reaches: it lands as
        `data-night` on the root and the stylesheet keys off it. The cloud layer
        this used to read is gone -- see `FX_OF`.
        """
        look = ("(n) => { fxNow=null; setSky('rain', n);"
                " return getComputedStyle(document.querySelector('#fx .rain'))"
                "   .backgroundImage; }")
        day, night = page.evaluate(look, False), page.evaluate(look, True)
        assert day != night, f"the drops look the same at midnight: {day}"
        assert page.evaluate("document.documentElement.hasAttribute('data-night')")

    @pytest.mark.parametrize("icon", ["overcast", "cloudy", "rain", "fog", "clear"])
    def test_no_seam_where_the_status_bar_strip_ends(self, page, icon):
        """The band across the top of the phone, reported twice, asserted in
        pixels because two rounds of reasoning about it were both wrong.

        `.edge-top` is ten points of flat `--sky1` painted over the sky so iOS
        has an opaque element to sample for the status-bar tint. Every sky
        effect lives *under* those ten points and *over* everything below, so
        anything that brightens the sky brightens it starting at exactly y=10
        and the phone draws a hard line there. Measured on the render at the
        time: rgb(35,44,64) above, rgb(41,50,70) below, six per channel with no
        ramp between them -- small on paper, and the first thing the eye finds
        on an OLED at night.

        Neither the DOM nor the computed styles show this; the elements are all
        exactly where they should be. Only the pixels show it, so the pixels
        are what this reads. Anything above three levels in one step, anywhere
        in the top sixty points, is an edge somebody will see.
        """
        Image = pytest.importorskip("PIL.Image", reason="pillow not installed")
        page.evaluate("(k) => { fxNow=null; setSky(k, false); }", icon)
        page.wait_for_timeout(250)
        # Six points in from the left edge, not the middle: the city name sits
        # in the middle and white text is a step of two hundred levels, which
        # is a true reading of something this test is not about.
        shot = page.screenshot(clip={"x": 0, "y": 0, "width": 20, "height": 70})
        im = Image.open(io.BytesIO(shot)).convert("RGB")
        col = [im.getpixel((6, y)) for y in range(im.size[1])]
        jumps = [(y, col[y - 1], col[y]) for y in range(1, len(col))
                 if max(abs(a - b)
                        for a, b in zip(col[y - 1], col[y], strict=True)) >= 3]
        assert not jumps, (
            f"{icon}: a visible step down the top of the screen at "
            f"{[j[0] for j in jumps]} -- {jumps[0][1]} then {jumps[0][2]}. "
            f"The sky effect starts under `.edge-top` and the mask's top hold "
            f"is too short to clear it.")

    def test_nothing_animates_a_property_the_compositor_cannot_run(self, page):
        """`transform` and `opacity` only.

        Anything else -- `background-position`, `top`, `filter` -- is a job for
        the main thread on every frame, and the main thread here is drawing a
        temperature curve. This reads the keyframes out of the stylesheet
        rather than trusting the rules, because a `@keyframes` block is where
        such a property actually gets in.
        """
        props = page.evaluate("""() => {
          const out = new Set();
          for (const sheet of document.styleSheets)
            for (const rule of sheet.cssRules)
              if (rule instanceof CSSKeyframesRule)
                for (const kf of rule.cssRules)
                  for (const p of kf.style) out.add(p);
          return [...out]; }""")
        allowed = {"transform", "opacity", "visibility",
                   # The one exception, and it is bounded: `sheen` is the
                   # loading skeleton, which exists only until the first render
                   # and is the one moment on this page when the main thread has
                   # nothing else to do.
                   "background-position-x", "background-position-y"}
        assert set(props) <= allowed, f"animated off the compositor: {props}"
        assert "transform" in props, "no keyframes read at all; check the query"

    @pytest.mark.parametrize("icon", ["rain", "snow", "hail", "fog"])
    def test_a_falling_layer_travels_exactly_one_tile(self, page, icon):
        """The bug this whole rewrite is about, asserted as arithmetic.

        A pattern that repeats every P pixels may only be translated by a whole
        multiple of P, or the wrap is a jump. The rain used an angled
        `repeating-linear-gradient` whose 46px period was 190px measured
        *vertically*, while the animation moved 168px -- so every 0.85s the
        screen twitched 22 pixels sideways, which is what a person watching it
        described as the lines jerking.

        The fix is structural: the vertical repeat is `background-size`'s
        height, the travel is the same custom property, and the slant is a
        skew, which leaves the vertical period alone. So this compares the two
        numbers the browser actually resolved. If they ever part, the seam is
        back.
        """
        page.evaluate("(k) => { fxNow=null; setSky(k, false); }", icon)
        page.wait_for_timeout(150)
        rows = page.evaluate("""() =>
          [...document.querySelectorAll('#fx .p, #fx .b')].map(e => {
            const s = getComputedStyle(e);
            return [s.backgroundSize, s.getPropertyValue('--tile').trim()]; })""")
        assert rows, f"{icon} has no falling layer"
        for size, tile in rows:
            # `background-size: 26px 40px` -> the vertical repeat is 40px.
            # A fog band has no background-size; its repeat is the gradient's
            # own last stop, which is also `--tile`.
            if size and size != "auto":
                assert size.split()[-1] == tile, (
                    f"{icon}: the pattern repeats every {size.split()[-1]} but "
                    f"the animation travels {tile} -- the loop will jump")
            assert tile.endswith("px"), f"{icon}: --tile is {tile!r}, not px"

    def test_reduced_motion_stops_all_of_it(self, browser, server):
        """Stopped, not stripped: the still frame of any of these is a
        legitimate picture of the weather."""
        ctx = browser.new_context(viewport={"width": 393, "height": 852},
                                  color_scheme="dark", locale="ru-RU",
                                  reduced_motion="reduce")
        pg = _pin(ctx.new_page())
        pg.goto(server, wait_until="networkidle")
        pg.wait_for_selector(".hero .t", timeout=10_000)
        pg.evaluate("fxNow=null; setSky('snow-heavy', true); 0")
        pg.wait_for_timeout(200)
        names = pg.evaluate(
            "[...document.querySelectorAll('#fx *')]"
            ".map(e => getComputedStyle(e).animationName)")
        ctx.close()
        assert names, "nothing rendered, so nothing was tested"
        assert set(names) == {"none"}, f"still moving under reduce: {names}"

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
            named = (f"getComputedStyle(document.documentElement)"
                     f".getPropertyValue('{var}').trim()"
                     if var.startswith("--") else f"'{var}'")
            want = page.evaluate(
                f"(() => {{const c = {named};"
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

    @pytest.mark.parametrize("sky", ["clear-day", "cloudy-day", "overcast",
                                     "rain", "snow", "clear-night"])
    def test_the_canvas_continues_the_sky_rather_than_interrupting_it(
            self, page, sky):
        """The one that hid behind nightfall for six attempts.

        `html`'s gradient is `background-size: 100% 100%, no-repeat`, so it
        covers the viewport and stops. On this phone the viewport is 59pt
        shorter than the display, and those 59 points get the root's
        `background-color` — permanently, on every screen. It was `--sky2`,
        which is the gradient's colour at its 62% stop, so the bottom of the
        display wore a strip of the *middle* of the sky.

        Invisible at night, because `clear-night` and `cloudy-night` both set
        `--sky2: #0a1020` and so does `--bg`. Every measurement taken while
        chasing this was taken in the evening. The first daylight screenshot
        showed the strip at (25,35,59) under content faded to (11,16,32).

        Parametrised over every sky for that reason and no other: one palette
        agreeing proves nothing here, and the two that agree are the two that
        were looked at.
        """
        # `html` carries `transition: background-color 1.2s`, so a computed
        # colour read straight after switching skies is a frame from the middle
        # of a fade. Suppressed rather than waited out -- the question here is
        # which colour the rule resolves to, not how it gets there.
        got = page.evaluate(
            "(() => { const s = document.createElement('style');"
            "  s.textContent = 'html{transition:none!important}';"
            "  document.head.appendChild(s); window.__t = s; })()")
        got = page.evaluate(
            f"(() => {{ document.documentElement.dataset.sky = '{sky}';"
            "  const h = getComputedStyle(document.documentElement);"
            "  const d = document.createElement('div');"
            "  d.style.color = h.getPropertyValue('--bg').trim();"
            "  document.body.appendChild(d);"
            "  const bg = getComputedStyle(d).color; d.remove();"
            "  return {canvas: h.backgroundColor, bg,"
            "          grad: h.backgroundImage}; })()")
        assert got["canvas"] == got["bg"], (
            f"with a {sky} sky the canvas is {got['canvas']} but the gradient "
            f"ends on {got['bg']} — so the strip below the viewport is a slice "
            f"of the middle of the sky stuck to the bottom of the display")
        assert got["grad"].rstrip(")").endswith(got["bg"] + " 100%"), (
            "the canvas gradient no longer ends on --bg; the assertion above "
            "is now comparing against the wrong end of it")

    def test_the_screens_fade_ends_on_the_colour_the_strip_is_painted(self, page):
        """Two values that have to be the same colour or the fix does nothing.

        The bottom 59pt of the phone's display is drawn by iOS, not by us, and
        it takes its colour from `.edge-bot`. The day screen dissolves its last
        56 points into a gradient so no content ends at a hard edge above it --
        but that only hides the seam if the gradient's final stop is *exactly*
        the colour the strip is painted. Move one and the fade lands on a
        slightly different dark blue, which is a band again, and nothing on a
        desktop browser would show it: there is no strip there to mismatch.

        Same species as `--hour-w` and `--push-ms`: a value that must agree in
        two places, asserted as an agreement rather than as either value.
        """
        got = page.evaluate(
            "(() => { const s = getComputedStyle(document.getElementById('sheetfade'));"
            "  const h = getComputedStyle(document.documentElement);"
            "  const b = h.getBoundingClientRect ? null : null;"
            "  return {fade: s.backgroundImage, bottom: s.bottom,"
            "          pos: s.position, canvas: h.backgroundColor}; })()")
        assert "gradient" in got["fade"], \
            "there is no bottom fade; a cut-off card sits on a hard edge"
        assert got["pos"] == "fixed" and got["bottom"] == "0px", (
            "the fade is not anchored to the viewport. Inside the sheet it "
            "travels with it, and at the medium detent the sheet's own bottom "
            "edge is below the fold -- so it would be absent exactly when a "
            "card is being cut off")
        assert got["canvas"] in got["fade"], (
            f"the fade ends on something other than {got['canvas']}, which is "
            f"what the canvas paints below the viewport -- so the seam is back")

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

    def test_the_sheet_reaches_the_bottom_and_matches_what_is_beyond_it(self, page):
        """The load-bearing test of the whole affair. Three assertions, and the
        third is the one that cost three deploys.

        The sheet cannot be translucent: an earlier drawer was, and needed the
        strips behind Safari's bars to dim along with it, which cannot be done
        from inside a page -- `theme-color` is ignored by iOS 26 and the sampler
        reads only at first render. So it is opaque.

        It has to reach the bottom of the viewport, because a panel that stops
        short of the fold has a hard edge floating in the middle of the glass.

        And its background has to be the same colour as the **canvas**, because
        the last 59pt of this phone's display is below the viewport entirely --
        no element reaches it, the root's `background-color` paints it, and if
        the sheet ends on any other colour there is a visible band there for as
        long as the app exists. It ended on `--sky1`-through-a-gradient while
        the canvas painted `--sky2`; both are `#0a1020` at night, which is when
        every screenshot in the investigation was taken.
        """
        page.evaluate("push('place')")
        page.wait_for_timeout(400)
        box = page.locator(".screen").bounding_box()
        got = page.evaluate(
            "(() => { const s = getComputedStyle(document.getElementById('screen'));"
            "  return {bg: s.backgroundColor, img: s.backgroundImage,"
            "          canvas: getComputedStyle(document.documentElement)"
            "                    .backgroundColor}; })()")
        bottom = box["y"] + box["height"]
        assert bottom >= page.viewport_size["height"] - 1, \
            f"the sheet ends at {bottom} in a {page.viewport_size['height']}px view"
        assert _rgba(got["bg"])[3:] != [0], \
            "the sheet is translucent; it must cover what is behind it"
        assert got["bg"] == got["canvas"], (
            f"the sheet is {got['bg']} and the canvas below the viewport is "
            f"{got['canvas']} -- that difference is a permanent band along the "
            f"bottom of the phone, and it is invisible at night")
        assert got["img"] == "none", (
            "the sheet carries a background *image*; only its flat colour can "
            "be matched against the canvas, so a gradient here means the edge "
            "is unverifiable and was wrong last time")
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
    pg = _pin(ctx.new_page())
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
        page.wait_for_selector("#screen .hour", state="attached", timeout=8000)
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
    pg = _pin(ctx.new_page())
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

    def test_the_sheet_is_inset_at_the_top_and_flush_at_the_bottom(self, page):
        """A sheet, so the top is deliberately *not* flush.

        Which is half of why it is a sheet. A panel that covers the whole
        display promises the whole display, and this phone keeps 59pt of it
        back; a panel that visibly starts below the status bar with the page
        behind it never made that promise, so the same 59pt at the bottom stops
        reading as a failure to deliver.

        The bottom still has to be flush — everything below the sheet is
        unreachable canvas, and a gap there would be the original bug.

        Two earlier versions of this test lived here, one asserting `inset: 0`
        and one asserting a full-height box, and both passed throughout the
        whole investigation. A desktop browser cannot see this bug, so the
        assertions that matter are the colour ones in `TestSky`.
        """
        # Opened first, and that is not boilerplate: the version of this test
        # before the sheet measured the *closed* panel and passed, because a
        # closed panel translated sideways still has top: 0. Translated
        # downwards it does not, which is the only reason anyone noticed.
        page.locator(".day[data-day]").nth(2).click()
        page.wait_for_selector(".screen.open")
        page.wait_for_timeout(400)
        def box():
            return page.evaluate(
                "(() => { const b = document.getElementById('screen')"
                ".getBoundingClientRect();"
                " return [b.top, b.bottom, window.innerHeight]; })()")

        top, bottom, h = box()
        assert h * 0.3 <= top <= h * 0.62, (
            f"the medium detent puts the sheet's top at {top} in a {h}px view: "
            f"either it is covering the forecast it is supposed to sit over, "
            f"or there is no room left to show a day")
        assert bottom >= h - 1, f"the sheet ends at {bottom}, above the fold"

        page.evaluate("goDetent('large')")
        page.wait_for_timeout(600)
        top, bottom, h = box()
        assert 30 <= top <= h * 0.16, (
            f"the large detent starts {top}px down: too flush to read as a "
            f"sheet at all, and a sheet that fills the display is the push "
            f"this replaced")
        assert bottom >= h - 1, f"the sheet ends at {bottom}, above the fold"

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
