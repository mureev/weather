# tools/

Diagnostics, not tests. Nothing here is part of the CI gate — `canary.py` runs
there weekly, on its own schedule, and decides nothing — and each exists
because a specific question came up once and will come up again.

| file | the question it answers |
|---|---|
| `route_probe.py` | **Start here for a dead Gismeteo tab.** Walks every (host, egress) route the app would try, in the same order, with the same parser, and prints what each one actually returns — status, city, temperature, provenance tier. Pass candidate proxies as arguments to test them before committing one. `make routes` |
| `canary.py` | **The one that runs unattended.** The suite tests committed fixtures and so cannot notice that the live pages have moved; this reads the live forecast — `/api/weather`, the payload every phone gets — and fails when any source slips to a lower extraction tier or drops a field. Exit 1 = something drifted, 2 = nothing to measure (the site is unreachable, or no source is answering). Stdlib only. `make canary` |
| `gm-probe.sh` | A source returns 403 to us and 200 to curl — is it the headers, the HTTP version, the TLS fingerprint, or the IP? Bisects all four. No dependencies. |
| `probe403.py` | The same matrix from inside the built image, using the app's own headers. `make probe` |
| `flight_probe.py` | Dumps Yandex's RSC flight stream and pulls out any JSON value by key. This is how the `fact` object was found in the first place. |
| `shoot.py` | Screenshots at iPhone size, light and dark, against the mock server. `make shots` |
| `trim_fixtures.py` | Not a diagnostic: what every recorded page goes through before it is committed. Cuts a capture down to what the parsers and tests read — the rest is somebody else's site, which a public repository must not redistribute — and writes nothing if the parsers would read the trimmed page any differently. The `make fixtures*` targets run it; `--check` says whether a page still needs it. |
| `phone.py` | **Reach for this before theorising about a phone-only layout bug.** Renders at the phone's real 393×852, applies the safe-area insets Chromium reports as zero, and pins the clock to the moment the fixtures were recorded — so the image is what the display shows rather than what a desktop window contains. `PHONE_LANG=en` shoots the English screen; `--readme` also writes the two pictures at the top of the README. It used to render a 393×793 view over a composited 59pt strip, faithfully reproducing a bug whose cause it had not found (`DECISIONS.md` §26). `python -m tools.phone` |

`gm-probe.sh` earned its keep: it proved Gismeteo blocks by **IP**, not by
request shape, after two rounds of header and transport theorising. Every row
flipped together when the egress IP changed — which is what "the variable you didn't
put in the test is the one that matters" looks like.

It also shows the limit of a well-built probe. It answered its question
correctly and completely, and the answer was still not the solution: the block
was real and unfixable *for that hostname*, and the fix was another hostname
serving the same data (`DECISIONS.md` §7). `route_probe.py` exists because that
is the shape of the question worth asking — not "why is this door shut" but
"which doors are open" — and it is the one to reach for first.
