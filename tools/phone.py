"""Render the app the way the phone actually renders it.

`python -m tools.phone` -> screenshots/phone-*.png
`PHONE_LANG=en python -m tools.phone` -> the same, in English
`python -m tools.phone --readme` -> also docs/forecast.png and docs/day.png,
    the two pictures at the top of the README: English, on Yandex's morning

Six attempts at one bug were spent looking at a desktop window and reasoning
about a phone, so this renders at the device's real geometry instead.

What a plain Playwright shot still gets wrong: **`env(safe-area-inset-*)` is 0
in Chromium**, where the phone reports 59 at the top and 34 at the bottom --
most of a nav bar's height. Those are injected below.

What it *used* to get wrong is the more interesting half, and it is recorded at
`VIEW`: this file was built around a 59pt discrepancy whose cause it had not
identified, and so it reproduced that discrepancy faithfully long after the
cause was removed. See DECISIONS.md §26.
"""
import asyncio
import datetime as dt
import os
import pathlib
import re
import subprocess
import sys
import time

from PIL import Image
from playwright.async_api import async_playwright

from app import cities
from app.sun import zone

OUT = pathlib.Path("screenshots")
OUT.mkdir(exist_ok=True)

# The moment the fixtures were recorded, read off the page that stamps itself:
# Gismeteo ships `<time-value class="current-time" timestamp>`. Derived rather
# than typed, so `make fixtures-gm` carries the harness along with it.
#
# Both ends are pinned to it -- the server by day through `YW_TODAY`, the
# browser by instant through `page.clock` -- for the same reason the browser
# suite is. Without it this tool renders August's fixtures against whatever day
# the machine thinks it is, and a September session gets screenshots with
# «Сегодня» three rows down and no dot anywhere, which looks precisely like the
# bug it reached for the screenshots to investigate.
#
# The instant is UTC and the *day* is the city's, which is not the same day for
# a capture made after nine in the evening. See DECISIONS.md §28; that gap is
# what put yesterday at the top of every shot this tool produced.
def _fixture_now() -> dt.datetime:
    p = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures"
    m = re.search(r'current-time"[^>]*timestamp="(\d+)"',
                  (p / "mf-current.html").read_text(encoding="utf-8",
                                                    errors="replace"))
    if not m:
        raise SystemExit("mf-current.html no longer stamps itself -- nothing "
                         "to pin the clock to. Re-run `make fixtures-gm`.")
    return dt.datetime.fromtimestamp(int(m.group(1)), tz=dt.UTC)


FIXTURE_NOW = _fixture_now()
# The README's shots open on the Yandex tab, and the Yandex set was recorded
# the morning *after* the Gismeteo one this pins to (AGENTS.md, "Where this
# was left"). Shot at 21:15 on the 14th, that tab's list began «Завтра», no
# hour said «сейчас», and today's range was missing. `PHONE_AT` shoots at
# another instant: `PHONE_AT=2026-08-15T04:05:00+00:00` is Yandex's morning.
README = "--readme" in sys.argv
if README:
    os.environ.setdefault("PHONE_AT", "2026-08-15T04:05:00+00:00")
    os.environ.setdefault("PHONE_LANG", "en")
if os.environ.get("PHONE_AT"):
    FIXTURE_NOW = dt.datetime.fromisoformat(os.environ["PHONE_AT"])
# The browser's language is what the app reads to choose its own, as a phone's
# would be: `ru` or `en`.
LOCALE = "en-US" if os.environ.get("PHONE_LANG") == "en" else "ru-RU"
FIXTURE_DAY = FIXTURE_NOW.astimezone(zone(cities.get("yoshkar-ola").tz)).date()

# iPhone 15 Pro, measured on the device by `static/debug.js`.
#
# **These are the same number, and this file used to insist they were not.** It
# shot at 393x793 and composited a 59pt strip underneath, on the finding that
# iOS hands a standalone web app a viewport shorter than its display. The
# measurement was real; the cause was not iOS. The app was pinning `<body>` to
# `position: fixed` as a scroll lock, and that is what collapses the viewport
# to the small viewport. With the lock gone the phone reports `inner 393x852`
# and there is no strip.
#
# A harness built from a measurement inherits everything that measurement did
# not explain, and this one spent a round confirming a theory it had been built
# out of. Setting `VIEW` back to (393, 793) reproduces the old device exactly,
# which is the only reason the compositing code below still exists.
DISPLAY = (393, 852)
VIEW = (393, 852)
INSET_TOP, INSET_BOTTOM = 59, 34
DSF = 3

# `env()` cannot be assigned, so the two places the stylesheet spends the
# insets are overridden by hand. Keep this in step with index.html: if a third
# rule starts reading a safe-area inset, it belongs here too or the shot is
# quietly wrong in the same direction as the bug.
INSETS = f"""
  body {{ padding-top: {INSET_TOP}px !important;
          padding-bottom: {INSET_BOTTOM}px !important; }}
  .screen {{ top: {INSET_TOP + 10}px !important; }}
"""

# The phone runs the *installed* app, and the stylesheet has rules for that
# alone (`@media (display-mode: standalone)`, DECISIONS.md §41). Chromium cannot
# be put in that mode, so the rules are made unconditional instead -- the same
# move as `tests/test_ui.py`'s `installed` fixture, and for the same reason as
# `INSETS`: a shot missing them is quietly wrong in the direction of the bug.
AS_INSTALLED = """() => { let n = 0;
  for (const sheet of document.styleSheets)
    for (const r of sheet.cssRules)
      if (r.media && /display-mode:\\s*standalone/.test(r.media.mediaText)) {
        r.media.mediaText = 'all'; n++; }
  return n; }"""


def _rgb(css: str) -> tuple[int, int, int]:
    """`rgb(r, g, b)` or, for a `color-mix()`, `color(srgb r g b)`."""
    m = re.search(r"color\(srgb\s+([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)", css)
    if m:
        return tuple(round(float(v) * 255) for v in m.groups())
    return tuple(int(float(n)) for n in re.findall(r"[\d.]+", css)[:3])


def _chromium_path() -> str | None:
    """The same discovery as `tests/test_ui.py`: `$CHROMIUM_PATH` when it is
    set, otherwise `None`, which lets Playwright use the browser `playwright
    install` put in place. Hard-coding a path meant this tool ran only on
    machines that happened to have one there."""
    return os.environ.get("CHROMIUM_PATH") or None


async def shoot(pg, name: str, strip: str):
    """Screenshot the 793pt view and paste the 59pt system strip under it."""
    raw = OUT / f".{name}.png"
    await pg.screenshot(path=str(raw))
    view = Image.open(raw).convert("RGB")
    out = Image.new("RGB", (DISPLAY[0] * DSF, DISPLAY[1] * DSF), strip)
    out.paste(view, (0, 0))
    out.save(OUT / f"phone-{name}.png")
    raw.unlink()


async def main(port=8097, mode="ok"):
    env = dict(os.environ, YW_MOCK=mode, PORT=str(port),
               YW_TODAY=FIXTURE_DAY.isoformat(), YW_NOW=FIXTURE_NOW.isoformat())
    srv = subprocess.Popen([sys.executable, "-m", "tests.mock_server"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3.5)
    try:
        async with async_playwright() as pw:
            b = await pw.chromium.launch(executable_path=_chromium_path())
            ctx = await b.new_context(
                viewport={"width": VIEW[0], "height": VIEW[1]},
                device_scale_factor=DSF, color_scheme="dark", locale=LOCALE)
            pg = await ctx.new_page()
            await pg.clock.set_fixed_time(FIXTURE_NOW)
            await pg.goto(f"http://127.0.0.1:{port}/weather/",
                          wait_until="networkidle")
            await pg.add_style_tag(content=INSETS)
            if not await pg.evaluate(AS_INSTALLED):
                raise SystemExit("index.html has no rules for the installed app "
                                 "any more; AS_INSTALLED is out of date")
            await pg.wait_for_timeout(900)

            # The **canvas** colour, and getting this wrong is how this file
            # spent a round agreeing with a broken theory. It read `.edge-bot`
            # first, on the belief that iOS tints the strip by sampling a fixed
            # element at that edge -- which is what it does behind Safari's
            # toolbar, and is not what happens here. There is no tinting: the
            # gradient on `html` is sized to the viewport and simply stops, and
            # those 59 points are the root's `background-color`, painted onto
            # the canvas like any other unpainted region of the window.
            #
            # `.edge-bot` and the canvas were the same colour every night and
            # different every day, so the shot was right half the time and
            # confidently wrong the other half. Ask the element that paints it.
            strip = _rgb(await pg.evaluate(
                "getComputedStyle(document.documentElement).backgroundColor"))

            await shoot(pg, "forecast-top", strip)
            await pg.evaluate("window.scrollTo(0, 1e6)")
            await pg.wait_for_timeout(400)
            await shoot(pg, "forecast-bottom", strip)

            await pg.evaluate("window.scrollTo(0, 0)")
            await pg.locator(".day").first.click()
            await pg.wait_for_timeout(700)
            await shoot(pg, "sheet-mid", strip)
            # The large detent has to be driven, not scrolled to: at the medium
            # one the body does not scroll at all, so a scrollTop write is a
            # no-op and the "bottom" shot silently duplicates the "top" one.
            await pg.evaluate("goDetent('large')")
            await pg.wait_for_timeout(700)
            await shoot(pg, "sheet-large", strip)
            await pg.evaluate(
                "document.getElementById('screen-body').scrollTop = 1e6")
            await pg.wait_for_timeout(400)
            await shoot(pg, "sheet-bottom", strip)

            await ctx.close()
            await b.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("phone-*.png"))))
    if README:
        _readme()


def _readme():
    """Half the phone's pixels and 256 colours: the README shows them at 295pt
    wide, and a 3x full-colour PNG is 600 kB of page weight for a picture of a
    forecast."""
    docs = pathlib.Path(__file__).resolve().parent.parent / "docs"
    for src, dst in (("forecast-top", "forecast"), ("sheet-mid", "day")):
        im = Image.open(OUT / f"phone-{src}.png").convert("RGB")
        im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
        im.quantize(256, method=Image.Quantize.MEDIANCUT).save(
            docs / f"{dst}.png", optimize=True)
    print("wrote docs/forecast.png, docs/day.png")


if __name__ == "__main__":
    asyncio.run(main())
