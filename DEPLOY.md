# Delivery

There is no deploy command. A green push to `master` is the deploy, and nothing
in this repository can reach the server.

## What a push does

1. **CI** (`.github/workflows/ci.yml`) runs the gate: lint and the unit
   suite, the browser suite in a real Chromium, and an image build for
   `linux/amd64`.
2. **`release`** runs only when the whole gate passes on a push to `master`. It
   publishes the image the `image` job built, stamped and started -- the same
   bytes, not a rebuild -- to GHCR as `ghcr.io/mureev/weather:master` and
   `ghcr.io/mureev/weather:sha-<short>`.
3. **The server** polls `:master` every two minutes. A new digest is pulled,
   started, and checked through the reverse proxy; if the check fails, the
   previous image is put back. That tool, and the server's configuration —
   environment variables, every one of them listed in `.env.example` — live in
   the owner's infrastructure repository, not here.

So a change is live within minutes, or not at all. Other branches and pull
requests get the same gate and publish nothing.

## What the gate checks, and what it does not

It checks that the code does what its tests say: every parser against real
captured pages, the invariants, the front end in a browser, the byte budget.
Then it checks that the image builds, starts locked down -- read-only, no Linux
capabilities, no privilege to gain -- reports this commit as its build, and
passes its own `HEALTHCHECK` (`DECISIONS.md` §42). On the server, a new image
is kept only once it answers through the reverse proxy: the page's body must
contain exactly `<title>Погода</title>`, `/api/version` must answer, and the
container must report healthy, which is the image's own `HEALTHCHECK` asking
`/healthz`. That check lives in the infrastructure repository, where nothing
here can see it, so `tests/test_api.py` pins all three answers
(`TestWhatTheServerAsks`). Above all the title: translate it, decorate it or
merely reformat it, and every deploy is rolled back while the old image quietly
goes on serving.

It does not check that the numbers are right today. The suite reads committed
fixtures, so a site that redesigned overnight is invisible to it; that is the
weekly `canary` job's question, and the canary is not part of the gate. Nor
does a deploy wait for the sources to be well: the server's check asks for the
page and for `/api/version`, never for a source's state, because Yandex having
a bad morning is no reason to roll back a good build. Nor does it ask whether a
dependency has been found vulnerable since it was pinned: `audit.yml` does,
every Monday and on every change to `requirements.lock`, and a red run there is
a reason to `make lock`, never a blocked deploy.

## What is running

Ask the site, like anyone else:

```bash
make status                                       # both of these, summarised
curl -s https://mureev.com/weather/api/version    # build, built_at, shell hash
curl -s https://mureev.com/weather/api/weather    # the forecast; per source: available, why not, tier
```

`build` is the commit. If it is not the one you pushed, the deploy is still on
its way or was rolled back. The forecast says whether the build that *is*
running is well: its `health.status`, and each source's `available` and
`reason`. `/api/health`, which used to say it, is retired and answers 410
with a pointer to these two (`DECISIONS.md` §38).

## Rolling back

- **The usual way:** `git revert` the commit and push. The revert goes through
  the same gate as everything else, which is the point.
- **When `master` cannot be trusted for a while:** pin a known-good
  `ghcr.io/mureev/weather:sha-<short>` in place of `:master` in the
  infrastructure repository, and unpin once `master` is right again.

## Installing on the iPhone

Safari → **Поделиться** → **На экран «Домой»**. On iOS 26 the compact tab bar
hides the Share button behind the **⋯** menu, so the instructions everyone has
memorised are wrong for some users now; the app's footer explains both paths.

Installing also earns persistent storage: home-screen web apps are exempt from
the 7-day ITP storage cap, and the app calls `navigator.storage.persist()` on
first launch, so the cached forecast survives.
