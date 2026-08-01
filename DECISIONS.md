# Decisions

Why things are the way they are. Written because this project has already
proved the point once: its predecessor lost its entire codebase to an ephemeral
container and was rebuilt in an afternoon from surviving documentation. The
~2,000 lines of code were the cheap part. The reasoning was not.

Each entry says what was decided, why, and **what would change it** — because a
decision recorded without its reversal condition becomes dogma.

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
id is not derivable from a name or a coordinate. Seven cities ship with ids
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

---

## 12. A retry is for refusals, never for parse failures

When a Gismeteo fetch fails, whether to try the next route depends entirely on
*which* failure it was:

```
refused  (Blocked, or any httpx error)  -> another route may work. Retry.
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
`httpx.HTTPStatusError` and classifies itself, but a challenge page arrives as
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
— `--sky1` at the top, `--bg` at the bottom. They are invisible on the page,
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

`CLAUDE.md` states the invariants for whoever arrives next. `test_invariants.py`
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
sky (§4), and the warning lands in `/api/health`.

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

`TestItIsCheapToLoad` asserts the compressed cold load stays under 32 kB and the
shell source under 80 kB. The budgets sit just above the measurements, so the
test that fails is the one where somebody adds a charting library.

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

## 19. Things deliberately not built

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

  All three now have one source and a test that asserts the *agreement* rather
  than either value — alignment in pixels, the composited colour, the number
  pytest actually collects. When a value has to exist in two languages, the
  second one reads it back; it never restates it.
- **A gradient in `objectBoundingBox` units vanishes on a flat line.** Twenty-four
  identical hours give the polyline a zero-height bounding box, and the spec
  says not to render the element at all. `userSpaceOnUse` has no such edge, and
  it makes the colour absolute besides.
- **iOS Safari ignores `overflow:hidden` on `<body>`.** Pinning with
  `position:fixed` is the only reliable scroll lock, and it discards the scroll
  offset, which must be saved and restored by hand.

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
