# Working on CM Weather

You are probably an AI session that has never seen this repository before, and
you will probably be gone in an hour. This file is what one session leaves the
next. Read it before you touch anything; it is short on purpose.

`README.md` explains the system to a human. `DECISIONS.md` explains *why* it is
the way it is, and is the file that actually matters — the code has already been
lost once and rebuilt from documentation in an afternoon.

---

## Where this was left

**One test is red on purpose, and it is not a bug.**

```
FAILED tests/test_invariants.py::TestTheFixturesAreOneRecording::test_the_sources_overlap
  Yandex spans ..2026-08-16 and Gismeteo ..2026-08-14, with no date in common
```

Meteofor had an outage on 15 August 2026 -- every page answering 200 with
`widget-no-data` where the forecast belongs (§32) -- so the Yandex fixtures were
re-recorded that day and the Gismeteo ones could not be. Two browser tests that
depend on both describing the same day skip themselves and point at this one, so
it is the only noise.

**The fix is one command, once the source is back:**

```bash
make fixtures-gm && make fixtures && make check
```

Check first that it is back -- `fixtures-gm` now refuses to record a placeholder
and will tell you if it is still down. If everything else is green and only that
line is red, nothing is broken; do not go looking.

---

## First, always

```bash
make check          # ruff + the whole suite, no network
python -m tools.phone   # render at the phone's real 393x852 view
```

**If the complaint came from the phone, do not form a theory.** This is the
single most expensive habit this project has, and it has now cost three
separate multi-day hunts. Two tools exist so that it does not cost a fourth:

- `tools/phone.py` renders at the device's geometry with the safe-area insets
  injected, and pins its clock to the fixtures so a September session gets the
  same picture as an August one.
- `static/debug.js` runs the whole battery **on the device** -- viewport units,
  canvas colours, the close button, the top of the screen, and both sheet
  animations sampled frame by frame -- and prints a verdict per line. Tap the
  build hash in the footer. One screenshot replaces four rounds of "try this
  and tell me what you see".

The second one earned its keep the first time it was asked. It found the
sheet's entrance losing its first 230ms to a `visibility` transition (§31) --
a defect reported for weeks, mis-fixed twice, and invisible to five hundred
passing tests because every computed style was correct and only the frames were
missing. **If you find yourself explaining why the device is wrong, add a probe
to `debug.js` instead and ask for one screenshot.**

Note what the harness cannot referee: Chromium reports `env(safe-area-inset-*)`
as 0 and `svh == lvh`, where the phone says 59/34 and 793/852. Anything that
depends on those is unprovable here.

If `make check` is red when you arrive, read the section above first, then fix
it, and suspect the harness before the code (see the bottom of `DECISIONS.md`).

Before you finish: `make check` again, and update `README.md` if you added a
module, a `make` target, a diagnostic, or an environment variable. Tests enforce
all four — `tests/test_docs.py` will fail rather than let the docs drift.

---

## The one idea

This app parses three weather sites and shows the numbers to one person on one
phone. **The danger is never that it breaks loudly.** It is that a redesign
moves a cell, the parser reads a pressure value into a temperature field, and
the app says +743° — or a plausible +55 after some well-meaning clamp — and it
is believed.

Everything below follows from that.

---

## Invariants — do not violate these

1. **Values are dropped, never clamped.** Every rejection path sets the field to
   `None`. A blank with a note beside it is information; a plausible wrong
   number is a lie the user will act on.
2. **Page identity is checked before any number is believed.** `check_identity`
   in `extract.py` and `sources/gismeteo.py`. Yandex will happily serve a
   beautifully parseable forecast for the wrong city. Never weaken this, and
   never "try another source until one agrees".
3. **Never use `?geoid=`.** It is vestigial and ignored. Address by slug or
   lat/lon. There is a test.
4. **No third-party subresource, ever.** No CDN font, no hosted JS, no map tile.
   `Content-Security-Policy: default-src 'self'` with no allowlist, and the
   service worker returns 403 for cross-origin. The whole point of the project
   is that the phone talks only to this server.
5. **Nothing from the phone goes upstream.** Not `Accept-Language`, not
   `User-Agent`, not the timezone. Only rounded coordinates, and only on demand.
6. **A retry is for refusals, not for parse failures.** `Blocked` and `httpx`
   errors earn another route; `ParseError` stops the search. Getting this
   backwards hides a broken parser behind a timeout.
7. **No build step.** No bundler, no framework, no `node_modules`. Three static
   files a browser reads directly. This is the single biggest reason the thing
   still runs in five years.
8. **Every cache and queue is bounded.** Keys here come from URLs — city
   searches and GPS fixes — so the key space is effectively infinite and an
   unbounded store is a set that only ever grows.
9. **A value that must exist in two languages is read back, never restated.**
   CSS owns `--hour-w` and `--push-ms`; JS reads them back with `cssVar`. This
   has bitten four times; the test derives the list of properties from the code
   rather than naming them, and asserts the *agreement*, not either value.
10. **Two fields that describe the same instant must agree.** The dangerous
   failure here is never a bad value — it is a right value describing the wrong
   thing: the wrong city, the wrong hour, the wrong cell. Bounds-checking sees
   none of them. `validation.check_coherence` is the layer for it; add to it
   when you add a field that has a sibling.
11. **A parser given the same bytes returns the same answer forever.** No
   function reads the clock; a date is passed in as `today=`, and the clock may
   only be that argument's default. The page's stated date beats our guess
   about what day it is.
12. **Ask what a value *is*, never where it sits.** Row 0 is not today, column
   0 is not now, and the *n*th typed element is not the *n*th day. Every one of
   those has shipped here as a bug, and none of them produced a wrong-looking
   number — they produced a right number attached to the wrong thing. On the
   front end this means a date, not an index; in a parser it means a container,
   not an offset into a flat list.
13. **The horizontal gesture is not ours to implement, only to opt into.** iOS
   runs its own edge-swipe-back in a standalone PWA and it cannot be switched
   off. A screen is pushed onto `history` so the platform gesture dismisses it;
   a hand-rolled *horizontal* swipe would run alongside the system one and
   navigate back twice. Narrowed from "no touch handlers at all" when the day
   detail became a bottom sheet: a **vertical** drag does not collide, and it
   is the one thing that makes a sheet feel like an object. Dismissal still
   goes through `history.back()` from every path, which is what keeps the
   system swipe working. Tested as: no pointer/gesture listeners, `clientX`
   read only to hand a sideways gesture back, `history.back()` present.

---

## When a source changes its HTML

This will happen. It is the expected case, not the emergency.

```bash
make routes-remote          # is it reachable at all, and from where?
make fixtures               # re-record Yandex from the box that fetches
make fixtures-gm            # re-record all four Gismeteo/Meteofor pages
make check                  # the diff tells you exactly what moved
```

Extraction is a **three-tier ladder**, and each tier fails independently:

| tier | mechanism | breaks when |
|---|---|---|
| 1 `NAMED` | embedded state JSON | their internal data contract changes |
| 2 `LABELLED` | accessibility prose, labelled cells | the information architecture changes |
| 3 `SHAPE` | content-classified DOM | the CSS class names change |

Fix the highest tier that can be fixed, and check `health.fallback_profile`
afterwards: all-tier-3 means the ground moved and the parser is one edit from
confidently reading the wrong cell.

**Classify a cell by what it contains, never by its position or its class
name.** `ru_text.classify` is the pattern. Position-based parsing is what makes
a redesign catastrophic instead of routine.

---

## Traps that have already cost real time

Full list at the bottom of `DECISIONS.md`. The ones that recur:

- Yandex renders minus as **U+2212**, not a hyphen. Invisible in summer.
- `(\d{1,2})\s*°` matches `743°` as `+43`. Every numeric pattern carries a
  `(?<![\d.,])` guard.
- The forecast block renders **twice**; a naive walk gives 20 days.
- `"безоблачно"` contains `"облачно"`. Substring order is load-bearing.
- An `<svg>` with no width/height defaults to 300×150 and wrecks the layout.
- **`position: fixed` on `<body>` collapses a standalone iOS web app to the
  *small* viewport.** `innerHeight` drops by the status-bar inset — 852 to 793
  — for as long as the lock is on, and every consequence looks like a CSS bug:
  an unpaintable band along the bottom of the phone, content cut at the fold,
  `dvh` disagreeing with `lvh`. It also relayouts the whole document, which
  ate the sheet's opening animation. **Six deploys were spent on the symptoms
  before anyone suspected the scroll lock.** Lock with
  `html.locked{overflow:hidden;overscroll-behavior:none}` — honoured since iOS
  16.3, changes no geometry, keeps the scroll position for free. There are
  invariant tests; `static/debug.js` reports `inner при открытом` on the device.
- **Re-date a workaround before you inherit it.** The pin above was justified
  by "iOS ignores `overflow:hidden` on `<body>`", which was true until iOS 16.3
  and then wrong for three years. Nothing recorded when it was written or
  against which version. If a comment explains a browser bug, it should say
  *when*.
- **A symptom in the stylesheet can have its cause in the JavaScript.** Every
  hypothesis for six deploys was a CSS hypothesis, because the symptom was a
  band of colour. The cause was a class name added in `openScreen`.
- **`overflow-x: auto` does not leave the other axis alone.** When one axis is
  not `visible`, a `visible` on the other computes to `auto`. Two pixels of
  overflow made the hourly strip its own vertical scroller, so dragging the
  curve moved the widget instead of the screen. State both axes.
- **A line box is taller than its font size.** 11.5px text at the body's 1.45
  line-height is 16.7px in a 15px-high row. That was the two pixels.
- **A test that hardcodes values from a fixture is a test of the weather.**
  Every `make fixtures-gm` broke it, and the only repair was to paste in the new
  numbers -- which would "fix" a parser that had started reading the wrong row
  just as readily. Cross-check against the same page by a *different* mechanism
  instead: `_row_pairs` in `test_gismeteo.py` regexes the raw HTML where the
  parser uses XPath.
- **A missing icon does not look missing.** `cloudy-night` did not exist, so
  `nightify` handed back the day form and the night rows drew a sun at three in
  the morning. Nothing was absent on screen; the wrong thing was present. There
  is now a test walking every emittable key against the shell's `<symbol>`s.
- **Backticks in a `git commit -m "..."` are command substitution.** One such
  message ran `make fixtures-gm`, whose `>` redirect truncated a fixture to zero
  bytes before curl failed. Commit messages go in a file and through `-F`.
- **Look at it.** The day labels disagreed between tabs — «Завтра» on one, «вс»
  on the other, same date — and 400-odd tests were green. It was found by
  putting two screenshots side by side. `python -m tools.shoot`, or drive the
  mock server with Playwright; a screen this app renders is cheap to look at and
  the failures that matter here are the ones that look fine.
- **A stub whose signature drifts fails like a broken upstream.** The mock's
  Gismeteo fetcher never grew the real one's `timeout=` keyword, so the tab was
  silently disabled in every screenshot and browser test.
- **Fixtures from two recordings are not a smaller reality.** Pairing a landing
  page from one day with an hourly strip from another makes the coherence check
  report the app as broken, correctly.
- **An outage answers 200.** Meteofor spent 15 August 2026 serving every page
  with the right title, the right city, and `<div class="widget
  widget-no-data">Данные уточняются` where the forecast goes. `curl -f` was
  happy, so `make fixtures-gm` overwrote four good fixtures with four empty
  ones, and the parser then refused them exactly as designed — which made a
  source outage look like a parser bug, having just destroyed the recording
  that would have proved otherwise. `fixtures-gm` now downloads to a scratch
  directory and refuses to install a page with no `data-row=` grid. **Before
  believing a source is broken, check whether it is merely empty**, and never
  let a recorder write over its own evidence.
- **A periodic animation has a divisibility constraint.** A pattern that
  repeats every P pixels may only be translated by a whole multiple of P. The
  rain's 46px gradient period was 190px measured *vertically* while the
  animation moved 168px, so it jumped 22px eleven hundred times a minute and
  had done since it was written. Express the constraint in the code — one
  custom property for both the repeat and the travel — or it is being met by
  luck. §30.
- **A pinned clock is an instant, not a time of day.** `set_fixed_time` takes
  UTC; the front end asks what day it is *in the city*. `FIXTURE_NOW` held the
  city's 22:00 wall clock, so the browser ran three hours ahead of the server's
  `YW_TODAY` — across midnight. All 66 browser tests stayed green, because the
  app was consistent with itself: it just rendered yesterday at the top of the
  ten-day list and «сейчас» at 01:00, in every screenshot the harness made.
  Both ends were pinned; they were pinned to different moments.
- **When a source drops a data blob, only one symptom looks broken.** Gismeteo's
  `weather.cw` went away and the report was "the icon is a question mark". Also
  true, unreported: the temperature had fallen to tier 3 — found by document
  position — and five fields went blank, which silently removed the whole
  «Подробности» card, because a block that renders nothing looks exactly like a
  source that never had those fields. Check `health.fallback_profile` and the
  *shape* of the screen, not just the thing that was noticed. §27.

---

## Shape of the code

```
app/main.py        routes, CSP, static      — the only module importing fastapi
app/http.py        builds clients           — the only module constructing httpx
app/routing.py     which host, which egress — Gismeteo's IP block lives here
app/service.py     orchestration            — assembly, divergence, day/night
app/extract.py     Yandex parser            \
app/sources/*.py   per-source fetch+parse   |  no I/O in extract/ru_text/
app/ru_text.py     Russian, content shapes  |  validation/sun — pure functions,
app/validation.py  the four contract layers |  which is why they are cheap to
app/sun.py         solar position           /  test exhaustively
```

`tests/test_invariants.py` enforces those arrows, and the invariants above.
If you need to break a rule, change it in that file deliberately and say why in
`DECISIONS.md` — do not work around it.

`tests/test_ladder.py` is the one to read if you are here because a site
redesigned: it strips each extraction tier out of the real captured HTML and
asserts the tier below answers **with the same numbers**.

`make canary` asks the live site the one question the suite cannot: has an
upstream moved since the fixtures were recorded? It runs weekly in CI.

---

## House style

Comments explain **why**, never what. A comment restating the code is noise; a
comment recording the failure that produced the line is the most valuable text
in the file. Match the surrounding tone — it is discursive on purpose, because
the next reader is a stranger.

Tests are named after the behaviour they protect, and carry the story of the
bug that motivated them. `test_bezoblachno_is_not_read_as_cloudy` is worth
more than `test_icon_mapping`.

Add a `DECISIONS.md` entry when you make a choice a future session might
reasonably undo. Include what would reverse it — a decision without its
reversal condition becomes dogma, and there is a test for that too.
