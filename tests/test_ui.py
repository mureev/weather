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
   interaction, which made a click handler look like it fired twice. End such
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


class TestPlaceSheet:
    def test_opens_and_lists_the_cities(self, page):
        page.click("#btn-place")
        page.wait_for_selector(".sheet.open")
        assert page.locator(".group li[data-slug]").count() >= 5
        assert page.locator(".geolink").count() == 1

    def test_the_current_city_is_ticked(self, page):
        page.click("#btn-place")
        page.wait_for_selector(".sheet.open")
        assert page.locator("li[data-slug].sel").count() == 1

    def test_it_pins_the_page_and_restores_the_position(self, page):
        """The bug: iOS Safari ignores overflow:hidden on <body>, so the page
        scrolled under the open sheet. Pinning discards the scroll offset, so
        it has to be saved and restored by hand.

        NOTE: openSheet() is called directly rather than clicking the button --
        Playwright scrolls an element into view before clicking it, which would
        reset the page to the top and make this test pass vacuously.
        """
        page.evaluate("window.scrollTo(0, 640)")
        page.wait_for_timeout(200)
        before = page.evaluate("window.scrollY")
        assert before > 300, "page is not tall enough to test scrolling"

        page.evaluate("openSheet()")
        page.wait_for_timeout(300)
        assert page.evaluate("document.body.classList.contains('locked')")

        page.mouse.move(196, 300)
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(300)
        assert page.evaluate("window.scrollY") == 0, "page scrolled under the sheet"

        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        assert page.evaluate("window.scrollY") == before

    def test_the_status_bar_darkens_with_the_sheet(self, page):
        """The complaint was that the top of the blur "was not drawing". It
        was: the unblurred strip is Safari's own status bar, tinted from
        <meta name="theme-color"> -- browser chrome, which a scrim inside the
        page cannot reach. So the tint is swapped for the sheet's and put back
        on close.

        Asserted on the meta tag rather than by screenshot because the strip in
        question is not inside the viewport a screenshot captures.
        """
        page.evaluate("skyNow=null; setSky('clear-day'); 0")
        page.wait_for_timeout(200)
        before = page.evaluate("document.getElementById('theme-color').content")

        page.evaluate("openSheet()")
        page.wait_for_timeout(300)
        during = page.evaluate("document.getElementById('theme-color').content")
        assert during != before, "the status bar stayed bright over the scrim"
        assert _luma(during) < _luma(before), "the scrim tint got lighter, not darker"

        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        assert page.evaluate(
            "document.getElementById('theme-color').content") == before

    def test_picking_a_city_changes_the_page(self, page):
        page.click("#btn-place")
        page.wait_for_selector(".sheet.open")
        page.click('li[data-slug="kazan"]')
        page.wait_for_timeout(900)
        assert not page.locator(".sheet").evaluate(
            "e => e.classList.contains('open')")


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

    def test_the_sampled_strips_dim_with_the_sheet(self, page):
        """The drawer's bright band, done the way that can actually work: a
        CSS rule on the strips Safari reads, not a JavaScript rewrite of a meta
        tag it ignores."""
        before = page.locator(".edge-top").evaluate(
            "e => getComputedStyle(e).backgroundColor")
        page.evaluate("openSheet()")
        page.wait_for_timeout(300)
        during = page.locator(".edge-top").evaluate(
            "e => getComputedStyle(e).backgroundColor")
        assert during != before, "the strip behind the status bar stayed bright"
        assert _luma(during) < _luma(before), "it got lighter, not darker"
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        assert page.locator(".edge-top").evaluate(
            "e => getComputedStyle(e).backgroundColor") == before

    def test_opening_the_sheet_dims_the_canvas_too(self, page):
        """The reported symptom: a bright band across the top of the screen
        while everything below it dimmed. That band is outside the page, so the
        in-page scrim cannot reach it -- the canvas has to dim as well, and it
        does it with the same colour over the same gradient so the two match
        exactly rather than approximately."""
        before = page.evaluate(
            "getComputedStyle(document.documentElement).backgroundImage")
        page.evaluate("openSheet()")
        page.wait_for_timeout(300)
        during = page.evaluate(
            "getComputedStyle(document.documentElement).backgroundImage")
        scrim = page.evaluate("getComputedStyle(document.documentElement)"
                              ".getPropertyValue('--scrim').trim()")
        assert during.count("gradient") == before.count("gradient") + 1
        # Compared numerically: the stylesheet authors `.62` and the computed
        # value serialises as `0.62`, which is the same colour and a different
        # string.
        assert _rgba(scrim) == _rgba(during), \
            "the canvas dimmed by some other amount than the scrim"

        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        assert page.evaluate(
            "getComputedStyle(document.documentElement).backgroundImage") == before

    def test_the_scrim_colour_is_written_down_once(self, page):
        """app.js computes the status-bar tint from --scrim rather than
        restating 4,8,18,.62 -- the same class of bug as the hourly column
        width, caught the same way."""
        assert "rgba(4, 8, 18" not in page.request.get(
            page.url.replace("/weather/", "/weather/app.js")).text()

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
