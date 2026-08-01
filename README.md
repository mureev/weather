# CM Weather

A self-hosted, ad-free weather app for an iPhone. The phone talks only to your
server; your server talks to the weather sites. No App Store, no Apple Developer
licence, and no upstream ever sees the phone's IP.

Live at **`mureev.com/weather`**. Default city Yoshkar-Ola, text search for
anywhere else, and a **Моё местоположение** button when you want *here*.

Three independent sources — **Яндекс**, **Gismeteo**, **Open-Meteo** — fetched
together and switchable with one tap.

Compressed cold load is about 26 kB — shell, script, service worker and the
first payload together. The image ships 34 MB of dependencies and the process
holds a bounded cache; both are asserted by tests rather than hoped for.

```bash
make            # list every command
make check      # lint + 389 tests, no network required
make run        # localhost:8080 against live upstreams
make deploy     # build amd64, push to GHCR, restart on the VPS, check health
```

---

## Start here

If you are picking this up cold, read these four things and skip the rest until
you need it:

1. **`make check` must pass before you believe anything.** 389 tests, no
   network. The parser tests run against real captured HTML, not invented
   markup.
2. **The fixtures in `tests/fixtures/` are ground truth.** When a site
   redesigns, `make fixtures` re-records from production and the test diff tells
   you exactly what moved. That two-minute loop is what this project is built
   around.
3. **`DECISIONS.md` holds the reasoning.** The code is cheap to regenerate; the
   reasoning is not. That is not a platitude here — this project's predecessor
   lost its entire codebase and was rebuilt in an afternoon from surviving
   documentation, and the *only* thing that mattered was the why.
4. **`/api/health` is the diagnostic.** Per source: available, why not,
   provenance tier per field, pairwise divergence, and the build SHA. It answers
   "what is wrong" without guessing.

---

## Architecture

```
iPhone PWA ──HTTPS──▶ mureev.com/weather ──┬─▶ yandex.ru/pogoda    RSC flight JSON
(same origin only)                         ├─▶ gismeteo.ru  ─┐    window.M.state
                                           │   meteofor.lv ─┘    (same data, two doors)
                                           └─▶ Open-Meteo         plain JSON API
                                            ▼
                           parse → validate → grade, per source
                    GET /api/weather → all three + a health block
```

All three are fetched concurrently and **all three are returned in one
payload**. Switching source is a client-side choice with no refetch — which
matters for a reason beyond latency: you are comparing three readings taken at
the same instant, not three taken as you tapped. Each tab carries its own
temperature, so the disagreement is visible without switching at all.

| source | current | hourly | 10-day | nowcast | any city? |
|---|---|---|---|---|---|
| Яндекс | RSC flight JSON | a11y prose | a11y prose | ✓ | ✓ by lat/lon |
| Gismeteo | `window.M.state` | typed attrs, own page | typed attrs | — | only known ids |
| Open-Meteo | JSON API | JSON API | JSON API | — | ✓ by lat/lon |

The front end has no idea *how* any number was extracted. That indirection is
the maintainability story: when a site redesigns — not if — one parser changes
and nothing downstream notices.

### Extraction: three tiers, three mechanisms

Not three flavours of CSS selector. Three things that fail *independently*:

| tier | mechanism | breaks when |
|---|---|---|
| 1 `NAMED` | embedded state JSON | the site changes its internal data contract |
| 2 `LABELLED` | accessibility prose, labelled neighbourhoods | the information architecture changes |
| 3 `SHAPE` | content-classified DOM cells | the CSS class names change |

Every field records which rung answered. If yesterday everything came from tier
1 and today it all comes from tier 3, the numbers may still be perfectly
correct, and the ground has moved, and the parser is one edit from confidently
reading the wrong cell. `health.sources.<x>.fallback_profile` says so on a calm
day rather than on the day you needed the forecast.

**Yandex** is a Next.js App Router app; its RSC flight stream carries a `fact`
object whose keys mirror the official API. Each day card also carries a
visually-hidden screen-reader paragraph that is *more precise than the screen*
(`1,7 м/с` where the visible cell rounds to `2`) and self-labelling, so the
whole "right shape, wrong cell" failure class cannot occur there.

**Gismeteo** is easier, contrary to both sites' reputations: `window.M.state` is
plain JSON carrying the city's own coordinates, so its identity check is
arithmetic rather than an argument about Russian declension, and its forecast
temperatures are `<temperature-value value="21">` — a typed, already-signed
attribute. It costs three requests rather than one: the landing page's hourly
strip is *three*-hourly, eight columns wide, so `/hourly/` is fetched as well
and whichever page yields more hours wins. That page is optional by
construction — if it redesigns, the forecast gets coarser instead of
disappearing.

Gismeteo is also the one source that has to be *reached* rather than merely
parsed: it returns 403 to this server's address and no header, transport or TLS
change touches it. The fix was not a proxy. `meteofor.lv` is the same service
under its export brand — same numeric city ids, same page, same values to the
minute — and it serves the addresses `gismeteo.ru` refuses. So `GISMETEO_HOSTS`
is a list, `GISMETEO_PROXY` is a list, the fetch walks the product of the two
until one answers, and it remembers which one did. `make routes` shows you that
walk from whatever machine you run it on. The full story, including why the
proxy instinct was backwards, is `DECISIONS.md` §7.

### How it knows a parser broke

The failure that hurts is not the loud one. A parser returning nothing is caught
by the first `if not data`. A parser returning **743** because a redesign moved
the pressure cell will tell you it is +743 degrees — or a plausible +55 after
some well-meaning clamp — and you will believe it.

**Values are dropped, never clamped.** Every rejection path sets the field to
`None`. Five layers, each catching what the others cannot:

1. **Range contracts** — Oymyakon's −67.7 °C clears them; 743 in a temperature
   field does not.
2. **Unit signatures** — a range check says *impossible*, a signature says
   *why*. The interesting case is humidity `0.81`, which passes 0–100 cleanly
   and only the signature sees is a fraction.
3. **Series structure** — 24 identical hourly values means a selector matched
   one node and the loop read it 24 times. An 8 °C hour-to-hour step is a row
   misalignment, not meteorology.
4. **Continuity** — the temperature did not move 20° since the fetch twenty
   minutes ago. The allowance grows with the gap, so a long outage never trips
   it; its job is the parser that broke *between* two fetches.
5. **Internal coherence** — does the source agree with *itself*? The four above
   are vertical: one value, one series. None of them can see a headline
   condition describing midnight beside an hourly column describing now, which
   is a real bug that shipped here. Every field was in range, in the right
   unit, in a well-formed series and continuous; they were individually perfect
   and jointly nonsense. Only holding two of them against each other shows it.

Plus **page identity**, which is separate and the most important of all: a page
that parses perfectly but describes the wrong city is rejected before a single
number is believed. See `DECISIONS.md` §2.

Degradation is graded, per source, independently:

```
a field fails a contract  -> drop that field, serve the rest, say so
the source is unusable    -> that tab is disabled, with the reason on it
every source is unusable  -> serve the last good payload, marked stale
nothing cached either     -> 503 with an honest error
```

There is no rung on which the app serves a number it does not believe.

---

## The front end

No framework, no build step, no dependencies. Three files.

**The sky is one gradient painted three times** — on the page, on the browser
canvas (what iOS fills the notch and the overscroll bounce with), and as two
invisible solid-colour strips at the viewport edges, which is the only thing
iOS 26 Safari will read when it tints the areas behind its own status bar and
toolbar. It ignores `theme-color` and samples a fixed element's
*background-color*, so a gradient is invisible to it (`DECISIONS.md` §14).

**The hero has no card** — it sits on an animated, condition-aware sky. That is
not decoration: a box with four lines in it reads as *empty*, whereas the same
four lines on a sky read as *calm*. Clear nights get a star field, rain gets
streaks, snow gets flakes; `prefers-reduced-motion` turns the motion off and
keeps the colour.

**Icons know what time it is.** Two of the three sources ship no day/night
information whatsoever, so the sun is computed from the coordinates and the
clock rather than read or guessed — see `DECISIONS.md` §13, and note that the
tests check it against Gismeteo's own published sunrise and sunset.

**Hourly is a curve**, not a row of numbers, with the label riding the line —
"is it getting warmer or colder" is the actual question, and a line answers it
before you read a figure. **Day rows have range bars** showing where each day's
low-to-high sits inside the whole period, so "is Thursday the cold one" needs no
arithmetic.

**Everything about *where* lives in one sheet**, opened by tapping the city
name. Search, geolocation and saved cities are all answers to the same question,
so they belong in one place rather than three permanent strips.

### The iOS constraint that shapes all of it

**A PWA cannot refresh in the background. At all.** Background Sync, Periodic
Background Sync and Background Fetch are unsupported; silent push is prohibited
by design, and a service worker that takes a push without showing a notification
has its subscription revoked after three strikes.

That is not a limitation you engineer around, it is one you design *for*: render
the cached payload instantly, refetch on every return to the foreground, and put
the timestamp somewhere you cannot miss it. The app never pretends the number on
screen is newer than it is.

---

## Privacy, and the ways it leaks

A PWA's own `fetch()` comes from the device and exposes the phone's IP.
**iCloud Private Relay does not help** — Apple states it "guarantees that users
can't use the system to pretend to be from a different region" and maps each
egress IP to the device's actual city. It preserves exactly the signal you want
suppressed.

So everything goes through the server. The naive version of that still leaks,
in these specific ways, all closed here:

1. **Third-party subresources are direct connections** — CDN fonts, hosted JS,
   and worst of all map tiles, which hit the tile host with your IP *and* the
   tile coordinates. Closed by `Content-Security-Policy: default-src 'self'`
   with no host allowlist at all, and by the service worker returning 403 for
   any cross-origin request. **Tested at the network layer**: `test_ui.py`
   captures every request the page makes and asserts none leaves the origin.
2. **`preconnect` / `dns-prefetch` / `preload` open real connections** before
   any JS runs. There are none, deliberately, with a comment saying so.
3. **Header forwarding** — only coordinates go upstream. Never the phone's
   `Accept-Language`, `User-Agent`, `Referer` or timezone; `Europe/Moscow`
   versus anything else gives away region independently of IP. The nginx snippet
   also blanks `X-Forwarded-For` on the way *in*: a value that never arrives
   cannot end up in a log.
4. **Geolocation** — opt-in, on a button, never automatic. Coordinates rounded
   to 2 decimals (~1.1 km) on the device and again on the server. They go to
   *your* server, which asks Yandex by lat/lon and reads the city name back off
   the response, so no fourth-party geocoder ever sees them.

**What this does not do is hide the server.** It is in Latvia, so Yandex sees a
Latvian IP — you have moved the signal, not removed it. `check_identity` makes
the resulting wrong-city risk fail loudly rather than silently. See
`DECISIONS.md` §7 for the tunnel that would remove it properly.

The egress proxies are worth one note here, since they are the one place a
stranger's machine could enter the path: every upstream is HTTPS, so a proxy is
asked to `CONNECT` and then relays bytes it cannot read, with certificates
verified against the origin by us. A hostile hop can stall or drop the
connection. It cannot hand back a forged forecast.

---

## Working on it

```bash
make check                              # lint + everything
make run                                # live upstreams, native arch, fast start
make mock                               # offline, against the fixtures
YW_MOCK=winter   make mock              # negative temperatures, U+2212
YW_MOCK=degraded make mock              # a source down, tabs disabled
make shots                              # screenshots, light + dark
```

The `degraded` scenario is worth looking at with your eyes. If it does not look
obviously wrong at a glance, the design has failed.

### The maintenance loop

It will break, because you are parsing someone's HTML. The goal is not to
prevent that; it is that you find out immediately instead of believing a wrong
number.

```bash
export DEBUG_TOKEN=...                  # whatever is in the compose env
make fixtures                           # re-record from the VPS, then run tests
```

Tests passing against re-recorded HTML means the parser is still correct against
reality. Tests failing tells you exactly which assumption broke.

```bash
make routes                             # which way in to Gismeteo works from here
make routes-remote                      # ...and from the VPS, the one that counts
make routes ARGS='http://1.2.3.4:8080'  # ...and would this proxy help?
make fixtures-gm                        # re-record Gismeteo from whichever host answers
make selftest                           # per-source fetch/parse/identity breakdown
make probe                              # why is a source returning 403?
```

Use `make routes-remote` in anger, not `make routes`. That is the whole point
of it: a route verified — or a fixture recorded — on a machine that is not
blocked proves nothing about the machine that is, and your laptop is not
blocked. The remote variant streams the probe in over ssh, so nothing has to be
checked out on the VPS.

`tools/README.md` explains what each diagnostic answers.

### Two things that used to need remembering, and no longer do

**The service-worker cache version** is a hash of the shell files, substituted
when `/sw.js` is served. It was bumped by hand eight times in one afternoon;
the ninth is the one you forget, and the symptom — a redesign invisible to every
installed device but perfect in a fresh browser — is horrible to diagnose.

**The build SHA** is baked into the image and shown in `/api/health` and, quietly,
in the footer. "Is my change actually deployed?" should not require squinting.

---

## Layout

```
app/
  main.py            FastAPI routes, CSP, static mount, BASE_PATH
  config.py          env-driven settings (frozen dataclass)
  version.py         build stamp + shell hash for the service worker
  cities.py          registry + EXTRA_CITIES — lat/lon, never geoid
  models.py          the wire format: SourceView, Health, the envelope
  http.py            the only place an outbound client is built
  routing.py         which door to knock on, and from where (Gismeteo)
  service.py         orchestration, per-source assembly, divergence
  validation.py      the four layers; decides what is servable
  extract.py         Yandex: flight stream, a11y prose, DOM shape, identity
  cache.py           TTL cache with stale-serving grace
  ru_text.py         Russian vocabulary, content-shaped extraction, icons
  sun.py             solar position: is it night here, at this hour?
  series.py          which hourly entry describes a given instant — one answer
  sources/
    yandex_html.py   fetcher; request hygiene, host fallback
    gismeteo.py      id registry, M.state, typed attrs
    openmeteo.py     no key, no quota
    geocode.py       text city search
static/              index.html, app.js, sw.js, icons — no build step
tests/               389 tests: parsers, degradation, invariants, docs, API, browser
tools/               diagnostics (see tools/README.md)
deploy/              nginx-proxy vhost snippet + compose service block
```

Deployment: **[DEPLOY.md](DEPLOY.md)**. Reasoning: **[DECISIONS.md](DECISIONS.md)**.

## Legal

`yandex.ru/robots.txt` permits `/pogoda`; `gismeteo.ru/robots.txt` permits
`/weather-*` and disallows every URL with a query string, which is why Gismeteo
is addressed only by its clean path form. We stay at human request rates — one
fetch per source per city per ten minutes, serving every device — and identify
as a normal browser. Both sites' general ToS presumably carry the usual
anti-automation clause, so this is a ToS question rather than a technical one;
for a single private reader on his own phone the exposure is negligible.

If it ever becomes public, Yandex requires branding for publicly displayed data
— logo, «Данные Яндекс Погоды», link back — and a real API key.
