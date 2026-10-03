# Decisions

Why things are the way they are. Written because this project has already
proved the point once: its predecessor lost its entire codebase to an ephemeral
container and was rebuilt in an afternoon from surviving documentation. The
~2,000 lines of code were the cheap part. The reasoning was not.

Each entry says what was decided, why, and **what would change it** — because a
decision recorded without its reversal condition becomes dogma.

---

## Index

★ marks the seven to read if you read nothing else.

| § | decision | in one line |
|---|---|---|
| 1 | [Scrape first; the official free key is not implemented](#1-scrape-first-the-official-free-key-is-not-implemented) | A key covering today and tomorrow can only be a gap-filler, and gap-fillers rot. |
| 2 ★ | [Page identity is checked before any number is believed](#2-page-identity-is-checked-before-any-number-is-believed) | Yandex will serve a perfect forecast for the wrong city; a page must name the place asked for. |
| 3 | [Values are dropped, never clamped](#3-values-are-dropped-never-clamped) | A clamped 743 is a plausible +55; a blank with a note beside it is information. |
| 4 | [Divergence records but no longer decides](#4-divergence-records-but-no-longer-decides) | With three readings on screen, disagreement is shown and recorded, not adjudicated. |
| 5 | [Geolocation is a button, never automatic](#5-geolocation-is-a-button-never-automatic) | A first screen that needs a permission is useless until granted; coordinates are rounded twice. |
| 6 | [Gismeteo has partial city coverage, and does not fake the rest](#6-gismeteo-has-partial-city-coverage-and-does-not-fake-the-rest) | No id, no tab — never a neighbouring city's numbers under this one's name. |
| 7 ★ | [Gismeteo blocks by IP — so we knock on a different door, not from a different address](#7-gismeteo-blocks-by-ip--so-we-knock-on-a-different-door-not-from-a-different-address) | Enumerate the origin's other hostnames before shopping for an address of your own. |
| 8 | [The hero has no card](#8-the-hero-has-no-card) | Four lines in a box read as empty; on a sky they read as calm. |
| 9 | [The place name is the control](#9-the-place-name-is-the-control) | One tappable title in place of four affordances for a choice made twice a month. |
| 10 | [The service-worker version is derived, not typed](#10-the-service-worker-version-is-derived-not-typed) | Hashed from the shell, because the ninth manual bump is the one you forget. |
| 11 | [Everything on the sky uses fixed-alpha translucency, not palette colours](#11-everything-on-the-sky-uses-fixed-alpha-translucency-not-palette-colours) | Translucency inherits the sky's lightness, so contrast holds on every sky. |
| 12 | [A retry is for refusals, never for parse failures](#12-a-retry-is-for-refusals-never-for-parse-failures) | A refusal earns another route; a parse failure stops the search. |
| 13 | [Day or night is computed, not read and not guessed](#13-day-or-night-is-computed-not-read-and-not-guessed) | Solar position from coordinates and the clock, checked against Gismeteo's printed sunrise and sunset. |
| 14 | [iOS 26 Safari does not read `theme-color`. It samples a fixed element.](#14-ios-26-safari-does-not-read-theme-color-it-samples-a-fixed-element) | Solid strips at the edges, because Safari samples a fixed element's colour, never a gradient. |
| 15 ★ | [The page's stated date beats our clock, and the rules beat the reviewer](#15-the-pages-stated-date-beats-our-clock-and-the-rules-beat-the-reviewer) | Same bytes, same answer, forever — and the rules are tests, not comments. |
| 16 ★ | [The dangerous failure is a right value describing the wrong thing](#16-the-dangerous-failure-is-a-right-value-describing-the-wrong-thing) | Fields individually perfect and jointly nonsense; hence the coherence layer. |
| 17 | [Three bugs, one shape: the parser under-reads and nothing fails](#17-three-bugs-one-shape-the-parser-under-reads-and-nothing-fails) | Ask whether a parse is everything, not only whether it is plausible. |
| 18 | [Cheap to load, cheap to run — measured, not assumed](#18-cheap-to-load-cheap-to-run--measured-not-assumed) | Compression, a 34 MB image, a bounded cache, and the budgets as tests. |
| 19 | [The launch is one colour, from tap to loaded](#19-the-launch-is-one-colour-from-tap-to-loaded) | Three lines of critical CSS removed the white flash between splash and app. |
| 20 ★ | [The launch screen cannot be removed — and dressing it up was not worth it](#20-the-launch-screen-cannot-be-removed--and-dressing-it-up-was-not-worth-it) | Built, deployed, invisible, reverted: estimate the effect before building the mechanism. |
| 21 | [Things deliberately not built](#21-things-deliberately-not-built) | Push notifications, a widget and a build step, and why each stays unbuilt. |
| 22 | [A day is a screen you push, not a drawer you open](#22-a-day-is-a-screen-you-push-not-a-drawer-you-open) | Every screen is a history entry, so the system's own back gesture dismisses it. |
| 23 | [Each source gets the shape it is good at](#23-each-source-gets-the-shape-it-is-good-at) | Parts, curve or table, whichever the source fills — keyed by date, never by row. |
| 24 | [Prose on the wire](#24-prose-on-the-wire) | Comments ship to the phone, deliberately; the byte budget carries the bill. |
| 25 | [One request, spent because somebody tapped something](#25-one-request-spent-because-somebody-tapped-something) | The per-day page is fetched only when a day is opened, and nothing depends on it. |
| 26 ★ | [Four guesses at one band, and the measurement that ended it](#26-four-guesses-at-one-band-and-the-measurement-that-ended-it) | Six deploys of CSS theories, and the cause was the scroll lock. Get a number off the device. |
| 27 | [When the state blob went away, only the icon looked broken](#27-when-the-state-blob-went-away-only-the-icon-looked-broken) | Check the fallback profile and the shape of the screen, not only the reported symptom. |
| 28 | [A pinned clock is an instant, not a time of day](#28-a-pinned-clock-is-an-instant-not-a-time-of-day) | Both ends were pinned, to different moments; a clock pin is a UTC instant. |
| 29 | [The sky is the only thing on this screen that is not information](#29-the-sky-is-the-only-thing-on-this-screen-that-is-not-information) | Motion carries intensity, under three rules: compositor-only, seamless, clear of the text. |
| 30 | [A loop that jerks is arithmetic, not taste](#30-a-loop-that-jerks-is-arithmetic-not-taste) | A pattern repeating every P pixels may only move by multiples of P. |
| 31 | [`visibility` in a transition flips at the midpoint](#31-visibility-in-a-transition-flips-at-the-midpoint) | A discrete property flips halfway: instant on the way in, delayed on the way out. |
| 32 ★ | [A source outage answers 200, and the recorder ate the evidence](#32-a-source-outage-answers-200-and-the-recorder-ate-the-evidence) | Download, inspect, then install — a recorder never overwrites its own evidence. |
| 33 | [A push to master is the deploy, and nothing here can reach the server](#33-a-push-to-master-is-the-deploy-and-nothing-here-can-reach-the-server) | The suite is the gate, the server pulls, and nothing in this repo can reach it. |
| 34 | [Fixtures are what the parsers read, not what the sites sent](#34-fixtures-are-what-the-parsers-read-not-what-the-sites-sent) | Test input is trimmed to what the code reads; a public repository does not redistribute pages. |
| 35 | [The install offer is a banner in the forecast, with one button](#35-the-install-offer-is-a-banner-in-the-forecast-with-one-button) | Shown only where an install can happen, below the hourly card; the button does the one thing it can, and the × means never. |
| 36 | [English is a reading of the sources, not a translation of them](#36-english-is-a-reading-of-the-sources-not-a-translation-of-them) | Chosen on the device, never sent upstream; a condition is named from its icon, and prose of no known shape is left out. |
| 37 | [A public instance gets a budget for strangers](#37-a-public-instance-gets-a-budget-for-strangers) | Places outside the registry and search misses draw on one bucket; registry cities never do. |
| 38 | [`/api/health` is retired, and the forecast is the diagnostic](#38-apihealth-is-retired-and-the-forecast-is-the-diagnostic) | It told strangers what the server tells itself, and nothing outside this repository read it; it answers 410 now. |
| 39 | [Dependencies earn their place, and the locks say what ships](#39-dependencies-earn-their-place-and-the-locks-say-what-ships) | New ones for the tests; both locks hashed and written by `make lock`; Dependabot for the actions; httpx2 in place of httpx for the upstreams, as a change of its own. |
| 40 | [The sky is the same in both appearances; light mode is the surfaces](#40-the-sky-is-the-same-in-both-appearances-light-mode-is-the-surfaces) | A pale sky put the hero at 1.4–3.1:1; one sky, white on it, and light cards and sheets. |
| 41 | [The installed app's canvas is the top of the sky](#41-the-installed-apps-canvas-is-the-top-of-the-sky) | iOS tints the blur under a home-screen app's clock with the canvas colour; there it is `--sky1`, dimmed with the scrim, and the page does not bounce. |
| 42 | [The image is started locked down; known vulnerabilities are an alarm, not a gate](#42-the-image-is-started-locked-down-known-vulnerabilities-are-an-alarm-not-a-gate) | CI runs the image the way the server should and waits for its HEALTHCHECK; a weekly audit reports and never blocks a deploy. |
| 43 | [Rain falls from the curve](#43-rain-falls-from-the-curve) | Streaks under the line where it rains, dots where it snows: density is how hard, opacity how sure, and a dry day draws nothing. |

---

## 1. Scrape first; the official free key is not implemented

`yandex.ru/pogoda/b2b/smarthome` issues a permanent free non-commercial key
(GraphQL, `X-Yandex-Weather-Key`, costs a phone number). It is **not used**, and
`config.py` no longer reads it.

**Why.** It covers today and tomorrow only — no 10-day, no Meteum nowcast — so
it can only ever be a gap-filler. And a gap-filler is a path that runs rarely,
which means it rots quietly and fails on the day you finally need it. The
fragile path should be the one exercised daily.

**What would change it.** If it were added, it should be a *fourth tab* in
`service.ORDER`, visible and exercised, not a silent fallback.

---

## 2. Page identity is checked before any number is believed

`check_identity` in `extract.py` and `gismeteo.py`. A response is rejected if it
does not name the place we asked for.

**Why.** This is the failure that nothing downstream can catch. `/pogoda`
geolocates the requesting IP when its addressing hints go stale and returns a
beautifully-formed, entirely parseable forecast **for the wrong city** — the
research pass asked for Yoshkar-Ola and got Columbus, Ohio. The numbers are
internally consistent, in range, smooth, and completely wrong. There is a test
that swaps the city name in the real fixture, confirms it still parses
perfectly, and asserts we reject it anyway.

Related: **never use `?geoid=`**. It is vestigial; `geoid=41` *is* Yoshkar-Ola
and is ignored. Address by slug or lat/lon.

**What would change it.** Nothing. This one is load-bearing.

---

## 3. Values are dropped, never clamped

Every rejection path sets the field to `None`.

**Why.** A clamped 743 becomes a plausible +55. A blank with a note beside it is
information; a plausible wrong number is a lie you will act on.

---

## 4. Divergence records but no longer decides

*Reversed 2026-07-31, when the third source arrived.*

The two-source design made Open-Meteo a referee: a >15 °C disagreement caused
the app to reject Yandex and silently substitute Open-Meteo.

**Why it was right.** With only one number ever on screen, the user had no way
to judge it.

**Why it was reversed.** With three temperatures visible on the tabs, the user
can see the disagreement directly — and an app that silently swaps an explicitly
chosen source is doing the thing this codebase avoids everywhere else. The
deltas are still computed (`service._record_divergence`) and land in
`health.divergence_c`; they inform rather than decide.

**Per-source validation was untouched**, because it answers a different
question. "Two sources disagree" is a judgement call. "This source returned 743
in a temperature field" is a broken parser.

**What would change it.** Dropping back to fewer visible sources. The honesty of
"no verdict" depends entirely on the user being able to see all three.

---

## 5. Geolocation is a button, never automatic

**Why.** Two reasons, and the second decided it. Home-screen web apps on iOS are
reported not to persist the location permission across refreshes, so an app that
asks on launch becomes an app that prompts on every launch. And an app whose
first screen needs a permission is useless until you grant one — Yoshkar-Ola
loads instantly and the button is there when you want it.

Coordinates are rounded to 2 decimals (~1.1 km) on the device *and* again on the
server, and resolved by asking Yandex for that lat/lon and reading the city name
off the response — so no fourth-party geocoder ever sees them.

---

## 6. Gismeteo has partial city coverage, and does not fake the rest

`gismeteo.ru/robots.txt` disallows `/*?*` — every URL with a query string — and
`/ajax`. The only permitted address is `/weather-<slug>-<id>/`, and that numeric
id is not derivable from a name or a coordinate. Six cities ship with ids
harvested from their own catalogue; `GISMETEO_IDS` adds more by hand.

For a searched or GPS city with no id, the tab is **disabled with a reason**. It
does **not** substitute a nearby city we do have an id for.

**Why.** Showing Cheboksary's numbers under a heading reading Yoshkar-Ola is
precisely the wrong-city failure §2 exists to prevent — self-inflicted this
time, which would be worse.

---

## 7. Gismeteo blocks by IP — so we knock on a different door, not from a different address

*Established empirically 2026-07-31 after two wrong theories, then solved the
same day by a third party noticing something none of the theories predicted.*

### What is actually true

Gismeteo returns 403 to the Latvian VPS and 200 to a Russian residential
address. **Every** variant fails from Latvia and **every** variant succeeds from
Russia — plain `curl`, stdlib `urllib`, HTTP/1.1, HTTP/2, minimal headers, full
Chrome headers. `tools/gm-probe.sh` bisects all four axes and shows every row
flipping together.

Two theories were wrong first: that it was the header set (a Chrome UA sent
without the `Sec-Fetch-*` family, which real Chrome never does), and that it was
HTTP/2 fingerprinting. Both changes were kept — they are more correct — but
neither was the cause. The tell was that plain `curl` sent *fewer* headers than
the app and still got 200; when adding correctness does not help, the variable
is not in the request.

**Client-side fetching does not work either**, and would be wrong if it did:
cross-origin reads need CORS headers Gismeteo has no reason to send, and it
would put the phone's IP in front of the one site demonstrably interested in
where requests come from — inverting the project's premise.

### The fix, and the lesson in it

`meteofor.lv` serves the identical page: same numeric city id (`11975`), same
`/weather-<slug>-<id>/` shape, same `window.M.state`, same values to the
minute — hourly series, gust series, precipitation, sunrise, moon phase, all
matching — and it answers a Latvian address, because serving Latvia is what it
is *for*. Meteofor is Gismeteo's export brand; `gismeteo.com` itself returns
METEOFOR-titled pages.

So `GISMETEO_HOSTS` ships as `gismeteo.ru,meteofor.lv/ru`, the fetch walks the
list, and the block is simply gone. No proxy, no tunnel, no third party in the
path, no new failure mode.

The lesson is worth more than the fix, because the fix was found by looking and
the search had been pointed the other way for a day: **when an origin refuses
your address, enumerate the origin's other addresses before you go shopping for
your own.** A block is a property of one hostname's edge, not of the company.
Changing where you knock costs one ordinary HTTPS request to a host that wants
your traffic. Changing where you knock *from* costs a dependency on a stranger's
machine, a slower hop, and a new thing that breaks at 3am. The instinct was
backwards, and it was backwards because proxies feel like the "real" engineering
answer.

### The proxy path is still wired, deliberately

`GISMETEO_PROXY` takes a **comma-separated list**, tried in order, and combined
with the host list: every host is attempted on each egress route. It stays for
three reasons — the mirror could be blocked tomorrow, someone may want to appear
in-country on purpose (see below), and it costs nothing when empty.

Three properties make an unreliable proxy usable rather than a liability:

- **Ordering is intent, not preference.** A configured proxy is tried *before*
  direct. You may have set it because Gismeteo blocks this box; you may equally
  have set it because you want to appear in-country regardless, and silently
  preferring direct because it happened to answer would undo that.
- **A budget** (`GISMETEO_ROUTE_BUDGET_S`, 20 s). All three sources are fetched
  concurrently, so Gismeteo's slowest route sets the latency for the whole
  response. Eight dead proxies at 12 s each is not a degraded tab, it is a
  broken app. Bounded, the failure degrades to "tab disabled with a reason".
- **Stickiness.** The route that worked is tried first next time, so the steady
  state is one request even with a long list.

**On free public proxies specifically**, since the question comes up: they are
safer than they look and less useful than they look. Safer, because every
upstream here is HTTPS — the proxy is asked to `CONNECT` and then relays bytes
it cannot read, with certificates still verified against the origin by us. A
hostile hop can drop or stall the connection; it cannot hand us a forged
forecast, which is the only failure that would matter. Less useful, because the
addresses on public lists are precisely the population an anti-bot system
blocks first, and individual entries die in hours. `make routes` tests
candidates against the real page before any of them is committed to an env var.

### What would change it

If both hosts are blocked: a machine on a Russian residential connection will
do, even one behind CGNAT with no inbound, because it only has to dial *out*. A
persistent reverse tunnel plus `tinyproxy` makes it one entry in
`GISMETEO_PROXY`. That tunnel remains the right answer for a *different*
problem regardless — pointing `UPSTREAM_PROXY` at it routes the Yandex fetch
through Russia and converts §2's wrong-city risk from "defended against" to
"eliminated".

Neither host is trusted more than the other, and neither is trusted at all: both
go through `check_identity` on every fetch. A mirror that quietly served a
different town would be rejected, not believed — which is what makes adding
hosts a cheap decision rather than a scary one.

---

## 8. The hero has no card

**Why.** The complaint was that it took a lot of space for little value. The
answer was not to add data — it was to remove the container. A box with four
lines in it reads as *empty*; the same four lines on a sky read as *calm*. Same
information, same pixels, opposite feeling. It is why Apple Weather's hero is
not in a container either.

The sky is animated and condition-aware. `prefers-reduced-motion` disables the
motion and keeps the colour.

---

## 9. The place name is the control

There is no hamburger and no toolbar. Tapping the city name opens a sheet
holding search, geolocation and saved cities.

**Why.** The top bar had four affordances — city name, a boxed GPS button, a
boxed search button, and a scrolling row of city bubbles — for a choice made
about twice a month. A hamburger would have been an improvement but still the
wrong label: a menu icon promises a menu of *things*, and there is only one
thing in it. The place name is already the largest element up there and says
what it does without a caption.

---

## 10. The service-worker version is derived, not typed

`app/version.py` hashes the shell files; `/sw.js` substitutes it on serve.

**Why.** It was bumped by hand eight times in one afternoon. The ninth is the
one you forget, and the symptom is a redesign that is invisible to every device
that already installed the app while being perfect in a fresh browser. That is a
genuinely horrible bug to diagnose, and it is entirely avoidable.

---

## 11. Everything on the sky uses fixed-alpha translucency, not palette colours

The source switcher's selected pill is `rgba(255,255,255,.17)`, not a named
colour.

**Why.** It used `--card2`, a fixed dark navy. Against a deep night sky that
read clearly; against a pale overcast sky it vanished. "Which source am I
looking at" was answerable on some days and not others. Translucency inherits
the backdrop's lightness, so relative contrast stays constant — the same reason
iOS builds segmented controls this way.

The same applies to the sky variables living on `:root` rather than `body`:
custom properties do not inherit *upward*, so `html{background:var(--sky1)}`
could not see them, and iOS painted the notch, the home-indicator strip and the
overscroll bounce black.

Since §40 this covers the text on the sky too: the place, the hero, the source
strip and the footer are white at a fixed alpha in both appearances, because
the palette changes with the appearance and the sky does not.

---

## 12. A retry is for refusals, never for parse failures

When a Gismeteo fetch fails, whether to try the next route depends entirely on
*which* failure it was:

```
refused  (Blocked, or any httpx2 error) -> another route may work. Retry.
parsed and wrong  (ParseError)          -> every route returns this page. Stop.
```

**Why.** The tempting implementation retries everything, and it appears to work
for a long time. Then the parser breaks, and eight routes each spend twelve
seconds fetching the same unparseable page, and the tab goes dark with
`timeout` written on it. You would spend the morning on the network.

The wrong-city case is the sharpest version. `check_identity` raises
`ParseError`, so it stops on the first route — and it must, because "try
another mirror until one agrees with us" is exactly the plausible wrong fix,
and it would defeat §2 by construction.

This is why `Blocked` exists as its own exception. A 403 arrives as
`httpx2.HTTPStatusError` and classifies itself, but a challenge page arrives as
**200 with a captcha in the body**, and calling that a parse failure would stop
the search on the first host that refuses politely.

---

## 13. Day or night is computed, not read and not guessed

The app drew a full midday sun at 01:25. Two of the three sources have no
day/night information at all — Gismeteo's condition comes from a tooltip that
says «Безоблачно» and stops there, Open-Meteo's WMO codes have no such concept
— so both shipped a daytime icon around the clock. Only Yandex knew, from the
`_d`/`_n` suffix on its icon codes.

It is now decided once, in `service._sunlit`, from the place's coordinates and
the clock, using the USNO low-precision solar position (`sun.py`).

**Why not read it from the page.** Gismeteo's markup does carry it. Reading it
would fix one source, leave the other two wrong, and add a per-source detail
that rots at their next redesign. The icon would also depend on which tab you
had selected, which is precisely the kind of inconsistency three visible
sources are supposed to expose rather than create.

**Why not a fixed evening window.** Because that is what one path already did —
`hour >= 21 or hour < 5` — and it is right in Yoshkar-Ola in August by
coincidence. Sunrise there moves from 03:44 in June to 08:37 in December and
sunset from 21:19 to 15:56, so the window puts a sun in the sky at 07:00 in
January and a moon at 20:00 in July. North of the Arctic Circle it is not
merely inaccurate but categorically wrong.

Arithmetic costs no fetch, no table, and no new dependency, and it is checkable
against a published almanac — the tests assert against **Gismeteo's own printed
sunrise and sunset for the exact page the bug was reported from**, 03:48 and
19:59, and match to the minute. Agreeing with the source is a stronger claim
than "looks dark to me".

Applied on **serve**, not on build, and idempotent: a payload cached at 19:50
and handed out from the stale grace at 22:00 would otherwise still be sunny.
Daily icons are left alone, because a day's summary is a day.

**What would change it.** Nothing about the sun. If a fourth source arrived
with real per-hour day/night data, it would still be normalised through here —
one answer, or the tabs disagree about what time it is.

---

## 14. iOS 26 Safari does not read `theme-color`. It samples a fixed element.

*Reported three times. The first two fixes were aimed at a mechanism that no
longer exists, and both of them passed their tests.*

### The symptom

A strip above the page and a strip below it, each some colour with no obvious
relationship to the page between them — sometimes lighter, sometimes darker,
changing with scroll position. On a phone it reads as a rendering fault rather
than as a background.

### What is actually going on

Safari 26 **ignores `<meta name="theme-color">`**. The tag still parses; the
value is discarded. Instead, the strips behind the status bar and the toolbar
take their colour from a **`position: fixed` element at that edge of the
viewport**, falling back to `<body>`. Two details in that sentence did all the
damage:

- **It reads `background-color`.** A gradient is a `background-image` and is
  invisible to the sampler. This page's sky is *nothing but* a gradient, so it
  contributed nothing at either edge and Safari picked something arbitrary.
- **It samples at first render** and does not re-sample when JavaScript changes
  a colour — which is exactly what the previous fix did, on `openSheet`.

Corroborated across three independent write-ups, all agreeing on the mechanism
and roughly on the geometry (full width, ~6px minimum height, within a few
pixels of the edge, `position: fixed` — `sticky` may not count, and a
`border-bottom` on the element outranks its `background-color`).

### The fix

Two strips, `.edge-top` and `.edge-bot`: fixed, full width, 10px tall, no
border, each a **solid colour** equal to the sky gradient at exactly that point
— `--sky1` at the top, `--sky3` at the bottom (`--bg` until §40, when the
sheets' surface and the foot of the sky stopped being one variable). They are invisible on the page,
because each is painted the colour of the thing directly behind it: measured,
the adjacent pixels differ by at most 3/255 in both schemes and at any scroll
position. They exist purely to be read.

With the sheet open they dim with everything else, in CSS, on
`html:has(body.locked)` — because a rule the stylesheet applies has a chance of
being picked up, and a value JavaScript writes into a meta tag has none.

The canvas keeps the same gradient it was given (`--skygrad` on `html`, fixed
to the viewport). That was never the wrong thing — it is what iOS paints into
the notch, the home-indicator strip and the overscroll bounce in the installed
app, where the page *does* own those pixels. It simply was not the thing Safari
reads, which is what the previous entry here got wrong.

### The lesson, which cost three rounds

**A test that asserts a meta tag changed is not a test that the browser acted
on it.** Both earlier attempts were green. The first checked that
`theme-color`'s content string updated; it did. The second checked that the
canvas gradient and the sky gradient matched; they did. Neither had anything to
do with the pixels the user was looking at, because neither had checked what
the browser reads. When a fix passes and the screenshot is unchanged, the test
is measuring the wrong end of the mechanism — go and find out what the platform
actually does before writing a third one.

`theme-color` is still set. It is correct for the installed PWA, for Android,
and for Safari before 26, and it costs a line.

**What would change it.** WebKit restoring `theme-color`, or documenting the
sampling rules properly. The strips are cheap and harmless either way; if they
ever became visible, that is a bug and there is a test asserting their colour
equals the sky variable at that edge.

---

## 15. The page's stated date beats our clock, and the rules beat the reviewer

*Two decisions from the same afternoon, and the same underlying bet: what
survives a hundred sessions is not care, it is enforcement.*

### The stated date wins

A day card reading «Сегодня, 31 июля» carries a relative word and an absolute
date, and they can disagree — the fetch was before midnight and the read is
after, the cache is serving something from yesterday, or a fixture recorded on
the 31st is parsed on the 1st. The absolute one wins. `today` is our guess
about when we are reading; «31 июля» is the page telling us what it is about.

**Why it matters more than it sounds.** Read the other way round, every date in
the series shifts by one and the tenth day falls off the end. Nothing errors.
The suite passes all afternoon and goes red at midnight UTC, and the session
that inherits it spends its hour on a bug that no longer reproduces. There is
now a test that parses the fixture as if it were five different days, including
a different year, and demands identical output.

The general form: **a parser given the same bytes must return the same answer
forever.** `tests/test_invariants.py` enforces it structurally — the clock may
appear only as the default of a `today=` argument, never inside a function.

### The rules are executable

`AGENTS.md` states the invariants for whoever arrives next. `test_invariants.py`
*enforces* them: the import graph (adapters are leaves, only `http.py` builds a
client, only `main.py` imports FastAPI, the pure modules import no network
library and read no clock), and a set of source-level assertions about mistakes
that have actually been made here — no `?geoid=`, no degree pattern without its
lookbehind guard, U+2212 still first in the minus table, no fixed-hour day/night
window, no constant restated across CSS and JS.

**Why grep-in-a-test, which is not elegant.** Because the failure mode this
project actually faces is not a careless author; it is a well-meaning stranger
with an hour, no context, and a plausible reason to undo something hard-won. A
comment does not stop that. A red test does, and it costs ten lines. Each rule
names the failure it prevents, so the person it blocks can read *why* before
deciding it is in the way.

They were mutation-tested when written: five deliberate violations, five
distinct failures, one green run after reverting. A rule that cannot fail is
decoration.

**What would change it.** A rule that starts firing on legitimate work should be
changed *here*, deliberately, not worked around. That is the whole protocol.

---

## 16. The dangerous failure is a right value describing the wrong thing

*Found by the user, three times over, before any check here noticed.*

The headline condition on the Gismeteo tab came from `_first_tooltip` — the
first icon tooltip on the page, which is the strip's **leftmost column**, i.e.
midnight. The temperature beside it came from the state blob's `cw`, observed
at 23:00. Twenty-three hours apart, on screen, next to each other, for weeks.

Every layer of validation passed, and correctly: both values were in range, in
the right unit, in a well-formed series, and continuous with the last fetch.
The fields were individually perfect and jointly nonsense.

### Why nothing caught it

Three reasons, and the second is the one worth remembering.

1. **The fixture was captured at 00:54** — the one hour of the day when the
   leftmost column *is* roughly now. Every assertion about the headline was
   written against that file, so the test suite did not merely miss the bug, it
   **encoded** it: `assert current.condition == "Малооблачно, туман"` was
   asserting the midnight column's text.
2. **Nothing cross-checked two fields of the same source.** All four validation
   layers are vertical — one value, or one series. Divergence is horizontal but
   *between* sources. There was no check anywhere that two fields describing the
   same instant should agree, which is precisely where this class of failure
   lives. It is the same shape as §2's wrong-city page: not a bad value, a
   **right value describing the wrong thing**. Bounds-checking cannot see either.
3. **The `/hourly/` page shipped with no fixture.** Its tests are skipped. That
   change did not cause the bug — it *exposed* it, by moving the hourly series
   onto real hours so the two finally disagreed on screen.

### What changed

**The parser.** The condition is now looked up in the hourly series by the
**real epoch** the page ships in `<time-value timestamp>`, matched against
`cw.date`, the observation time. Not by label — deriving absolute times from
"HH:MM" means guessing which side of midnight each falls on, and the answer
differs between the landing page and `/hourly/`. The headline and the "now"
column are now the same fact by construction rather than two guesses that
agreed on the day the fixture was recorded.

**A fifth validation layer: internal coherence.** Does this source agree with
*itself*? The current temperature against the hourly column covering the same
instant; the current condition against the same column's icon family; the
current temperature against today's own published min/max. It warns rather than
drops, because a disagreement is evidence about our parser and not about the
sky (§4), and the warning lands in `/api/health` (amended 2026-10-02: in that
source's `warnings`, which ride in every payload and show under «Что не так»;
`/api/health` is retired, §38).

**A guard on the fixture itself.** A test now fails if the captured page's
leftmost column *is* the observed hour — because such a fixture cannot tell a
correct parser from one that reads column zero. If `make fixtures-gm` is ever
run at half past midnight, it says so.

**The front end stopped lying too.** It labelled `hourly[0]` "сейчас"
unconditionally. A source may hand back a strip starting at midnight or at the
next whole hour; now a column is labelled "сейчас" only when its hour matches
the clock **in the city being displayed**, which is the whole point of an app
you use to look up somewhere else.

### The lesson

Two of them, and the second cost this fix ten minutes of its own medicine.

**A fixture recorded at a convenient moment is a test that agrees with you.**
The bug needed a page where "first column" and "now" differ. Capturing at 00:54
guaranteed they did not.

**Comparing two times without saying which clock they are on is how all of
these start.** The first draft of `_hour_covering` compared a city-local hour
label against a UTC hour and was wrong by the offset — the same species of
mistake as the bug it was written to catch, caught by its own tests within the
minute. The timezone is now a required parameter.

**What would change it.** If Gismeteo ever ships a usable current-conditions
enumeration (`iconWeather` looks like one, but a single sample is not a table),
the condition could move to tier 1 and stop depending on the strip at all.

---

## 17. Three bugs, one shape: the parser under-reads and nothing fails

*All three found by a human comparing two screens. None caught by 337 tests.*

Reported in one sitting, and worth keeping together because they are the same
bug three times:

1. **The headline condition described midnight**, not the observed hour
   (§16, fixed) — and the coherence check written to catch it then **re-derived
   "which hour is now" differently from the parser**, so the app reported itself
   broken on every fetch. The parser matched real timestamps, the validator
   matched hour labels with a wraparound; on a 23:00 reading against a
   00:00..21:00 strip they answered 21:00 and 00:00. `DECISIONS.md` already
   carried an entry about a *constant* written twice. This was the same failure
   in **logic**, which is harder to see and no less certain to diverge. Both now
   call `series.covering`, and nothing else may answer that question.

2. **Hourly precipitation was never read at all.** The page publishes an
   «Осадки в жидком эквиваленте» row; every hour shipped `precip_mm=None`. And
   the reason it stayed invisible after the row *was* parsed is the good part:
   a dry hour is the plain text `0`, a wet hour is
   `<precipitation-value value="3.7">`. Reading `text_content()` gives a tidy
   series of zeros with holes exactly where the rain is. **Every value that
   matters is the one that goes missing**, and the result reads downstream as a
   dry day.

3. **The strip opened on the next hour.** Each source begins its series
   somewhere different and each is sensible on its own page — Gismeteo's
   `/hourly/` starts at the next whole hour (its page shows current conditions
   in a separate card), Open-Meteo returns the whole calendar day, Yandex starts
   now. Rendered identically, the same strip meant three different things per
   tab. `series.align_to_now` normalises: drop what has happened, and if nothing
   covers the present hour, put the observation at its head — the same reading
   already in the hero, moved into the series it belongs to.

### The shape

**Nothing failed.** No exception, no dropped value, no warning. A field that is
always `None` is indistinguishable from a field the source does not publish. A
series of zeros is indistinguishable from a dry day. A strip starting at 12:00
looks like a strip. The parser quietly reads less than the page contains and
the app quietly shows less than it knows — and every existing check passes,
because every check asks "is what we returned plausible" and none asks "is it
everything".

### What now asks the other question

`tests/test_mapping.py` inverts the direction:

- **Every typed element on the page is either read or declared.** `<speed-value>`,
  `<pressure-value>` and `<snow-value>` are listed as deliberate omissions with
  reasons; anything else appearing fails the build. `precipitation-value` sat
  unread for a fortnight and would have failed this on day one.
- **A modelled field the page carries may not be uniformly empty.** All-`None`
  precipitation is now a failure rather than a shrug.
- **Two independent readings of the same fact must agree** — millimetres from
  the precipitation row against the icon from the column tooltip.
- **The whole condition vocabulary is audited**, not spot-checked: every tooltip
  string in every fixture must map to an icon, and precipitation must beat
  cloudiness in all of them. A redesign that introduces new phrasing fails here
  rather than rendering the `unknown` glyph on a phone.

### The fixture, when it finally arrived

Recorded the same day, and it settled all of it:

- **The `/hourly/` page does start at the next whole hour.** Observation 12:00,
  strip beginning 13:00. The inference was right and `align_to_now` is doing
  real work rather than defending against an imagined case.
- **The mirror parses at tier 1** — `temp_c`, humidity, pressure and wind all
  from `window.M.state`, hourly and daily at tier 2, coordinates present. The
  claim in §7 is now checked against real bytes instead of two screenshots.
- **Nothing on any of the three pages is unmapped or unread.** Every condition
  phrase resolves to an icon; every typed element is read or declared.

And one thing nobody had noticed: `test_the_state_blob_is_there_too` asserted
`provenance["current"] == NAMED`, and provenance has no `"current"` key. It
could never have passed. It had been skipped since the day it was written, so
nothing ever said so.

**A skipped test is not a passing test.** It is an unexamined claim wearing a
green tick, and the longer it waits the more confidently it is cited. CI now
fails on any skip outside the browser suite, because everything else has its
inputs committed and therefore has no excuse not to run.

**What would change it.** Nothing about the approach. But every one of these was
reported by a person looking at two screens, which is a slow and expensive test
suite that happens to be extremely good. The nearest automated equivalent is
`make canary`, and extending it from "which tier answered" to "which fields came
back empty" would have caught the precipitation bug without anyone squinting.

---

## 18. Cheap to load, cheap to run — measured, not assumed

Every number below was measured before and after. The point of writing them
down is that the next session can tell whether it made things worse.

### Bytes on the wire

Nothing was compressed. Not by the app, and not by nginx-proxy — the `/weather/`
location block has no `gzip` directive, so every byte went out raw. One line of
middleware:

```
/api/weather   22.8 kB -> 2.5 kB   (89%; it is a very repetitive document)
index.html     32.2 kB -> 10.9 kB  (66%)
app.js         29.2 kB -> 11.3 kB  (61%)
sw.js           3.5 kB -> 1.7 kB   (52%)
cold load     ~103 kB  -> ~26 kB
```

There is no BREACH concern, for the usual reason: the responses contain no
secret to extract — no session, no CSRF token, no auth material anywhere.

Static assets now also state how long they may be kept. The shell revalidates
every time, deliberately: it is unhashed, and a cached copy that never checks
is a device pinned to an old build for ever — the exact failure the derived
service-worker version exists to prevent, reintroduced one layer up.
Revalidation costs a 304. Icons are content rather than code and get a week.

### The image

`uvicorn[standard]` was pulling **19 MB** of packages unreachable from this
app: uvloop (14 MB), websockets, watchfiles and PyYAML. There are no
websockets, nothing reloads in production, no YAML is ever parsed, and uvloop
optimises an event loop that spends its life waiting on three upstream HTTP
requests. Shipped dependencies went **53 MB → 34 MB**. `httptools` stayed: 2 MB,
and it does help.

The build is now two-stage. Today that saves little, because the only thing
left behind is pip's working state. It is worth the four lines for the day a
dependency stops shipping a wheel and needs a compiler — which then lands in
the builder and never reaches the image facing the internet. Structuring for
that in advance is free; retrofitting it during an outage is not.

**Considered and rejected:** dropping FastAPI for bare Starlette to shed
pydantic (~12 MB). The app uses dataclasses and never touches a pydantic model,
so it is dead weight — but it is dead weight in exchange for the most
conventional web framework in the language, and legibility to the next session
is worth more here than twelve megabytes. Alpine was rejected too: lxml has no
musl wheels, so it would mean compiling lxml on every build.

### Memory

**The cache was unbounded.** Keyed by place slug, and a slug is whatever the URL
can express: every city the search can name, plus one per distinct GPS fix —
coordinates rounded to two decimals, so about a kilometre apart, which over a
country is a great many. Nothing ever removed anything, so each one left a whole
`Weather` object resident for the life of the process. Not a leak in the classic
sense, since every entry was once legitimately wanted; just a set that only ever
grew, on a box with a fixed amount of memory. It is now bounded — past-grace
entries first, then oldest — with `CACHE_MAX_ENTRIES` at 64, which is generous
beside the handful of cities anyone uses.

`--limit-concurrency 64` bounds the other direction: each in-flight request can
hold three parsed lxml trees, and refusing the 65th with a 503 is a better
failure than the OOM killer taking the container down for everyone.

### The budget is a test

`TestItIsCheapToLoad` asserts the compressed cold load stays under a byte
budget and the shell source under another, each set just above the measurement
of its day, so the test that fails is the one where somebody adds a charting
library. They started at 32 kB and 80 kB; they are 49,000 and 131,000 bytes
now, and every raise in between is argued for where it was made (§24, and the
test's own docstring), which is the only way a budget stays one.

*Amended 2026-10-02: one budget now, the compressed one, at 64 kB. The fourth
raise had left 43 bytes, so the next change to the sky would have had to stop
and ask; it still fails on a charting library. The uncompressed budget went:
it measured comments more than code, and comments are the house style (§24).
The owner's call, §42.*

Two of these tests were wrong when first written, in the way this file keeps
recording. The byte budget read `len(response.content)` — and the test client
decompresses transparently, so it measured the file on disk and reported 82 kB
for a 26 kB load; `Content-Length` is the real figure. And the cache-eviction
test found that at `grace_s=0` the new implementation evicted the entry it had
just written, because the cutoff read the clock a second time. **Measure the
thing that leaves the machine, not the thing you have in hand.**

**What would change it.** A second user. Everything here is sized for one phone
and one small VPS; none of it would survive contact with real traffic, and all
of it would be the wrong thing to optimise for it.

---

## 19. The launch is one colour, from tap to loaded

Reported as "black splash, then a white flash, then the app". All three frames
were ours, and all three disagreed:

| moment | what decided it | what it was |
|---|---|---|
| launch screen | manifest `background_color` | `#0b1220` — reads as black |
| before the CSS parses | nothing | the WebView's own **white** |
| loaded | `--sky1` | `#0d1630` |

iOS builds the standalone launch screen from `background_color`, so the splash
was a near-black of our own choosing. Then the browser had 30 kB of stylesheet
to read before it knew what colour the page was, and until it did it painted
its default. Three transitions where there should be none.

**The fix is three lines at the very top of `<head>`** — a stylesheet
containing nothing but `html{background:…}` (and, until §40, its light-mode
counterpart).
There is nothing to parse, so it governs the first paint; the full sky replaces
it a few milliseconds later by source order. The manifest colour was changed to
match.

The colour is now written in three places, which is exactly the duplication
this file has an entry against — but nothing can read all three, since one is
consumed by iOS at install time, one by the parser at first paint, and one by
the cascade afterwards. So it follows the established rule instead: **a test
asserts the three agree**, and the failure message says which one drifted.

**The skeleton became furniture.** It was the hero at 30% opacity showing
"—°", which reads as a broken app rather than a loading one. It is now the
*shape* of the answer: icon, temperature, condition, source strip, two cards.
Deliberately no fake numbers anywhere — the same rule the parsers follow about
plausible wrong values, applied to the loading state. A test asserts the
skeleton contains no digits, and the loading state is announced for screen
readers since the shapes are `aria-hidden`.

**Known imperfection, since fixed.** A manifest carries one `background_color`,
and iOS uses it whatever the appearance setting, so light mode stepped once,
from a dark splash to a lighter sky; per-scheme manifest colours, which iOS
does not honour, were the only fix in sight. §40 removed the step instead:
the sky is the same in both appearances, so one colour is right for both.

**What would change it.** Making the first paint the *last* sky rather than the
default — the app would open on the exact gradient it closed with. That needs
JavaScript running before first paint, which means an inline script, which the
CSP forbids (`script-src 'self'`, no `unsafe-inline`). Doable with a
server-computed hash in the CSP header; not worth it for the remaining few
milliseconds.

---

## 20. The launch screen cannot be removed — and dressing it up was not worth it

*Built, deployed, looked at, reverted the same day. The reversal is the useful
part, so it is recorded rather than quietly dropped.*

**It is not removable and not shortenable.** On iOS and Android alike the launch
screen is part of the operating system's app-launch model — the same screen a
native app gets. `web.dev` documents the mechanism and offers no opt-out; a 2026
survey of iOS PWA limitations calls the approach "rudimentary and hacky" and
likewise describes no way to skip it. That part is settled and worth not
re-researching.

### What was tried

`apple-touch-startup-image`, so iOS would hold the exact gradient the first
frame paints instead of a flat rectangle. The images were generated at request
time by a dependency-free PNG encoder — `zlib` is stdlib, and since every
scanline of a vertical gradient is one colour the Up filter reduced a
9-megapixel image to 12 kB. It worked exactly as designed: 180 lines,
22 `<link>` tags, a test that decoded the PNG and checked its top pixel.

### Why it went

Deployed, and **the difference was invisible**. Which is obvious in hindsight
and should have been obvious in advance: by then the manifest colour was already
`#0d1630`, and the startup image is a gradient from `#0d1630` to `#0a1020`
across the top 62% of the screen. A handful of RGB steps, spread over a phone
screen, for a fifth of a second. There was never much there to see.

Against that: 180 lines, ~400 bytes of gzipped `<link>` tags on every load, and
a maintenance tail — Apple ships new screen sizes every autumn, and each one
silently falls back until someone adds a row.

**The version that mattered was the cheap one.** Six lines — three of critical
CSS at the top of `<head>` and a manifest colour to match — removed the white
flash, which was a real, visible defect. The elaborate follow-up addressed a
difference nobody could perceive.

There was one case where it was not cosmetic: a manifest carries a single
`background_color`, so in light mode a dark splash preceded a light app, and
startup images can vary by scheme. That case is gone — since §40 light mode
opens on the same navy sky as dark — so the reason to bring it back went with
it. `git show 97e2817` still has all of it.

### The lesson, which is the reason this entry exists

**Estimate the size of the effect before building the mechanism.** The
arithmetic here — two colours, thirteen RGB steps apart, over a fifth of a
second — takes a minute and would have killed the idea before the PNG encoder
existed. Instead it got built, tested, documented, deployed and removed, and
the only thing that survived is this paragraph.

Kept from the attempt: the fade (`.wrap`, 0.22 s, three lines) and the test that
walks the sheet's ancestors for `transform`, `filter`, `perspective` and
`backdrop-filter` — a transformed ancestor becomes the containing block for
`position: fixed` children, which broke the place sheet for 220 ms and is worth
guarding permanently.

**What would change it.** Apple offering any control over the launch screen.
(Regular light-mode use was the other, until §40 gave light mode the same
first frame as dark.)

---

## 21. Things deliberately not built

**Push notifications.** Possible without a Developer account (standard Web Push,
your own VAPID keypair), but every push on iOS must show a visible notification,
and a service worker that takes one without displaying it loses its subscription
after three strikes. Since that is the only background-refresh mechanism iOS
offers, dropping push means the app updates only when opened — which is why the
timestamp is prominent.

**A home-screen widget.** WidgetKit needs a signed native bundle; there is no
web API. The workaround is a Scriptable script against the same `/api/weather`.

**A build step.** No bundler, no framework, no `node_modules`. Three static
files that a browser reads directly. This is the single biggest contributor to
the project still working in five years.

---

## 22. A day is a screen you push, not a drawer you open

The ten-day list needed somewhere to put a day. So did the city picker, whose
bottom sheet had been the weakest thing in the app for a while — the rounded
panel, the dimmed backdrop and the grab handle are three separate promises of a
drag gesture that was never implemented, and a drawer says *small choice, then
back to what you were doing*, which a day's detail is not.

Both are now the same primitive: a full-screen panel that slides in from the
right, pushed with `history.pushState`.

**Why history, specifically.** In a standalone iOS PWA the edge-swipe-back
gesture is wired to browser history. A screen that exists as a history entry is
therefore dismissable by the system gesture, with the system's own transition,
for free. A screen that exists as a CSS class is not, and no amount of touch
handling fixes that — a hand-rolled swipe runs *alongside* the OS gesture rather
than instead of it, and the app navigates back twice. Ionic have carried that
bug across several major versions; there is no way to opt out of the platform
gesture. So the rule is: the gesture is not ours to implement, only to opt into.
There is a test asserting `app.js` registers no touch handlers.

**Why opaque and full-screen.** Not laziness about the parallax iOS does under a
push — it is what makes this safe. A transformed ancestor becomes the containing
block for `position: fixed` descendants, which is exactly how a 4px rise on
`.wrap` broke the old sheet (§14). Sliding the page under the screen would put
that trap straight back. Being opaque also retires the whole scrim problem: the
strips iOS paints behind its own bars cannot be tinted from inside the page, and
covering them is not a smaller fix than the three we tried, it is a different
shape of one.

**Depth is one.** Neither screen leads anywhere else. A stack that can only ever
hold one thing should say so rather than carry bookkeeping for a case that does
not exist.

**What would change it:** a third screen that genuinely opens from a second, or
a Safari that lets a page suppress the platform back gesture.

---

## 23. Each source gets the shape it is good at

The day-detail screen shows different things on different tabs, and that is the
design rather than an unfinished part of it.

Яндекс publishes four named parts of a day and no per-day metrics. Gismeteo
publishes fifteen metric rows and no parts. Open-Meteo publishes an hour at a
time for ten days and no summary of any of it. The obvious design — one table,
a row per field — would be two-thirds blank on any given tab, and a blank cell
in a table reads as *missing data* rather than as "this source does not work
that way".

So each tab renders in the idiom its source actually fills: parts of day for
Яндекс, a metrics table for Gismeteo, an hourly curve for Open-Meteo. Switching
tabs changes the shape of the screen, which is honest about what the three
sources are.

The corollary is that the screen is keyed by **date**, never by row index. The
three do not agree on where their ten days start, and an index would quietly
show you a different day when you switched source. That is not hypothetical: it
shipped in the day *labels* — 2 August read «Завтра» on one tab and «вс» on
another — and was caught by putting two screenshots side by side, not by a test.
There is a test now.

**What would change it:** a source that starts publishing the others' shapes, at
which point the divergence stops being informative.

**Postscript, one day later.** Gismeteo's `/3-days/` page turned out to be a
*ten*-day grid at four columns a day, carrying the same fifteen metric rows per
part of day. So Gismeteo now publishes parts too, and the rule became simpler
rather than more complicated: lead with parts wherever a source has them, then
the hourly curve, then the metric table — ordered by how much of the day each
block answers at once. The two sources still disagree about what a part *is*
(Yandex prints morning first and means the following night; Gismeteo prints
night first and means the one that starts the day), and that disagreement is
preserved rather than normalised. See §22's note on reordering.

---

## 24. Prose on the wire

The byte budget went from 32 kB to 39 kB in one sitting, and roughly half of the
increase is comments.

This codebase writes long explanatory comments on purpose — the paragraph
recording the failure that produced a line is the most valuable text in the
repository, and `app.js` ships to a phone with all of it intact. Stripping
comments at serve time was considered and rejected: a remover that mangles one
regular-expression literal is a silent, catastrophic failure, and it would be a
build step in everything but name (§21).

So the trade is made deliberately: 37 kB fetched once and then held by the
service worker indefinitely, in exchange for a front end the next session can
actually read. The budget test carries the arithmetic so that the *next*
increase has to be argued for too.

**What would change it:** a cold load that stops fitting in a second on a slow
connection, or evidence anyone is fetching the shell more than once.

---

## 25. One request, spent because somebody tapped something

Yandex publishes a page per day — `…/details/auto/10-day-weather/day-N` —
carrying eight three-hourly columns with feels-like, gusts, precipitation
probability and visibility. It is the deepest per-day data any source here
offers, and it is the only one that costs new requests: ten days is ten URLs
against the **one** this app spends per source per city per ten minutes.

Three options, and the middle one was chosen deliberately.

*Fetch all ten on every refresh* multiplies the app's entire upstream footprint
by eleven to deepen its thinnest tab. The README's claim — that this is a slower
request rate than one human with the page open — would simply stop being true,
and it is a claim worth keeping.

*Do not fetch it at all* was defensible right up until the day it wasn't:
Gismeteo's parts grid (§23) already gives four parts × thirteen metrics for all
ten days, and Open-Meteo gives hourly for any of them. But the Яндекс tab is the
default one, and leaving the default the thinnest is an odd place to land.

*Fetch the day somebody opened*, cache it for the usual ten minutes, and — the
part that makes it safe — **let nothing depend on it**. The screen renders from
the payload already in hand: four parts of day, the metric table, whatever slice
of the flat hourly series falls on that date. The eight-column curve replaces
that slice a moment later if the network cooperates. There is deliberately no
spinner and no skeleton, because a loading state advertises a thing that may
never arrive in place of a thing that already has. Offline, the screen is
exactly what it was before this feature existed.

The endpoint answers **204** when there is no page — a GPS fix has no
addressable slug, a date past the tenth has no page — and the client remembers
that, because it is an answer rather than a failure. A *failed* request is
forgotten instead, so opening the day again after regaining signal tries once
more.

And the URL's day number is not trusted. `day-5` is a position, and this
codebase has an invariant about positions (`AGENTS.md` 12): the offset is
computed from the date, the page is fetched, and then the page's own stated date
is held against the date that was asked for. A page describing a different day
is rejected exactly the way a page describing a different city is.

**What would change it:** Yandex publishing the same depth on the ten-day page,
or a measurement showing people open days often enough that the lazy fetches
outnumber the eager ones would have been.

---

## 26. Four guesses at one band, and the measurement that ended it

The day screen stopped 59pt above the bottom of the display. Under it sat a
strip of flat colour that read, to the person using the app, as a tab bar that
had forgotten to draw itself. It survived four fixes.

The fixes are worth listing, because they were not careless — each was a
correct statement about CSS:

1. The body had a `28px` bottom padding floor, which on a phone became 34pt of
   safe area plus a card's 10pt margin. True, and removing it was right, and
   the band did not move.
2. A fixed panel is sized by the *large* viewport, so it would sit under
   Safari's auto-hiding toolbar; therefore `height: 100dvh`. True in a browser
   tab. There is no toolbar in a standalone app, and the band got worse.
3. So `100dvh` is short by the top inset; therefore `inset: 0`, which pins to
   the real edges. Half true — and the band did not move by a single pixel,
   because `bottom: 0` resolves against exactly the same short viewport that
   `dvh` reports. Two spellings of one number.
4. Then a fourth theory about compositing, unfired.

What they have in common is that every one is true on a Mac, and the bug only
exists on a phone. Four hypotheses that predict the same rendering on the only
machine available to test them are not four hypotheses.

The end of it was a temporary block on the day screen printing `innerHeight`,
`100vh`, `100dvh`, `env()` and the rect of a bare `position: fixed; inset: 0`
box, deployed once, screenshotted once:

```
display  393x852     env t/b  59 / 34
inner    393x793     vh/dvh   852 / 793
docEl    393x793     svh/lvh  793 / 852
fix@html 0…793 h793  fix@body 0…793 h793
```

The obvious reading — and the fifth wrong fix — is that `dvh` and `bottom: 0`
are lying and `lvh` is telling the truth, so the panel should be `100lvh`. That
shipped. The band did not move, and the next screenshot said why:

```
.screen  0…852 h852        <- with 100lvh
```

with the card's colour giving way to flat `--bg` at row 793 all the same. The
box really was 852 tall. The browser agreed. **The paint stopped at 793 anyway**,
because 793 is the whole web view: a 393×793 surface at the top of an 852pt
display, with 59 points of system-drawn strip beneath it that no stylesheet can
reach. So `100lvh` did not extend the panel down the glass — it parked the last
59pt of the scroll content in a region the device never draws. That is worse
than the band, which at least was honest about being empty.

So `inset: 0`/`dvh` is right and `lvh` is a regression. The sixth attempt was
`apple-mobile-web-app-status-bar-style: black`, which should place the view
*below* the status bar so the same 793 points cover 59…852. On the device it
changed nothing — iOS reads that tag when the app is added to the home screen,
and it was already there. Re-adding might take. It was not worth asking.

### What actually fixed it, which was never a length

The band exists on the **forecast page too**, identically, and nobody has ever
noticed in months of daily use. That is the whole answer, and it took building
`tools/phone.py` — which renders into the real 393×793 view and composites the
59pt strip underneath — to see it, because on a desktop window neither page has
a band at all.

Put the two bottoms side by side and the difference is not geometry:

- The forecast page ends in a quiet line of grey text on the sky. The eye reads
  *page over*, and 90-odd points of background below it is where the page
  stopped.
- The day screen ended flush against a card's hard rounded edge. The identical
  strip read as a bar that had failed to draw itself.

So the day screen was given the forecast page's ending: a `.screenfoot` line
naming the source and the fetch time, with background running out beneath it.

That shipped, and came back as **"no difference"** — correctly, and the word
that should have been read four attempts earlier is in the original report:
*"empty space at bottom **all the time**, like a ui tab bar"*. A footer only
exists at the bottom of the scroll. Mid-scroll, which is almost always, there
is a card sliced off by the fold with flat colour under it, and a hard
horizontal edge one card wide sixty points above the glass is a bar no matter
what sits below it. Three separate attempts — padding, then a footer, then a
different footer — all fixed the *end* of a screen whose problem was its
*edge*.

The fix is to have no edge. `.screen::after` fades the last 56 points from
transparent to `--bg`, and `--bg` is exactly what iOS paints below the view, so
content dissolves into the strip's own colour at every scroll position and the
strip stops being a separate object. Two lines of CSS. The footer stays,
because it is honest information and it is what makes the *end* read as an end
once you get there.

### The actual cause, found by the sun coming up

The fade shipped and came back with a screenshot taken at 09:18 — the first one
in daylight in the entire investigation. The content faded to (11,16,32)
exactly as designed, and then the strip below it was **(25,35,59)**.

`cloudy-day` sets `--sky2: #16233d`. That is the strip.

`html`'s background is `background-size: 100% 100%, no-repeat` — the gradient
covers the viewport and stops — so the 59 points past it are painted with the
root's `background-color`, which was `var(--sky2)`. `--sky2` is the gradient's
colour at its **62% stop**, not its end. The bottom of the display had been
wearing a slice of the middle of the sky, permanently, on every screen, since
the day the gradient was put on the canvas.

It was invisible for six attempts because `clear-night` and `cloudy-night` both
set `--sky2: #0a1020`, and so does `--bg`. Every screenshot taken while chasing
this — 21:08, 21:32, 21:52 — was taken after dark, when the wrong colour and
the right colour are the same colour. The canvas had been contradicting
`.edge-bot`, which has said `--bg` the whole time, and nothing could show it
until the sun came up.

The fix is `background-color: var(--bg)`. One word. `tests/test_ui.py`
parametrises it over all seven skies for the obvious reason.

Two lessons, and they are the expensive ones:

- **A value that varies by theme must be tested against every theme.** One
  palette agreeing proves nothing, and the palette you happen to be looking at
  is the one that agrees.
- **A harness inherits the theory it was built with.** `tools/phone.py`
  composited the strip by sampling `.edge-bot`, on the belief that iOS tints it
  the way it tints Safari's toolbar. It doesn't — it is just canvas. So the
  harness agreed with the phone at night, disagreed by day, and blessed a fix
  that did nothing. It reads the root's background now. Ask what your
  reproduction *assumes* before you trust what it shows you.

The `.screen::after` fade stays: the colour match removes the band, the fade
removes the hard edge where a card meets the fold, and they are different
problems that happened to arrive together.

### The suite had an expiry date on it

Found by accident while doing the above: a container's clock jumped eleven days
mid-session and nine browser tests failed at once, none for the reason they
were written. The fixtures describe 31 July 2026, and half of what the browser
suite checks is date-relative — today's row carries a dot, «Сегодня» is a label
rather than a weekday, the day screen fetches detail for the date it shows. All
of that stopped being true on 1 August and nobody noticed, because the work
happened that week.

Both ends are now pinned to the fixtures' own day: the browser via Playwright's
`clock.set_fixed_time`, the server via `YW_TODAY`, which the mock also uses to
patch `local_now` — in `sun` **and** in `service`, since `service` binds the
name at import and patching one half leaves the two halves of the app
disagreeing about what day it is.

**What would change it:** re-recording the fixtures, which resets the clock but
does not remove the coupling. The pin is the durable half.

### It was the scroll lock. All of it.

**One line caused both the 59pt band and the broken animation, and it was not a
line about either.**

```css
body.locked { position: fixed; left: 0; right: 0; width: 100%; overflow: hidden }
```

A textbook scroll lock, applied while a sheet is open. In a standalone iOS web
app it does two things nobody looks for:

**1. It collapses the viewport to the *small* viewport.** `innerHeight` drops
from 852 to 793 — the display minus the status-bar inset — and stays there for
as long as the lock is on. Every downstream symptom followed: the band along
the bottom of the phone, content sliced off at the fold, `dvh` disagreeing with
`lvh`, a panel that "stops short of the glass". Six deploys went looking for
that in the stylesheet. It was in the scroll lock.

**2. It relayouts the entire document**, in the same task that starts the
sheet's transition — so the animation's opening frames were never painted. Two
screen recordings, decoded frame by frame, measured the sheet first appearing
at 505pt and 573pt of a travel starting at 793.

Both vanished together. The on-device diagnostic now reports:

```
экран  393×852     inner  393×852     ниже вьюпорта  0pt
```

where it used to report 793 and 59.

The lock existed on a note saying iOS ignores `overflow: hidden` on the
scrolling element. **That was true, and stopped being true in iOS 16.3.** The
note predated the fix by three years and was inherited without ever being
re-dated. The replacement is
`html.locked { overflow: hidden; overscroll-behavior: none }`: no geometry
changes, no reflow, and the scroll position survives for free because nothing
moved. `tests/test_invariants.py::TestNothingPinsTheDocument` asserts it at the
source, and the browser test asserts the strongest available form — `scrollY`
never changes at all, which the old approach could not have passed.

Sources: [Ben Frain, *Preventing body scroll for modals in
iOS*](https://benfrain.com/preventing-body-scroll-for-modals-in-ios/); [Robin
Weser, *Scroll Blocking Overlays*](https://weser.io/blog/scroll-blocking-overlays),
which dates the WebKit fix.

Three things are worth keeping from how long this took:

- **Re-date a workaround before you inherit it.** This one was correct when
  written and had been quietly wrong for years. Nothing in the codebase said
  when it was written or against which iOS.
- **A symptom in the stylesheet can have its cause in the JavaScript.** Every
  hypothesis for six deploys was a CSS hypothesis, because the symptom was a
  band of colour. The cause was a class being added by `openScreen`.
- **The harness inherits what the measurement did not explain.**
  `tools/phone.py` was built to render at 393×793 with a strip composited
  underneath — faithfully reproducing a bug whose cause it had not identified,
  and then agreeing with a fix that did nothing. It renders at 393×852 now,
  and `VIEW` carries the story.

**What would change it:** iOS below 16.3, which this project does not support.

### What the animation stall looked like, for the next time

Reported as "the pop-up animation starts from the wrong position". Two screen
recordings, decoded frame by frame, said something more specific: the sheet was
not visible at all until it had already travelled half way. First video — first
painted frame at **505pt** of a journey that starts at 793. Second — **573pt**.
Both times it then slid the remainder normally. Dismissal did the mirror image,
jumping 135pt in one frame before it began to move. Frames were duplicated
throughout: roughly 30fps, not 60.

That is not a wrong start position. It is a **main thread too busy to paint**,
and the culprit was three lines away from the transition:

```js
goDetent('mid');                        // starts the animation
document.querySelector('.wrap').inert = true;
document.body.style.top = `-${scrollY}px`;
document.body.classList.add('locked');  // body: static -> fixed
```

Switching `<body>` to `position: fixed` relayouts the entire document, and the
document here is a ten-day forecast. It happened in the same task that started
the sheet's transition, so WebKit went off to reflow the page while the
animation was supposed to be painting its opening frames. `closeScreen` did the
same to the exit with `window.scrollTo`.

The pin was there on a note saying iOS ignores `overflow: hidden` on the
scrolling element. **That was true, and stopped being true in iOS 16.3**, when
WebKit fixed it; this phone is on 26. So the lock is now
`html.locked{overflow:hidden;overscroll-behavior:none}` — no geometry changes,
no reflow, and the scroll position survives for free because nothing moved. The
test asserts the strongest form of that: `scrollY` never changes at all, which
the old approach could not have passed.

Sources: [Ben Frain, *Preventing body scroll for modals in
iOS*](https://benfrain.com/preventing-body-scroll-for-modals-in-ios/); [Robin
Weser, *Scroll Blocking Overlays*](https://weser.io/blog/scroll-blocking-overlays),
which dates the WebKit fix.

**Re-date a workaround before you inherit it.** This one was correct when it
was written and had been quietly wrong for three years.

**What would change it:** needing to support iOS below 16.3, which this project
does not.

### `static/debug.js`, and why a diagnostic beats another guess

Six deploys were spent on a bug that only exists on one phone, and every one of
them ended by asking its owner to look at something and describe it. That loop
does not converge: a desktop browser cannot see the defect, and nobody can
measure a 16ms frame gap by eye.

So the app now carries a diagnostic. Tap the build hash in the footer and it
runs the whole battery once — environment and viewport units, the canvas/sheet/
strip colours, the sheet's geometry, the close button's circle and *ink*, and
both animations sampled every frame — then prints a verdict per line. One
screenshot answers what would otherwise be four rounds of correspondence.

Two design points earn their keep:

- **It measures frame pacing, not just position.** A transition can report a
  flawless `translateY` series while nothing reaches the glass. What separates
  "the animation is wrong" from "the animation is right and the phone is too
  busy to draw it" is whether `requestAnimationFrame` is being called at all —
  so the report leads with the largest gap between frames.
- **It is fetched, not bundled.** It is the one thing here allowed to require
  the network, since it exists to be run while someone is holding the phone.
  That keeps it out of the cold-load budget entirely.

It found both close-button faults on its own first run, with the same numbers a
human had extracted from a video by hand.

**What would change it:** a way to attach Safari's inspector to a home-screen
web app without a Mac and a cable. Until then this is the only instrument that
reaches the device.

### And it is a sheet now

Asked for repeatedly and put off while the band was still unexplained, which
was the wrong order — the request was never only cosmetic. A full-bleed push
*claims the whole display*, and this display keeps 59 points back. A sheet that
starts below the status bar with the dimmed forecast behind it never made that
promise, so the strip at the bottom stops reading as something withheld.

Modelled on `UISheetPresentationController`, because that is what a day detail
would be in a native app. Two detents — medium at 38% of the sheet's height,
large just under the status bar. Flat `--bg` rather than a second sky: a sheet
is a surface lifted off the page, and a flat colour is also the only kind that
can be *asserted* equal to the canvas, which after §26 is not a small thing.
The curve is `cubic-bezier(.32,.72,0,1)` over 460ms — Ionic's, matched to iOS's
own, and already written down here as `--push-ease`.

Three behaviours separate a sheet that feels real from a panel that animates,
and all three are implemented rather than approximated:

- **The dimming tracks the drag.** The scrim's opacity is a function of where
  the sheet currently is, so the page behind brightens under your finger. Most
  of the illusion lives in that one coupling.
- **A flick is not a drag.** Past ~0.5 px/ms the sheet goes one detent the way
  it was thrown, wherever you let go; below that it snaps to the nearest.
  Position-only sheets feel sticky, velocity-only ones feel twitchy.
- **The drag defers to the scroll.** At the large detent a drag may only begin
  at the top of the content; at the medium one the content does not scroll at
  all, so the whole surface is a handle (`prefersScrollingExpandsWhenScrolled-
  ToEdge`, iOS's default). A gesture that turns out to be sideways is handed
  back, because the hourly curve inside the sheet scrolls horizontally.

**The dismiss control is a trailing X, not a leading back chevron**, and the
first version of the sheet got that wrong — it kept the push's «‹ Назад». The
rule is old and it is about grammar, not decoration: *"if something slid in
from the right — the user moved further into the hierarchy — use «Back», at the
left. If something slid in from the bottom (a modal view), use «Done», at the
right."* A chevron on a sheet claims a navigation that never happened.

An X rather than the word «Готово», because Apple's own line is "avoid using
Done buttons for things other than completing the task" and there is no task
here — you read a day and close it. That is `UIBarButtonItem.SystemItem.close`:
a small filled circle with an xmark, in grey rather than the accent colour,
which is what the App Store and Photos put on a sheet you only read. It is not
redundant with the grabber: the grabber says the sheet resizes and can be
flicked away, the button is the explicit, reachable, labelled version.

This required narrowing invariant 13, deliberately — see AGENTS.md. It forbids
hand-rolling the *horizontal* swipe, which is the system's. A vertical drag
does not collide with it, and dismissal still goes through `history.back()`
from every path, so there is exactly one way out and the edge swipe still
works.

**What would reverse it:** wanting the day to feel like a place you navigated
to rather than a panel over the forecast. That is the honest argument for the
push, and it is why it was built that way first.


The cost was three deploys and someone watching the same bug survive three
announcements that it was fixed. Two lessons, both cheaper than the bug:
**when a defect exists only on a device, get a number off the device first**;
and **build the harness before the fifth guess, not after** — `tools/phone.py`
is forty lines and would have replaced every one of them.

**What would change it:** iOS giving a standalone web app the whole display, at
which point the strip disappears and the footer is just a footer — which is
fine, because it earns its place as information anyway. If the day screen ever
becomes a bottom sheet (rendered, and it works — the flat `--bg` runs into the
strip seamlessly), the footer stays: a sheet has the same bottom edge.

---

## 27. When the state blob went away, only the icon looked broken

August 2026. `weather.cw` — the hydration JSON the whole Gismeteo current block
was read from — disappeared from all four pages at once. What was reported was
one question mark where the hero's icon goes.

What had actually happened is the more interesting half:

| field | before | after |
|---|---|---|
| `temp_c` | tier 1, the blob | **tier 3**, the first `<temperature-value>` in the document |
| `condition`, `icon` | tier 1 → tooltip | gone — hence the question mark |
| `feels_like_c`, `humidity_pct`, `pressure_mmhg`, `wind_ms`, `wind_dir` | tier 1 | gone, silently |
| `observed_epoch` | tier 1 | gone, taking the condition's fallback with it |

Three separate failures, one visible. The temperature was still right, and
still on screen, and now being found by *position* — the configuration this
whole codebase is arranged to avoid. The five secondary fields simply became
blank, which took the entire «Подробности» card off the Gismeteo tab: below
three cells the block does not render, and a block that does not render is
indistinguishable from a source that never published those fields. Yandex kept
its card. Gismeteo lost its card. Nothing said why.

**The repair reads prose and a grid, and admits it.**

The condition and the temperature come from the site's own header sentence —
«в Йошкар-Оле пасмурно, небольшой дождь, +12°» — with the city removed *before*
the weather words are classified, because `ru_text` matches as substrings and
Russia has towns called Снежинск. The other five come from the captioned widget
grid the hourly strip already reads, at the column covering now.

Two things make that honest rather than convenient, and both are load-bearing:

- **The column is chosen by time.** The page states its own clock —
  `<time-value class="current-time" timestamp>` — and the column taken is the
  one covering that instant. Column zero is midnight. This parser has already
  shipped the other version of this once, putting a description of 00:00 beside
  a temperature observed at 23:00, and it went unnoticed because the fixture
  was captured at 00:54, the one hour of the day when the two agree.
- **The provenance records the weaker step.** The rows answer at tier 1 — their
  own `data-row` keys — but the alignment that picks a cell out of them is tier
  2, and a value is only as trustworthy as the weakest link that produced it.
  Recording tier 1 here would tell `health.fallback_profile` the ground is
  firmer than it is, and that profile is the one signal that says a source needs
  looking at.

A strip that ends before the page's own clock is refused rather than stretched.
The last column of a page mid-redesign is not «сейчас» merely by being last, and
"something beats nothing" is the reasoning that puts a plausible wrong number in
front of someone who will dress for it.

**What would reverse it:** `weather.cw` coming back. The recovery is written as
"fill what is still `None`", so it is already a no-op on a page that has the
blob — the July capture still parses entirely at tier 1, and there is a test
that fails if *no* remaining fixture does, because the day both are blob-less
the tier-1 branch is untested code that the next reader will delete as dead.

---

## 28. A pinned clock is an instant, not a time of day

The browser suite freezes `Date` at `FIXTURE_NOW` and the mock server is pinned
to `FIXTURE_NOW.date()`. For a while those were two different days.

`page.clock.set_fixed_time` takes UTC. `FIXTURE_NOW` had been written as
`22:00` — the *city's* wall clock, matching the recorded pages. Three hours out,
and at 22:00 three hours crosses midnight, so the browser believed it was the
14th while the server believed the 13th.

Nothing failed. Not one of 66 browser tests, because the app is internally
consistent: `dayLabel` asks what day it is **in the city**, got one answer, and
rendered it faithfully. So the ten-day list opened on yesterday, «Сегодня» sat
in the second row, «сейчас» pointed at 01:00, and every screenshot the harness
produced looked like a layout bug somebody would go and hunt for in the
stylesheet — which is exactly what §26 is about.

Both ends were pinned. They were pinned to different moments. That is the same
failure as fixtures from two recordings, wearing a clock.

`FIXTURE_NOW` is now a timezone-aware UTC instant, taken from the page that
stamps itself, and `tools/phone.py` pins the same way rather than rendering
August's fixtures against whatever day the machine thinks it is. The test is in
`TestRendersAtAll`, asserted through the screen — the first row of a ten-day
forecast is today — because the thing worth protecting is that the picture is
honest, not that two constants match.

**What would reverse it:** nothing about the app. If the fixtures are recorded
in a city on another offset, the instant moves with them; it is read off
`<time-value class="current-time">`, so re-recording carries it along.

A footnote worth more than the entry: the test that requires every decision here
to state its reversal condition **had never checked the newest one.** It split
the file on headings and let the last section run to the end, so it swallowed
the trap list and borrowed a keyword from it — and the last section is always
the one just written, always the one nobody has reviewed. It surfaced only when
§29 was appended and §28 suddenly had to stand on its own. A green test is a
claim like any other.

---

## 29. The sky is the only thing on this screen that is not information

Everything else here earns its place by being a number somebody needs. The sky
does not, and it is the reason the app is nice to open.

It used to be seven gradients and three effects, with eighteen weather
conditions mapped onto them — so drizzle, steady rain, a downpour and a
thunderstorm were the same picture, and the only thing that distinguished them
was a caption you had to stop and read. Now the *motion* carries the intensity:
thin and slow through dense and fast, two precipitation layers at spacings with
no common factor so the tiling does not read as a plaid, a cloud layer behind
at a different speed for depth. Night differs from day, which is why the
envelope grew a `night` flag — only `clear`, `partly` and `cloudy` carry the
hour inside their icon, so rain at midnight was being lit for noon.

Three rules held it in check, and each is in the stylesheet next to the line it
governs:

- **`transform` and `opacity`, nothing else.** Those are the two the compositor
  can run without waking the main thread, and the main thread on this page is
  drawing a temperature curve. There is a test that reads every `@keyframes`
  block in the shell and fails on a third property.
- **Seamless by construction, not by tuning.** A pattern repeating every *P*
  pixels may only be translated by a whole multiple of *P*. The slant is a
  `skewX`, which leaves the vertical period alone, so the repeat is
  `background-size`'s height and the travel is the same custom property. The
  drift layers avoid the question entirely by running `alternate`, which has no
  wrap.
- **Out of the way of the text.** The layers live in a masked wrapper that fades
  by the point the gradient pales, so nothing moves behind a card. The mask is
  on the wrapper and not on the layers because a mask travels with the element
  it is on, and a fade that slides down the screen once a second is worse than
  no fade.

**What would reverse it:** a fourth raise of the byte budget for something that
is actually information. This cost 3 kB compressed and buys nothing you could
not read from the caption; it is the first thing that should go.

---

## 30. A loop that jerks is arithmetic, not taste

The rain twitched once a second and had done since it was written. Worth
recording because the diagnosis took one calculation and no deploys, and the
six-deploy bug in §26 took six.

`repeating-linear-gradient(104deg, ... 46px)` repeats every 46px **along its own
axis**. Vertically — which is the direction the animation moved — that is
46/cos 14° = 190px. The animation moved 14% of a 1198px layer: 168px. Every
0.85s the pattern wrapped 22px out of phase and the whole screen jumped
sideways. Snow was worse, 52px of a 220px tile, and got away with it only by
being nine times slower.

Nothing about that is visible in the code. Two numbers in two different files,
in different units, related by a cosine nobody wrote down.

The lesson generalises past this bug: **a periodic animation has a divisibility
constraint, and if the constraint is not expressed in the code it is being met
by luck.** Here the constraint is now structural — one custom property is both
the pattern's repeat and the animation's travel, so they cannot disagree — and
there is a test that reads both back out of the browser and compares them.

**What would reverse it:** nothing; this is arithmetic. But if a layer ever
needs a *diagonal* repeat rather than a skewed vertical one, the travel has to
be recomputed as `P / cos θ` and the test above will say so.

---

## 31. `visibility` in a transition flips at the midpoint

The sheet's entrance lost its first half for weeks, and the report was always
the same sentence: *the pop-up starts from the wrong position.* It was fixed
twice by moving things that were not wrong.

```css
transition: transform 460ms var(--push-ease), visibility 460ms;   /* wrong */
```

`visibility` does not fade. It is a discrete property, and a transition of a
discrete property changes value at **50% of the duration**. So for 230ms the
sheet was already travelling and still `hidden`, and what reached the eye was a
panel materialising a third of the way up the screen, in motion.

None of five hundred tests saw it, and they were right not to: every computed
style was perfect. The transform series was correct from 781 to 297; the frames
simply were not on the glass for the first half of it. That is the difference
between "the animation is wrong" and "the animation is right and invisible",
and only an instrument on the device can tell them apart.

`static/debug.js` printed it on the first run after being asked:

```
✗ открытие: первый видимый  533  (ожидается 781)
```

and 781 − (230/460) × 484 = 539. The measurement and the arithmetic agree to
six points.

The fix is the standard two-line idiom, and it is worth knowing by heart:

```css
.screen      { transition: transform 460ms ease, visibility 0s linear 460ms; }
.screen.open { transition: transform 460ms ease, visibility 0s; }
```

Instant on the way in, delayed on the way out — so the sheet is visible from
its first frame and stays on screen until it has finished leaving. Both halves
are tested.

**What would reverse it:** nothing about this. If the entrance ever needs the
sheet hidden for part of its travel, that is `opacity`, which actually
interpolates.

---

## 32. A source outage answers 200, and the recorder ate the evidence

15 August 2026. Meteofor served every page with the correct title, the correct
city, valid markup, and this where the forecast belongs:

```html
<div class="widget widget-no-data">
  <div class="desc">Данные уточняются. Пожалуйста, зайдите чуть позже.</div>
```

Three things then happened in order, and the order is the whole lesson.

The **parser refused it** — no temperature, so the tab went dark with a reason.
That is invariant 1 working exactly as designed, and it is why nobody was shown
a made-up number.

The **recorder destroyed the evidence.** `make fixtures-gm` was four `curl -f`
calls with `>` redirects. `curl` was perfectly happy with a 200, so four good
fixtures became four empty ones before anyone looked at them.

And then **the outage looked like a parser bug** — the tab was dark, the
fixtures no longer parsed, and the recording that would have told the two apart
had just been overwritten by the thing that caused the confusion. An hour went
into establishing that nothing here was broken.

`fixtures-gm` now downloads to a scratch directory, checks each page for the
`data-row=` grid, and installs nothing unless all four have it. It says which
it is:

```
  refusing to record: .../ carries no forecast grid.
  it says so itself (widget-no-data): an outage on their side, not a parser bug.
  Your existing fixtures are untouched. Try again when it is back.
```

Two rules fall out of it, and the second is the general one:

- **Before believing a source is broken, check whether it is merely empty.**
  A page that says `no-data` in its own class names is not a redesign.
- **A recorder must never overwrite its own evidence.** Download, inspect,
  then install — in that order, always. The same reasoning applies to anything
  that captures state for later comparison.

**What would reverse it:** a source that stops marking its own empty state, at
which point the check needs a different signal — but it should still be a
check, and it should still run before the write.

---

## 33. A push to master is the deploy, and nothing here can reach the server

*Decided 2026-10-01, the day the last manual step went.*

A release used to be `make deploy`: build for amd64 on whichever machine ran
it, push to the registry, ssh into the server, pull, restart, then poll
`/api/health` until it settled. Every step worked. Every step was also a thing
to remember, run from a machine that held a login to the server.

Now a push to `master` is the whole procedure. CI runs lint and the unit suite,
the browser suite and an image build; when all three pass, `release` publishes
the image as `:master` and `:sha-<short>`; a tool on the server — configured in
the owner's infrastructure repository, not here — sees the new digest within a
couple of minutes, deploys it behind a health check, and puts the previous
image back if the check fails. Every Makefile target that logged in to the
server went, and `deploy/` with them. What is left reaches the server the way a
browser does.

**Why.**

- **The suite became the gate.** It was always the thing that had to pass before
  anyone believed anything; now it is also the only thing that has to pass
  before the phone gets it. Five hundred tests are a better release checklist
  than a person remembering one.
- **Credentials go the right way round.** CI holds no key to the server, only a
  token scoped to the run that can publish this repository's image. The server
  fetches the image; nothing reaches in. That makes the image the way in
  instead: whatever can change what `release` publishes -- a push to
  `master`, an action running in that job, a dependency resolved at build
  time -- runs on the server within minutes, which is why each of those is
  pinned rather than trusted (amended 2026-10-02: actions by commit SHA,
  runtime dependencies by hash in `requirements.lock`, and `release` publishes
  the image `image` built and started rather than building a second one).
- **Rollback stopped being a procedure.** A failed health check undoes itself.
  A bad build that passes the check is undone the ordinary way — `git revert`
  and push — or, while `master` cannot be trusted, by pinning a known-good
  `:sha-` tag in the infrastructure repository.
- **What is live is answerable without access.** `/api/version` names the build
  and `/api/health` says how it is doing; `make status` asks both, from
  anywhere, with no key (amended 2026-10-02: `/api/health` is retired, §38;
  the forecast's own `health` block and each source's state say how it is
  doing, and that is what `make status` reads).

**What it does not buy.** The gate checks that the code passes its tests and
that the app starts and answers. It does not check that the numbers are right:
the suite reads committed fixtures and cannot see a site that redesigned
overnight. That is `make canary`'s question, asked weekly, and the canary is
deliberately outside the gate. Nor does a deploy wait for `/api/health` to say
`ok`, because that endpoint is allowed to report a source down, and Yandex
having a bad morning is no reason to roll back a good build. (Amended
2026-10-02: the server's check asks for the page and `/api/version`, and
`/api/health` is retired, §38.)

**What would reverse it.** A CI verdict that stops meaning what it says. Once a
green tick ships, a tick that can be green over a red suite is not a gate but a
delay — and that is exactly what this one was, found the day it started
deploying. The unit step piped `pytest` into `tee`, GitHub's default shell runs
without `pipefail`, and the step reported `tee`'s success over the suite's
failure, so the one test known to be red could never have turned it red. Fixed
the same day by naming `bash` as the shell for every step, which turns
`pipefail` on, and that test is now an explicit `xfail(strict=True)` rather
than a failure the gate could not see. If the verdict and the suite ever part
company again, delivery goes back to being a deliberate act until they are
reconciled.

---

## 34. Fixtures are what the parsers read, not what the sites sent

*Decided 2026-10-01, the day this repository was readied for publishing.*

The fixtures used to be whole pages: doctype to `</html>`, two hundred flight
pushes, ad slots, a few dozen news teasers per Gismeteo page — 6.5 MB in all.
That was harmless in a private repository and wrong in a public one, which
would be redistributing somebody else's site in order to test a parser that
reads a few kilobytes of it.

They are now cut down by `tools/trim_fixtures.py` to what the parsers and the
tests read: 1.3 MB in all. The keep-lists are the parsers' own XPaths and
markers — the identity elements, the forecast blocks, the four flight pushes
`extract.py` reads (and the decoy the tests prove it never reads), the
`window.M.state` keys the Gismeteo parser uses. The cut is textual, so every
kept byte is the recorded byte: the tests regex raw markup, and a page
round-tripped through a parser would change `&nbsp;` and quoting underneath
them. The tool refuses to write a page the app would read any differently,
including with each fallback tier forced off the way `test_ladder` forces it,
and the `make fixtures*` targets run it, so a re-recorded page arrives
trimmed. A page it refuses is left as recorded, because a redesign is exactly
the page a parser has to be fixed against, and
`TestTheFixturesStayTrimmed` in `tests/test_invariants.py` fails on any
committed fixture that trimming would still change. Leaving one whole is a
mistake the suite catches, not one a reviewer has to.

**What it cost.** Two tests measured the page rather than the parser and were
re-aimed: a truncation that cut at a fixed 40,000 characters now cuts where the
current conditions begin, and a decode check that wanted 100,000 characters of
flight now wants 5,000. The month and details pages, which nothing read, went
altogether. And the undecodable-push path in `extract.flight` is no longer
exercised by any fixture, because the two pushes that reached it were tracking
scripts.

**What would reverse it.** A parser that needs something the trim threw away.
The answer then is to re-record and widen the keep-list for that element, never
to commit a whole page again; the tool's refusal to write is what makes the
first such mistake loud rather than quiet.

---

## 35. The install offer is a banner in the forecast, with one button

*Decided 2026-10-02, from a screenshot of Yandex Weather's.*

The old offer was a line of grey 12.5px text under the footer: «Поделиться →
На экран «Домой». В iOS 26 — в меню ⋯». It is now a card between the hourly
card and the ten days, drawn after Yandex's: a phone cropped by the card's
bottom edge with this app's own icon on its home screen, a two-line title, one
button, and a × in the corner.

**Why a banner rather than a footnote.** Installing is the largest single
improvement to how this app behaves on the phone, and the footnote was placed
where nothing is ever read: below the timestamp, below the language switch,
last on the page. Added to the home screen the app opens full screen with no
Safari bars, its storage is exempt from the seven-day ITP cap, and with no
network it shows the last forecast the service worker kept. That is worth
asking once, properly, and then never again.

**Why one button, not Yandex's «Да» / «Нет».** "No" is the × already. And
"Yes" cannot keep its promise on an iPhone: there is no API that installs a web
app from Safari, so the most a page can do is show the steps. So the button
says what it does. In Safari it is «Как добавить» and opens a sheet with
Safari's four steps, each beside the glyph Safari draws on that button. Where
the browser has handed over `beforeinstallprompt` (Chrome on Android or a
desktop) it is «Установить» and calls the event's `prompt()`, which is a real
one-tap install, and the banner goes once the choice is made.

**Why inside the forecast, below the hourly card.** The temperature is the
answer and the hero stays first; "what about later today" is the second
question, so the hourly card stays second. The banner is met on the first
scroll, after both answers, and never moves the hero down. Above the hero it
would be the first thing on every launch in Safari, which is the shape of an
advert in an app whose reason to exist is having none.

**Why only where installing is possible.** `navigator.standalone` exists only
in iOS and iPadOS WebKit, and is false outside the home screen; a held
`beforeinstallprompt` is the other way to know an install can happen. A desktop
Safari or Firefox visitor can do nothing with the offer, so they never see it,
and an installed app (`standalone`, or `display-mode: standalone`) never does
either. The × stores `yw.a2hs = no` in `localStorage`, and in memory as well,
so it holds for the visit even where storage is blocked.

Three things it cannot know. On iOS the installed app and Safari keep separate
storage, so a Safari tab cannot learn the app was added; the × is what silences
it there. Browsers built into other apps also report `standalone` as false and
cannot add to the home screen at all, which is why the sheet says «в Safari».
And Apple's Russian name for the "Open as Web App" switch could not be checked
against Apple's own Russian pages — one translated article calls it «Открыть
как веб-приложение» — so the Russian step says «переключатель» without naming
it. It is the only switch on that screen.

It cost 2.5 kB compressed (a cold load went from 50.3 to 52.8 kB), most of it
the two languages' worth of steps and the phone, which is drawn in CSS and
inline SVG rather than shipped as an image, and sized in `cqw` of the card so
that 320pt gets the same picture smaller rather than a phone crowding the
words. Crossing 64 KiB also exposed a gap in the budget test, which read
`Content-Length` and found none: Starlette streams a file past one 64 KiB chunk,
and its gzip middleware then states no length. `wire_bytes` now recompresses at
the middleware's level instead, and a test holds that to the stated length
wherever one is still stated.

**What would reverse it.** Safari learning to install a web app from a page:
then the iPhone gets the one-tap button too, and the sheet goes. If the steps
move again in iOS 27, they are the `a2hsStep*` strings in `app.js`, not a
reason to drop the banner. And if a budget raise is ever wanted for something
that is information, the phone drawing is the first thing to give back: a
plain card with the same title and button keeps the behaviour for a fraction
of the bytes.

---

## 36. English is a reading of the sources, not a translation of them

*Decided 2026-10-02, asked for by the owner along with the banner.*

The interface speaks Russian or English. Which one is decided on the device:
the switch in the footer, else the first of `navigator.languages` that is one
of the two, else English; `?lang=en` or `?lang=ru` in a link sets it too. Every
string the app says is a `STR` entry carrying both languages side by side, and
`t(key)` picks one.

**Nothing about the choice leaves the phone** (invariant 5). The server is not
told, and its requests to the weather sites are byte-for-byte the same whoever
is reading. That is the constraint that shaped everything else, because the
sources speak only Russian:

- **A condition is named from its icon key.** «Пасмурно, небольшой дождь» is
  `rain-light`, so an English screen says "Light rain". The icon key is the
  reading of the phrase the server has already checked (`ru_text`), so the
  word and the picture cannot disagree; a translation table of phrases would
  be a second, unchecked reading of the same text. The Russian screen keeps the
  source's own words, nuance included.
- **Prose of a known shape is read; prose of any other shape is left out.**
  Yandex's nowcast says «Слабый дождь с 10:00 до 22:00» or «Сегодня осадков не
  ожидается», and both become English. A sentence the app has never seen is
  not shown at all on an English screen: it would be Russian, which the reader
  chose not to read, and a guessed translation is the plausible-wrong-value
  failure (§3) in words. The same rule for the day's length and the magnetic
  field.
- **The server's own words** -- a tab's reason, the parts of a day, a known
  warning -- go through one small Russian-to-English table in `app.js`. A
  warning not in it stays as written, since it is addressed to the maintainer.
- **Names.** The six built-in cities carry the names English speakers use:
  Moscow, not the transliterated Moskva. A GPS fix or a hand-added city is
  transliterated on the server (`ru_text.latin`, BGN/PCGN the way English
  signage spells it -- Kozmodemyansk, Yelabuga, Rostov-na-Donu); for a Russian
  place that *is* its English name. A search asks the geocoder in **both**
  languages whoever is asking, and joins the answers by the geocoder's id:
  asking only in the reader's language would tell a fourth party what it is,
  an `Accept-Language` header by another name. It costs a second request per
  uncached search, on a cache that keeps an answer for a week.

The installed app's name follows the page (`manifest.webmanifest?lang=en`,
`apple-mobile-web-app-title`), never a request header.

It is tested the strong way: on an en-US browser no visible line -- on every
source's forecast, every day of every source, the place sheet -- carries a
Cyrillic letter, except the switch back to «Русский». A new string that skips
`STR` fails that test rather than a reader.

**What it cost.** About 3.7 kB compressed, most of it the table: every string
now exists twice, and the English renderings of what the sources say
(`COND`, `RU_EN`, the nowcast shapes) are new. Paid for on every cold load,
including the Russian ones, because a second file fetched only for English
would put a frame of Russian in front of every English launch.

**What would reverse it.** A source that publishes English directly would be
tempting -- Yandex does, at `/pogoda/en` -- but fetching it only for English
readers is the leak this entry is built to avoid, and fetching it for everyone
doubles the upstream footprint for the words alone. If that ever looks worth
it, it is a decision about §25's request budget, not about this table.

---

## 37. A public instance gets a budget for strangers

*Decided 2026-10-02, the day after the repository and the instance it names
were made public.*

§18 sized everything for one phone, and "a second user" was its reversal
condition. A public URL is not a second user but an unbounded number of them,
and three things measured that day made it concrete. Each new 0.01° cell asked
for by `?lat=&lon=` cost one or two Yandex requests and one to Open-Meteo, and
nothing stopped the next one (40 anonymous requests made 80 and 40). During an
outage every request for a registry city re-ran the whole fan-out, thirteen
requests against hosts already refusing. And 64 stranger coordinates evicted
the owner's own city from the cache, so the next outage answered 503 instead
of the six-hour stale payload.

So places outside the registry -- GPS fixes, searched cities -- and search
misses draw on one token bucket for the whole process (burst 20,
`COLD_FETCHES_PER_HOUR`, 180 by default). Registry cities never do: they are
a handful of keys at one round per ten minutes each, however often they are
asked for. Over budget, the weather route answers with what the client
already knows how to draw -- the stale payload, or the DOWN envelope with the
reason «слишком часто» -- and never a bare 429, which the client would store
as if it were a forecast. A minute's memory of "everything was down" and of
"no page for that day" stops an outage being retried at request rate.
(Amended 2026-10-02: ten minutes for "no page for that day". The day endpoint
never drew on the bucket, so six cities times ten dates could still ask Yandex
sixty times a minute while it refused; now six. §42.)

The owner's own GPS fixes and searches share the bucket with everyone else's,
which is the one cost: a stranger spending it all makes his location button
answer «слишком часто» for a while. The registry is exempt precisely so that
the cities he actually uses never are.

**What would reverse it.** The instance going private again, or a reverse
proxy in front of it that rate-limits per client -- at which point the bucket
can be raised until it never fires. Not removed: it is also what keeps a
search box from being a free proxy to the geocoder.

*Amended 2026-10-02: the second half of that condition was wrong, and the
bucket stays as it is.* The proxy exists now. Since 2026-10-01 nginx limits
`/weather/api/` per client address: 30 requests a minute with a burst of 20,
and 300 a minute with a burst of 60 shared by everyone arriving through the
relay. But a per-client limit bounds each client and never the sum, and the
sum is what the bucket is for: the upstreams see one address, this server's,
and Open-Meteo's free tier counts one total. Per-address limits multiply with
the number of addresses asking, and a single address at 30 a minute may
already ask for 1,800 new places an hour, ten times the bucket's 180. Nor can
the app take the per-client half on itself: nginx blanks the client's address
on the way in (README, *Privacy*), so to the app every request comes from
nobody in particular. The two answer different questions -- how much one
client may ask of the app, and how much everyone together may spend of the
server's address -- and both stay. What would reverse it now is the instance
going private. Nothing put in front of it could: a proxy counts requests, and
only the app knows which of them cost an upstream round.

---

## 38. `/api/health` is retired, and the forecast is the diagnostic

*Decided 2026-10-02 by the owner, on a review of what the public instance
tells strangers.*

`/api/health` answered anyone with the server's verdict and, beside it, the
server's notes to itself: each source's error text as the fetcher wrote it --
upstream URLs, exception messages -- and the route that last reached Gismeteo,
which names a proxy by host and port whenever one is configured.
`routing._mask` strips a proxy's credentials, not its address. Production sets
no proxy, so what it has published so far is upstream URLs and internals
rather than an address; but a public endpoint that would start publishing the
box the server routes through on the evening somebody configures one is a trap
waiting for that evening.

And nothing needed it. The server's deploy check, configured in the owner's
infrastructure repository, asks for the page and for `/api/version`; the
image's `HEALTHCHECK` asks `/healthz` (DEPLOY.md). Only this repository read
`/api/health`: `make status`, the weekly canary, the docs and the tests.

So it answers **410 Gone**, with a short JSON body naming `/api/version` for
the build and `/api/weather` for each source's state.

- **410, not 404.** A 404 at that path is also what a wrong `BASE_PATH`, a
  path the static mount swallowed, or a proxy that never reached the app
  would answer, so anything still asking -- an old checkout's `make status`, a
  monitor set up by hand -- would take the retirement for an outage. Only the
  app can say 410, and it says "this is up, and the answer moved". The debug
  routes answer 404 so as not to advertise whether a token is configured;
  there is nothing like that to hide here, in a public repository that says
  the endpoint existed. Saying it costs nothing: no cache, no upstream.
- **The forecast is the diagnostic.** Everything `/api/health` said that
  anyone may know was already in every `/api/weather` payload, under the names
  the app itself uses: `health.status`, `warnings`, `age_s` and
  `divergence_c`, and per source `available`, `reason`, `provenance`,
  `fallback_profile` and `dropped_fields`. `make status` takes the build from
  `/api/version` and the rest from there, and the canary reads the same
  payload for the default city.
- **The notes stay, for the debug token.** The same `detail` lists rode in
  every `/api/weather` payload, to every phone, so retiring the endpoint alone
  would have closed nothing. They are left off the wire now unless the
  request carries `X-Debug-Token` -- the rule `force` and `/api/debug/*`
  already follow -- and that answer is `no-store`, so no cache in between
  keeps a copy for the next visitor. Nothing in `static/` read them: the app
  shows `warnings` and each tab's short `reason`, and those stay. Production
  configures no token. There every fetch failure is still in the container's
  log, as it always was, and setting a token on the server brings back the
  rest: the validator's verdicts, and which route reached Gismeteo.
- **No `/api/health` for the debug token, either.** With the token,
  `/api/weather` and `/api/version` between them say everything `/api/health`
  did. A second route reshaping the same envelope under names of its own is
  the same thing written down twice, and this one had already drifted: it
  called the dropped fields `dropped`, the canary asked it for
  `dropped_fields`, and so a dropped field could never fail the canary.
  Reading the payload, it can.
- **A stale answer is still a failure.** `/api/health` answered 503 for a
  stale payload as well as for none. `/api/weather` serves the stale one with
  200, because the phone should still show it, so `make status` and the
  canary read `health.status` rather than the HTTP code and fail on it all
  the same: a stale payload's provenance describes the last fetch that worked,
  not today's pages.

**What would reverse it.** A question the payload cannot answer without work
of its own -- a probe of every Gismeteo route from the server, say -- would
earn a route, behind the debug token like the other diagnostics rather than
in public. The 410 itself can go, and the path fall through to a plain 404,
once the access log shows nothing has asked for it in a few months.

---

## 39. Dependencies earn their place, and the locks say what ships

*Decided 2026-10-02, the day the owner said new dependencies are welcome when
they earn their place, and asked for the earlier choices to be reviewed.*

Until then every dependency waited for the owner's word (`AGENTS.md`), and the
lock was a day old. This is what came in when that changed, how the locks are
kept, and the one earlier choice worth revisiting: the HTTP client.

**What came in for the tests.** The image's one change, of HTTP client, is
further down.

- `httpx2`, for Starlette's TestClient. From Starlette 1.7 it prefers httpx2
  and warns on every run that falls back to httpx -- a warning
  `ignore::DeprecationWarning` never hid, because Starlette issues it as a
  UserWarning.
- `hypercorn` and `trustme`, for `tests/test_transport.py`: the app's own
  `http.client()` over a real socket, against a local TLS server that speaks
  HTTP/2, trusting an authority minted per run. Every other test stubs the
  network out, so nothing in the suite had ever made a handshake, negotiated
  HTTP/2, followed a redirect or decoded gzip with the client the app ships --
  which is exactly the layer a change of HTTP client changes.
- The tools CI pinned inline -- pytest, ruff, playwright, pillow -- moved,
  exact, into `requirements-dev.txt`, which CI, the README and `make lock` all
  read now.

**Hashed, the tools too.** `requirements-dev.lock` holds them and everything
they pull in. Two reasons, both about the gate. Exact pins on the names still
left what sits beneath them -- pluggy, greenlet, pyee and the rest -- free to
change, and any of those can turn master red on its own release day, which
here is a deploy that does not happen. And the jobs that install them decide
whether `release` publishes: a tool that could make the gate lie belongs to
the deploy as much as the app's own dependencies do. The cost is one
generated file and no extra command. It is resolved against the app's lock
(the `-c requirements.lock` line in `requirements-dev.txt`), so a package both
need is one version in both, and CI installs the two together: if they ever
disagree, pip refuses (tried, with one version changed by hand).

**Kept by `make lock`.** It runs exactly the command written at the top of
each lock, and `tests/test_docs.py` holds the recipe and the headers to each
other, so the header alone reproduces a lock. uv keeps every pin that still
satisfies `requirements*.txt`: on unchanged inputs both files come back byte
for byte (checked). `UPGRADE=--upgrade`, or `--upgrade-package` with a name,
takes new releases, and uv leaves those flags out of the header. A version
changes only in a reviewed diff to a lock.

**Dependabot for the actions, not for pip.** `.github/dependabot.yml` moves
the SHA-pinned actions and the release named beside each -- exact now,
`v4.4.0` rather than `v4` -- in one grouped pull request a week, and only for
releases a week old: a hijacked action release is usually found and pulled
within days. All seven are a major version or more behind today, so the first
pull request will be a big one. Not pip, because it cannot keep these locks
(read in dependabot-core, 2026-10-02): it re-runs a lock's command only for a
`.txt` compiled from an `.in`, and edits anything else in place, a package and
its hashes at a time. `requirements-dev.txt`'s pins would move without the
lock CI installs from, and a lock it touched would stop being what the command
at its top produces. (Amended 2026-10-02: monthly now, not weekly; and since
nothing here asked whether a pinned Python package had been found vulnerable
since, a weekly workflow does -- an alarm, not part of the gate, §42.)

**Deprecations fail the suite.** The blanket ignore is gone. Python's own
deprecation categories are errors now, and so is any UserWarning whose message
says it is a deprecation -- Starlette, FastAPI and httpx2 all issue theirs
that way, so that they show by default. The suite is clean on 3.11, 3.12 and
3.13 (run on each). A deprecation inside a dependency can only arrive with a
lock change, which is exactly when somebody is reading the diff.

**OpenTelemetry's API: kept.** FastAPI 0.142 requires `opentelemetry-api` and
imports it. Read and measured: with no provider configured its telemetry does
nothing -- one check per request, 2.6 µs -- and at startup it adds exporters
only when an `OTEL_EXPORTER_OTLP_*` endpoint is set, and then refuses to start,
because no SDK is installed. 692 KiB on disk, about 12 ms of a 430 ms import,
and one dependency of its own, already here. Pinning `fastapi<0.142` resolves
to 0.141.1 and holds the framework back, indefinitely, for a package that does
nothing. What would matter is an exporter, so that is what a test forbids: no
OpenTelemetry SDK, exporter or instrumentation in `requirements.lock`. With
one in the image, an environment variable alone could start sending request
paths -- coordinates included -- off the box.

**httpx2, for the upstreams.** Moved, in a change of its own, deployed by
itself: the suite cannot fetch from Yandex, and the deploy's check fetches only
the app's own pages, so a regression there would ship without a sound. The
commit that moved it says what to watch once it is live.

- *Why move.* httpx's last release is 0.28.1, of December 2024. httpx2 forked
  from it and released fifteen times between May and September 2026, under
  Pydantic, which already supplies pydantic here. The API this code uses is
  unchanged but for the module's name, and the default headers differ only in
  the User-Agent, which the two scrapers set for themselves. Among its fixes,
  two touch this app: bounded memory while decoding compressed responses, and
  a cap of five chained content-encodings. And the tests already needed it.
- *What changes underneath.* Compared function by function with httpx 0.28.1
  and httpcore 1.0.9: the HTTP/2 connection, the TLS start, the redirect
  headers and the decoders were all reworked in places. That is what
  `tests/test_transport.py` runs, and it ran unchanged on both, but for the
  exception class it names.
- *TLS.* httpx2's default context is `truststore`, the operating system's
  store, which on Linux it applies afresh to every new connection. In
  `python:3.12-slim` -- Debian 13, `ca-certificates` and `openssl` installed --
  that is a re-read of `/usr/lib/ssl/cert.pem` per connection: 19 ms at the
  median and up to 37 ms, on the event loop, measured on that same layout.
  The context `http.py` builds once at import costs nothing per connection.
  So `http.py` keeps building its own, from certifi -- now a direct
  dependency -- and the switch changes nothing about who is believed.
  truststore is installed, because httpx2 requires it, and verifies no
  origin. (An `https://` egress proxy's own certificate would be checked
  against the system store by httpcore2's default; none is configured.)
- *Size.* About half a megabyte more installed (35.1 to 35.6 MB, bytecode
  included): httpx2 carries WebSocket and SSE support nothing here uses, and
  truststore comes with it. The diagnostics that run inside the image
  (`tools/probe403.py`, `tools/route_probe.py`) moved with it, since httpx is
  no longer there to import.

**What would reverse it.** Each part has its own condition. The hashed dev
lock: a tool that publishes nothing hashable for a platform someone works on.
Dependabot for pip: dependabot-core re-running the command a lock records,
whatever its file names -- or this repository moving to `uv.lock`, which it
does maintain. Errors on deprecations: one inside a dependency that no version
choice fixes, which earns a named `ignore` line with its reason, never the
blanket back. The OpenTelemetry API: FastAPI's telemetry starting to work
without a provider, or the package pulling in more; wanting traces at all
would be a privacy decision before it is a dependency one. The client: httpx2
stalling the way httpx did, or drifting from the HTTPX API this code is
written against.

---

## 40. The sky is the same in both appearances; light mode is the surfaces

*Decided 2026-10-02, after the owner read the measurement: "Light-mode contrast
on the sky could be better — yes, pls do!"*

Light mode had a sky of its own. It had to start deep -- iOS draws the status
bar's glyphs white over it under `black-translucent` -- so it held a saturated
blue for the top third and opened out to near-white by 62%. The hero's lower
lines and the source strip sit between those two points, and on the pixels, on
every one of the seven skies, the white text there read at **1.4 to 3.1:1**:
the selected tab's temperature, light blue on a grey that had once been blue,
was 1.4. Nothing had failed. The test that guarded it asked whether the text
*colours* were light, and they were; it never asked what was behind them.

**Two ways out, and the one taken.** The light sky could have held its deep
part under everything that sits on it -- but the strip's position depends on
the hero's height and the viewport's, and a gradient fixed to the viewport
cannot know either: an iPhone SE puts the strip in the pale part again. Or the
sky could stop changing with the appearance, which is what Apple Weather does:
the sky is a picture of the weather, and the weather does not depend on a
setting in the phone. Light mode then means what it means everywhere else on
iOS -- the cards and the sheets are light, the way widgets on a dark wallpaper
are. That is the one built, and it removed more than it added: the light
palette of seven skies, the dark raindrops drawn for a pale sky, and the list
of on-sky elements that needed white text in one scheme only, which is how
the day screen once shipped a near-black title on a blue bar.

**What it took:**

- `--sky3`, the foot of the sky, split from `--bg`. They were one variable
  because in the dark scheme they are one colour, and §26 needs the sheet and
  the canvas below it to agree. In light mode `--bg` is the sheets' surface
  and `--sky3` stays navy; with the viewport the whole display there is no
  canvas to see below a sheet (`debug.js` checks the two only when there is).
- Nothing on the sky takes a palette colour (§11): the place, the hero, the
  strip and the footer are white at fixed alphas, chosen on the brightest sky
  -- `cloudy-day` under its haze -- with a margin over 4.5:1. That fixed the
  dark scheme too: its hero lines were `--dim` and `--faint`, 3.3 to 4.3:1 on
  the two day skies.
- Light cards are opaque. White at 86% over navy is grey (#dcdde2), and the
  white cells of the facts grid read as tiles on it.
- The light palette's quiet greys moved to AA on the surfaces they are drawn
  on, and `--cold`, the chance of rain under each hour, went from a sky blue
  that was 1.8:1 on white to a deep one. The curve reads its colours from the
  stylesheet now, instead of copies, so it follows.
- The weather icons were drawn for a navy sky; on a white card the clouds were
  1.5:1. A hairline drop-shadow in light mode gives each an edge without a
  second set of eighteen symbols.
- One first paint for both appearances, which fixed the step §19 recorded as
  unfixable: the manifest's single colour is now right in light mode too.

A browser test measures it the way it was found: on each of the seven skies,
in both schemes, the text on the sky, the quietest text on the cards over it
and the footer are made transparent and every pixel behind them is scored.
Before this change it failed in both schemes.

**The one cost.** In Safari (not the installed app), iOS 26 tints the strip
behind its toolbar from `.edge-bot` once, at first render (§14). In light mode
that is navy, which matches the page and not a light sheet opened over it.

**What would reverse it.** Wanting light mode to *feel* light rather than to
be light where you read -- a pale sky is the honest version of that, and it
needs every element on it re-measured on every sky. The test above is the one
that will say so.

---

## 41. The installed app's canvas is the top of the sky

*Reported 2026-10-02 with two cards from the app switcher: "there is strange
artifact on top, like dark gradient, only in pwa mode". The Safari card was
clean. Fixed the same morning and confirmed on the phone, build 4aff50c:
"worked well".*

### What it is

iOS 26 draws a **scroll-edge effect** under the status bar of a home-screen web
app: a soft blur, strongest under the clock and gone some 35pt below it, which
is there so the clock stays legible over whatever scrolls beneath it. It is
system chrome, painted over the web view, and no CSS turns it off.

Its colour is ours, though. WebKit leaves the soft effect's colour to the
scroll view's background (`_updateTopScrollPocketCaptureColor` in
`WKWebView.mm`: the pocket "should match the scroll view background color
anyways"), and the scroll view's background is `underPageBackgroundColor` --
the root element's `background-color`. Here that was `--sky3`, `#0a1020`, the
near-black foot of the sky, faded over its lightest part.

The screenshot says so on all three channels at once. Under the clock the
installed app was a flat **(27,39,64)**; Safari shows the same sky there as
**(48,71,105)**. Converted to the screenshot's colour space, the band is the
sky with `--sky3` laid over it at 56.1%, 57.0% and 55.6% -- one strength,
within 1.5 points. Black would need 43%, 45% and 40%, and the manifest's
`theme_color` 62%, 64% and 69%: neither is one colour at one strength.

### Why Safari is clean, and why the usual fix does nothing here

Safari covers the strip under its status bar with a colour of its own, read
from a fixed element at the top of the page (`.edge-top`, §14), and WebKit
hides the blur whenever that colour is showing (`_shouldHideTopScrollPocket`).
But it only shows it over an *obscured inset* -- a region the browser's own
chrome covers -- and a `black-translucent` home-screen app has none: the page
runs to the top of the glass and the status bar is just drawn on it. The
phone says as much: `debug.js` measures a 59pt safe area under the clock, and
WebKit subtracts any obscured inset from the safe area it reports. So
`.edge-top` was already being found, and could change nothing.

That is the fix most often proposed this autumn -- a fixed, full-width, opaque
strip within 4pt of the top -- and one write-up reports it working. The device
reports from projects that shipped a fixed or sticky top layer say otherwise,
and agree with the source: the blur stayed (Twilight #148, herdr-web-ui #164,
wynteam #664). The other common proposal, `status-bar-style: default` or
`black`, moves the page *below* an opaque bar. It would take the sky out from
under the clock, which is the design, and it needs a reinstall to test,
because iOS reads that tag when the icon is added (§26, sixth attempt). None
of the reports found has a device confirming it either. It stays in reserve.

### The fix

In the installed app -- `@media (display-mode: standalone)`, so nothing changes
in Safari -- the canvas is `--sky1`, the top of the sky. The blur is still
drawn; it is now the colour of what it is drawn over, and a blur of a smooth
gradient is invisible.

Three things follow from making the canvas light at one end:

- **It follows the scrim.** With a sheet up, the sky under the clock is
  darkened, and an undimmed canvas would tint the blur *lighter* than what is
  behind it -- the same band, inverted, on every open sheet. `setSheet` writes
  the scrim's opacity to `--scrim` beside the scrim itself, and the stylesheet
  mixes it in. What eases is the **number**, on the scrim's curve, so the two
  agree on every frame: a transition on the colour would run in Oklab, which
  is not how black at an opacity darkens what is under it. A drag stops it
  easing, as it stops the scrim.
- **`--scrim` is registered and not inherited.** A drag writes it on every
  frame, and an inherited custom property changed on the root restyles every
  element in the document.
- **The installed app does not bounce.** A bounce past the bottom would pull
  the light canvas up under the dark foot of the sky. `body` carried
  `overscroll-behavior-y: none` from the first commit, meant for exactly this,
  and it never did anything: WebKit takes `overscroll-behavior` from the root element and
  nowhere else (`LocalFrameView::verticalOverscrollBehavior`). The inert rule
  is gone; the installed app sets it on `<html>`. Safari still bounces, on
  purpose -- it keeps pull-to-refresh, which is a natural thing to do to a
  forecast, and its canvas is still the foot of the sky.

### What checks it

Chromium cannot be put in `display-mode: standalone` -- the DevTools call that
emulates media features accepts it and does nothing -- so the browser tests
find the stylesheet's standalone rules and make them unconditional, and then
compute what the phone computes from the same text: the canvas against
`--sky1` on every palette, against the dimmed sky at both detents and on every
frame of the transition between them, mid-drag, after closing; the bounce;
that `<body>` does not inherit `--scrim`; and that Safari kept its canvas and
its bounce. `tools/phone.py` applies the same rules, since the phone runs the
installed app.

None of that draws the blur. On the phone, the build hash runs `debug.js`, which
now prints `канва = верх неба`, `отскок (html)` and, with a sheet up,
`тон под часами` -- the colour iOS is being handed, against the colour it
should be, in the state the screenshot came from.

The cold-load budget did not move. The stylesheet's prose about the canvas was
condensed to pay for it; the stories it told are §26 and this.

**What would reverse it.** The band still on the phone while `debug.js` ticks
all three lines: then the tint is not the canvas after all, and the next step
is `status-bar-style: default` with a reinstall. Or WebKit starting to hide the
effect in home-screen apps the way it does in Safari, at which point the
canvas could go back to the foot of the sky. Or iOS drawing the same effect
along the *bottom* of a home-screen app, where a canvas the colour of the top
of the sky would be wrong.

---

## 42. The image is started locked down; known vulnerabilities are an alarm, not a gate

*Decided 2026-10-02 by the owner, after three independent reviews of the day's
hardening asked whether it had earned its weight.*

CI starts every image read-only, with a tmpfs at `/tmp`, no Linux capabilities
and `no-new-privileges`, and waits for its own `HEALTHCHECK` -- the check the
server's deploy waits for, which nothing here had run. It proves the image runs
under the flags the server should use; it protects nothing until the server
uses them too.

`audit.yml` asks PyPI every Monday, and whenever `requirements.lock` changes,
whether anything pinned there has a published advisory. It is not part of the
gate: by the time an advisory lands the vulnerable version is already live, so
blocking the next push would only delay a sky tweak.

Tried the same day and taken back: the audit as a gate, with pip-audit and two
dozen packages in the dev lock; the base image pinned by digest, which turned
patching into a pull request most Mondays and added nothing `release` did not
already guarantee; and `persist-credentials: false`, guarding a read-only
token. Dependabot proposes the actions monthly. The same review gave the sky
its room (§18), dropped the README's test count, and has a refused day page
remembered for ten minutes (§37).

**What would reverse it.** A second maintainer, or deploys nobody reviews,
would make the gate worth its chores again. If the server never adopts the
flags, the locked-down run is decoration and can go.

---

## 43. Rain falls from the curve

*Decided 2026-10-03 by the owner, choosing from six drafts drawn on the real
card.*

The question the hourly card is opened for, more than any other, is whether it
will rain in the next couple of hours -- and it answered that more quietly than
anything else on it. Where a source gives a chance or an amount, it sat in the
11.5px row under the times. On Yandex, the default tab, whose strip has icons
and no numbers at all, it was a pair of drops inside a 26px cloud. A yes-or-no
question was being answered by reading a row of small figures.

The owner's suggestion was the fill: it is drawn there already and it is liked,
so let it carry the weather too. So rain falls from the line. Under the curve a
wet hour gets slanted streaks, snow gets dots and sleet gets both -- the marks
the icons and the sky (§29) already use for them, so nothing new has to be
learnt. **Density is how hard**: millimetres where a source gives them (under
0.5 light, under 1.5 moderate, heavier above), and the icon's own word where it
does not, which on Yandex is always. **Opacity is how sure**: the source's
probability where it has one, and 40% or more with nothing else to go on is
drawn as the lightest rain. **A dry hour draws nothing**, and on a dry day the
card is pixel-identical to the one before this entry.

Six versions were drawn on eight forecasts and compared side by side: today's
card and five changes to it, on the two real recordings, examples aimed at the
awkward cases, and light mode. The four that lost:

- **The hour's dot became a drop.** Too small to find at a glance, which was
  the whole point.
- **The fill turned blue.** The literal reading of the suggestion, and the
  curve already says *cold* in blue: a wet hour looked like a cold one, and
  snow tinted the same way read as fog.
- **Water rose from the floor, its height the amount.** The most informative
  where there are millimetres, and a flat ledge on Yandex, where there are
  none. Its surface line also read as a second temperature until its stroke
  came off.
- **Tint and streaks together.** The loudest, and louder than a yes-or-no
  question needs.

Two things only the drafts could have found:

- **The fill is 8px tall at the strip's coldest hour, and rain that arrives
  with a cold front arrives exactly then** -- the temperature falls as it comes.
  Every version drawn inside the fill shrank to a sliver of a few pixels there.
  So the streaks keep 12px above the floor whatever the line does, and
  where it dips into that band they run on behind it.
- **The curve's points are the only `<circle>`s in the chart, and a test counts
  them.** `test_the_curve_sits_on_the_same_grid_as_the_labels` proves one point
  per column that way, and the first snow pattern drew its dots as circles: 33
  points for 24 columns. Snow is paths.

Each drawing gets its own ids, because the forecast's curve and an open day's
are in the document at once and each must clip to its own line. That has a
test, as does each rule above; the colours have a light-mode pair held to 3:1
on a white card. Measured on the cold load, 1.75 kB: 55.8 to 57.5 kB of the
64 (§18). It is information, it works offline, and it raised no budget.

**What would reverse it.** If the streaks prove too quiet outdoors in daylight,
the tint goes under them before anything else is tried -- it was drawn and is
waiting. If Open-Meteo's maybes make the card look permanently wet, the 40%
rises, not the design. And if the card stops feeling calm -- the owner's test
is that this app stays fresh and clean -- the streaks go, and the row under the
times carries the rain alone, as it did.

---

## Traps that cost real time

Kept because each was invisible until it wasn't.

- **Yandex renders minus as U+2212, not ASCII hyphen.** Miss it and every winter
  temperature comes out positive — completely invisible in July. Dedicated test.
- **`(\d{1,2})\s*°` matches "743°" as +43.** A pressure reading becomes a
  plausible temperature: in range, smooth, invisible to every bounds check.
  Every numeric pattern carries a `(?<![\d.,])` guard.
- **The forecast block renders twice** (wide and narrow layouts). A naive walk
  gives ten days followed by the same ten days, which looks exactly like a
  working 20-day forecast until you read the dates.
- **The decimal comma eats the wind speed.** `скорость ветра 1,7 м/с` parsed
  with a `[^,]+` capture — natural, since the clauses are comma-separated —
  truncates at the *decimal separator* and yields 1.
- **"безоблачно" contains "облачно".** Substring order in the icon table is
  load-bearing or a cloudless sky renders as overcast.
- **An `<svg>` with no width/height defaults to 300×150** and destroys the
  layout.
- **The same number written down twice always diverges.** Three times here, in
  one afternoon, which is why it gets a named entry rather than a bullet:

  1. The hourly column was `58px` in the stylesheet and `54px` in the layout
     code. The curve drifted 4px left per column and stopped 96px short of the
     last label — which does not look like a wrong constant, it looks like the
     data running out.
  2. The scrim was `rgba(4,8,18,.62)` in CSS and `0.62 / [4,8,18]` in JS,
     written *while fixing the first one*.
  3. The test count in the `README` was hand-edited three times and wrong after
     two of them.

  All three got one source and a test that asserts the *agreement* rather
  than either value — alignment in pixels, the composited colour, the number
  pytest actually collects. (The third went further on 2026-10-02: the README
  states no count at all, so there is nothing to agree with, §42.) When a
  value has to exist in two languages, the second one reads it back; it never
  restates it.
- **A gradient in `objectBoundingBox` units vanishes on a flat line.** Twenty-four
  identical hours give the polyline a zero-height bounding box, and the spec
  says not to render the element at all. `userSpaceOnUse` has no such edge, and
  it makes the colour absolute besides.
- ~~**iOS Safari ignores `overflow:hidden` on `<body>`.**~~ **This bullet is the
  trap.** It was true until iOS 16.3 and then wrong for three years, and because
  nothing here recorded *when* it was written or against which version, it was
  inherited as fact and cost six deploys — see §26. `position: fixed` on `<body>`
  collapses a standalone web app to the small viewport; `html{overflow:hidden}`
  has been honoured since 16.3, changes no geometry, and keeps the scroll offset
  for free. Left struck through rather than deleted: a workaround that outlives
  its browser bug is the most expensive kind of note in this file, and it is
  worth seeing one.
- **A position is not a date.** «Сегодня» and «Завтра» were decided by the row's
  index, and the three sources disagree about which morning their ten days start
  on — so the same date was named differently depending on which tab was open.
  Same species as the headline reading the strip's first column and calling it
  now. Ask what the value *is*, never where it sits.
- **A metric row can be missing a half.** Gismeteo's pressure row publishes a
  maximum for ten days and a minimum for eight. Read as a flat list of typed
  elements that is eighteen where twenty are expected, and every day after the
  gap takes its neighbour's number — a real pressure, in range, in the right
  unit, attached to the wrong day. Cells are counted as containers.
- **A source's own abbreviations have to be in the table.** Gismeteo's ten-day
  header says «сб 1 авг», and `MONTHS` held only «августа» and «август» — so the
  label matched nothing and every date came from "today plus the column index"
  instead. The fallback is correct on every day but the one it exists for.
- **A stub whose signature drifts fails like a broken upstream.** The mock's
  Gismeteo fetcher never grew the `timeout=` keyword the real one did, so every
  mock fetch raised `TypeError`, the router logged it as a fetch error, and the
  Gismeteo tab was quietly disabled in every screenshot and browser test.
- **Fixtures from two different recordings are not a smaller reality.** The mock
  paired a landing page from one day with an hourly strip from another, and the
  coherence check — correctly — reported the app as broken on every fetch.

### And two traps in the test harness

Both looked exactly like application bugs and cost more time than the bugs would
have.

- **Playwright scrolls an element into view before clicking it**, which reset
  the page to the top and made the scroll-lock test report a failure that did
  not exist.
- **`page.evaluate(str)` invokes the result if it is a function**, so a stub
  ending in `window.f = () => {...}` gets called once before any interaction —
  making a click handler look like it fired twice.

If a test fails in a way that contradicts what you see by hand, suspect the
harness before the code.
