# Working on CM Weather

You are probably an AI session that has never seen this repository before, and
you will probably be gone in an hour. This file is what one session leaves the
next, whichever agent that turns out to be. Read it before you touch anything;
it is short on purpose.

`README.md` explains the system to a human. `DECISIONS.md` explains *why* it is
the way it is, and is the file that actually matters — the code has already been
lost once and rebuilt from documentation in an afternoon.

---

## Who decides what

The owner directs; the session builds. Within a task you have a free hand, and
this is where it ends. Ask the owner first before you:

- add a build step, or a fetch from any third party. Not a dependency any
  more: the owner has said new ones are welcome when they earn their place
  (2026-10-02). What has not changed is the reason. It goes beside the pin in
  `requirements.txt` or `requirements-dev.txt`, it is argued in `DECISIONS.md`
  (§39 has the ones so far), and the version arrives through `make lock`;
- raise a budget — the byte budget in `tests/test_api.py`, or any other number
  a test holds something below;
- change an invariant, here or where `tests/test_invariants.py` enforces it;
- touch `.github/`, which is the deploy gate (next section).

Everything else is yours to decide, provided the reason ends up where the next
session will find it.

## `master` is production

A green push to `master` is live within minutes: CI tests it and publishes the
image, and the server deploys it behind a health check that rolls itself back
(`DEPLOY.md`). There is no staging, and no "fixed in the next commit" that does
not ship the broken one first. Work in progress goes on a branch, which gets the
same CI and deploys nothing.

---

## Where this was left

**One test is a known failure, and it is marked as one rather than skipped.**

```
XFAIL tests/test_invariants.py::TestTheFixturesAreOneRecording::test_the_sources_overlap
  - the Yandex and Gismeteo fixtures are two recordings with no date in common ...
```

Meteofor had an outage on 15 August 2026 -- every page answering 200 with
`widget-no-data` where the forecast belongs (§32) -- so the Yandex fixtures were
re-recorded that day and the Gismeteo ones could not be. Two browser tests that
depend on both describing the same day skip themselves and point at this one.

It is `xfail(strict=True)` because a plain failure now blocks every deploy, and
a skip is invisible. Strict is the half that keeps it honest: the day the
fixtures agree, the test passes, the unexpected pass fails the suite, and the
marker has to come off.

**The fix is one command, once the source is back:**

```bash
make fixtures-gm && make fixtures && make check
```

The suite then fails on purpose, with `XPASS(strict)`, until the marker is
deleted. That failure is the sign the fix worked.

Check first that it is back -- `fixtures-gm` refuses to record a placeholder and
will tell you if it is still down. If everything else is green and that line
says XFAIL, nothing is broken; do not go looking.

---

## First, always

```bash
make check              # ruff + the whole suite, no network
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

Before you finish, see **Done means** at the bottom of this file.

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
6. **A retry is for refusals, not for parse failures.** `Blocked` and `httpx2`
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
make status                 # is it reachable at all? the server's verdict, per source
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

Fix the highest tier that can be fixed, and check
`sources.<source>.fallback_profile` in the `/api/weather` payload afterwards
(`make canary` reads it): all-tier-3 means the ground moved and the parser is
one edit from confidently reading the wrong cell.

**Classify a cell by what it contains, never by its position or its class
name.** `ru_text.classify` is the pattern. Position-based parsing is what makes
a redesign catastrophic instead of routine.

---

## Traps that have already cost real time

One line each; the story is behind the reference — a § of `DECISIONS.md`,
*Traps* for the list that closes it, or the file named.

- Yandex's minus is **U+2212**, not a hyphen; invisible in summer. *Traps*
- `(\d{1,2})\s*°` reads `743°` as `+43`; every numeric pattern has a `(?<![\d.,])` guard. *Traps*
- The forecast block renders **twice**; a naive walk finds 20 days. *Traps*
- `"безоблачно"` contains `"облачно"`; substring order is load-bearing. *Traps*
- An `<svg>` with no width or height is 300×150 and wrecks the layout. *Traps*
- **`position: fixed` on `<body>` shrinks a standalone iOS app to the small viewport**; lock with `html.locked`. §26
- **Re-date a workaround before you inherit it**: a comment about a browser bug says *when*. §26
- **A symptom in the stylesheet can have its cause in the JavaScript.** §26
- **`overflow-x: auto` turns the other axis's `visible` into `auto`**; state both. `tests/test_ui.py`
- **A line box is taller than its font size**: 11.5px text, a 16.7px line, a 15px row. `static/index.html`
- **A test that hardcodes fixture values tests the weather**; cross-check another way. `_row_pairs`, `tests/test_gismeteo.py`
- **A missing icon does not look missing**: the wrong one is drawn instead. `tests/test_invariants.py`
- **Look at it**: two tabs named one date differently, with 400-odd tests green. §23
- **A stub whose signature drifts fails like a broken upstream.** *Traps*
- **Fixtures from two recordings are not a smaller reality.** *Traps*
- **An outage answers 200**, and a recorder must never overwrite its own evidence. §32
- **A periodic animation has a divisibility constraint**; express it in the code. §30
- **A pinned clock is an instant, not a time of day.** §28
- **When a source drops a data blob, only one symptom looks broken.** §27
- **iOS tints the blur under an installed app's clock with `html`'s background colour.** §41
- **`overscroll-behavior` on `<body>` does nothing in WebKit**; it is read off `<html>`. §41
- **The curve's points are the only `<circle>`s in the chart, and a test counts them**; draw any other dot as a path. §43

---

## Shape of the code

```
app/main.py        routes, CSP, static      — the only module importing fastapi
app/http.py        builds clients           — the only module constructing httpx2
app/routing.py     which host, which egress — Gismeteo's IP block lives here
app/service.py     orchestration            — assembly, divergence, day/night
app/extract.py     Yandex parser            \
app/sources/*.py   per-source fetch+parse   |  no I/O in extract/ru_text/
app/ru_text.py     Russian, content shapes  |  validation/sun — pure functions,
app/validation.py  the five contract layers |  which is why they are cheap to
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

Every string the interface says is a `STR` entry in `app.js` with both
languages, Russian first; `t(key)` picks one. A browser test fails if an
English screen shows a Cyrillic letter anywhere but the switch back to Russian
(`DECISIONS.md` §36).

Tests are named after the behaviour they protect, and carry the story of the
bug that motivated them. `test_bezoblachno_is_not_read_as_cloudy` is worth
more than `test_icon_mapping`.

Add a `DECISIONS.md` entry when you make a choice a future session might
reasonably undo. Include what would reverse it — a decision without its
reversal condition becomes dogma, and there is a test for that too.

---

## Done means

- `make check` is green, with no new skips. A known failure is marked
  `xfail(strict=True)` with its reason; it is never skipped.
- Anything visible has been looked at with `python -m tools.phone`, and the
  pictures read rather than merely produced.
- The docs name what you added: modules in `README.md`'s layout, `make` targets
  in the Makefile's header, diagnostics in `tools/README.md`, settings in
  `.env.example`. `tests/test_docs.py` fails rather than let them drift.
- A choice a future session might reasonably undo has a `DECISIONS.md` entry,
  with what would reverse it.
- No budget was raised and no invariant changed without the owner's yes.
