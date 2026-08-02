# Working on CM Weather

You are probably an AI session that has never seen this repository before, and
you will probably be gone in an hour. This file is what one session leaves the
next. Read it before you touch anything; it is short on purpose.

`README.md` explains the system to a human. `DECISIONS.md` explains *why* it is
the way it is, and is the file that actually matters — the code has already been
lost once and rebuilt from documentation in an afternoon.

---

## First, always

```bash
make check          # ruff + the whole suite, no network. Must be green.
```

If `make check` is red when you arrive, fix that before anything else, and
suspect the harness before the code (see the bottom of `DECISIONS.md`).

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
13. **The gesture is not ours to implement, only to opt into.** iOS runs its own
   edge-swipe-back in a standalone PWA and it cannot be switched off. A screen
   is pushed onto `history` so the platform gesture dismisses it; a hand-rolled
   swipe would run *alongside* the system one and navigate back twice. There is
   a test asserting `app.js` registers no touch handlers.

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
- iOS Safari ignores `overflow:hidden` on `<body>`.
- **iOS 26 Safari ignores `theme-color`.** It tints the strips above and below
  the page by sampling the `background-color` of a `position: fixed` element at
  that edge — a *colour*, so gradients are invisible to it, and only at first
  render, so JavaScript cannot change it. `.edge-top` / `.edge-bot` exist
  solely to be sampled; keep them fixed, full width, ≥6px, no border.
- **Measure the thing that leaves the machine.** The byte-budget test read
  `len(response.content)`; the test client decompresses transparently, so it
  measured the file on disk and reported 82 kB for a 26 kB load.
- **A skipped test is not a passing test, and one that has never run may be
  asserting nonsense.** Four tests waited on a fixture for weeks; the moment one
  existed, one of them failed on an assertion that could never have been true.
  CI now fails on any skip outside the browser suite.
- **A parser that under-reads never fails.** An always-`None` field looks like
  a field the source does not publish; a series of zeros looks like a dry day.
  Ask "what does the page contain that we never touch" — `test_mapping.py`.
- **The values that matter are the typed ones.** A dry hour is the text `0`, a
  wet hour is `<precipitation-value value="3.7">`. Read the text and exactly the
  interesting cells go missing.
- **Nearest is not the same question as covering.** `series.covering` picks the
  best match for comparison; `series.align_to_now` picks the entry that contains
  the moment. Conflating them dropped the current hour from the strip.
- **A fixture captured at a convenient moment is a test that agrees with you.**
  The Gismeteo headline read the strip's *first* column — midnight — instead of
  the observed hour, for weeks. The fixture was recorded at 00:54, the one hour
  when those coincide, so the test asserted the bug. There is now a test that
  rejects such a fixture.
- **Comparing two times without saying which clock they are on** is how most of
  the above start. Pass the timezone; never assume UTC.
- **A test asserting a meta tag changed is not a test that the browser acted on
  it.** Two `theme-color` fixes passed their tests and did nothing on a phone.
  When a fix is green and the screenshot is unchanged, you are measuring the
  wrong end of the mechanism.
- **A row can be missing a half.** Gismeteo's pressure row has a max for ten
  days and a min for eight. Read flat, every day after the gap takes its
  neighbour's number — in range, right unit, wrong day. Count containers.
- **A page can be named for something it is not.** Gismeteo's `/3-days/` is a
  *ten*-day grid at four columns a day. It was left unparsed for a while on the
  strength of its URL. Open the page before believing its name.
- **A source's absence can be a reading.** Gismeteo prints «штиль» and no number
  at all for a calm part of the day. Gating the cell on the speed dropped the
  one value that said something.
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
