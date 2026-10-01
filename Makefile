# CM Weather — the everyday commands.
#
# Delivery is not in here. A green push to master is tested and published by
# CI and deployed by the server itself (DEPLOY.md), so nothing below builds an
# image for anywhere but this machine, and nothing reaches the server except
# through the public site, like any other visitor.
#
#   make test          the full suite (no network needed)
#   make check         lint + test -- what CI runs
#   make run           run locally on :8080 against live upstreams
#   make status        what is live: the build it reports, then its own health
#   make fixtures      re-record test fixtures from the box that does the fetching
#   make fixtures-ya   re-record Yandex from this machine (no DEBUG_TOKEN)
#   make fixtures-gm   re-record the Gismeteo pages from whichever host answers
#   make fixtures-day  re-record Yandex's one-day page, the one /api/day reads
#   make probe         diagnose a source that is refusing us
#   make canary        has an upstream changed under us? (live, not fixtures)
#   make routes        which way in to Gismeteo works from here
#
# Override anything on the command line:
#   make status SITE=http://localhost:8080/weather

IMAGE      ?= ghcr.io/mureev/weather:master
SERVICE    ?= cm-weather
PORT       ?= 8080
SITE       ?= https://mureev.com/weather
CITY       ?= yoshkar-ola
YA_URL     ?= https://yandex.ru/pogoda/ru/yoshkar-ola

# The Gismeteo page the fixtures are recorded from. `meteofor.lv` is the same
# service under its export brand and answers addresses `gismeteo.ru` refuses,
# so it is the default; point GM_URL at either and set GM_PREFIX to match.
GM_URL     ?= https://meteofor.lv/ru/weather-yoshkar-ola-11975
GM_PREFIX  ?= mf
UA         ?= Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36

# Stamped into the image and reported by /api/version and /api/health, so "is
# my change actually running?" has an answer. A git SHA when there is one -- it
# identifies the *code* -- and otherwise the build time, which at least
# identifies the build. CI stamps the images it publishes the same way; these
# stamp the one `make run` builds.
#
# It used to fall back to the literal string "dev", at a time when this repo
# had no commits, so every image ever built was stamped `dev` and the field
# answered nothing at all. A constant fallback is worse than no field: it looks
# like information.
BUILD      ?= $(shell git rev-parse --short HEAD 2>/dev/null || date -u +b%Y%m%d-%H%M)
BUILT_AT   ?= $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
BUILDARGS   = --build-arg APP_BUILD=$(BUILD) --build-arg APP_BUILT_AT=$(BUILT_AT)

.PHONY: help test test-fast test-if-possible lint fmt check run status mock shots \
        fixtures fixtures-ya fixtures-gm fixtures-day selftest probe routes \
        canary clean

help:
	@grep -E '^#   make' $(MAKEFILE_LIST) | sed 's/^#   /  /'

# --- local ------------------------------------------------------------------

test:
	python3 -m pytest -q

# Everything except the browser tests, which need chromium.
test-fast:
	python3 -m pytest -q --ignore=tests/test_ui.py

lint:
	ruff check .

fmt:
	ruff check --fix .

check: lint test

# Native arch, so it starts fast. For looking at it, not for shipping -- CI
# builds what ships. Stamped all the same, so /api/version on localhost says
# which commit you are looking at.
run:
	docker build $(BUILDARGS) -t $(SERVICE):dev .
	docker run --rm -p $(PORT):8080 -e DEBUG_TOKEN=local $(SERVICE):dev

# Offline, against the recorded fixtures. YW_MOCK=winter|degraded|down
mock:
	python3 -m tests.mock_server

shots:
	python3 -m tools.shoot ok degraded

# --- look at it -------------------------------------------------------------

# What is live, asked the way anyone may ask: the build the site says it is
# running, then its own verdict per source. Read-only and credential-free, so
# it is safe against anything at any time, and it exits non-zero unless
# /api/health answers 200 -- which it does not when every source is down.
# Right after a push, a build that has not changed yet is a deploy still on its
# way (DEPLOY.md), not a failed one.
#     make status
#     make status SITE=http://localhost:8080/weather
status:
	@tmp=$$(mktemp); trap 'rm -f "$$tmp"' EXIT; \
	curl -fsS '$(SITE)/api/version' > "$$tmp" && jq -c . "$$tmp" || exit 1; \
	code=$$(curl -sS -o "$$tmp" -w '%{http_code}' '$(SITE)/api/health') || exit 1; \
	jq '{status, selected, age_s, divergence_c, sources: (.sources | map_values({available, reason, temp_c}))}' "$$tmp"; \
	test "$$code" = 200 || { echo "  /api/health answered $$code"; exit 1; }

# --- maintenance ------------------------------------------------------------

# Recording is not the same job as testing, and the machine that can do one
# often cannot do the other: a laptop with curl and no pytest recorded a
# fixture perfectly and then reported `make fixtures-ya` as a failure. The
# recording is the deliverable; running the suite is a courtesy when it is
# available.
#
# **One recipe line, and that is the whole fix.** The version before this
# probed for pytest on one line and ran the suite on the next -- and make gives
# every line of a recipe its own shell, so `exit 0` ended that shell
# successfully and make cheerfully proceeded to the next line. The probe
# printed "pytest is not installed here", and then the target ran pytest
# anyway, failed, and reported the recording as broken. It looked like the
# guard had no effect at all; it had exactly the effect it asked for, on a
# shell that had nothing left to do.
test-if-possible:
	@if python3 -c 'import pytest' 2>/dev/null; then \
	  $(MAKE) test; \
	else \
	  echo "recorded. pytest is not installed here -- run \`make check\` where it is"; \
	fi

# The loop this project is designed around. Re-record from the box that
# actually does the fetching, then let the tests say what moved.
# Needs DEBUG_TOKEN set in the container's environment and exported here.
#
# Every recipe below trims what it records to the parts the parsers read
# (tools/trim_fixtures.py): the rest is somebody else's site, and this
# repository is public. A page the parsers would read differently once trimmed
# is left as recorded, with a message saying so -- do not commit it like that.
fixtures:
	@test -n "$(DEBUG_TOKEN)" || (echo "set DEBUG_TOKEN=... first, or use \`make fixtures-ya\`" && exit 1)
	curl -fsS -H "X-Debug-Token: $(DEBUG_TOKEN)" \
	  "$(SITE)/api/debug/raw?city=$(CITY)" > tests/fixtures/current.html
	python3 tools/trim_fixtures.py tests/fixtures/current.html
	@$(MAKE) test-if-possible

# Yandex, recorded straight from this machine instead of through the server's
# debug route. For when `DEBUG_TOKEN` is not enabled -- unset, `/api/debug/raw`
# answers 404, and re-recording should not be blocked behind a change to the
# server's configuration.
#
# `make fixtures` is still the better one and stays the default: it records
# what the *VPS* receives, and the VPS is the machine whose network conditions
# the parser has to survive. This records what a laptop receives. For Gismeteo
# that distinction was the whole story (it blocks by IP); for Yandex it has
# never mattered, but if a fixture taken this way ever parses differently from
# one taken through the server, believe the server's.
fixtures-ya:
	curl -fsS --compressed -A '$(UA)' '$(YA_URL)' > tests/fixtures/current.html
	python3 tools/trim_fixtures.py tests/fixtures/current.html
	@$(MAKE) test-if-possible

# Record the Gismeteo pages from whichever host currently answers. Run it where
# the fetch actually happens -- a fixture recorded on a machine that is not
# blocked proves nothing about the machine that is.
#     make fixtures-gm
#     make fixtures-gm GM_URL=https://www.gismeteo.ru/weather-yoshkar-ola-11975 GM_PREFIX=gm
fixtures-gm:
	@# **Downloaded to a scratch directory and inspected before anything is
	@# overwritten**, and that ordering is the whole point of this recipe.
	@#
	@# On 15 August 2026 the source had an outage: every page answered 200, with
	@# the right title, the right city, and this where the forecast goes --
	@#
	@#     <div class="widget widget-no-data">
	@#       <div class="desc">Данные уточняются. Пожалуйста, зайдите чуть позже.</div>
	@#
	@# -- so `curl -f` was perfectly happy and the `>` redirect replaced four good
	@# fixtures with four empty ones before anyone looked. The parser then refused
	@# them exactly as designed, which made a source outage look like a parser
	@# bug, and the recording that would have proved otherwise had just been
	@# destroyed. An hour went into telling those two apart.
	@#
	@# The page says which it is, in its own markup. `data-row=` is the forecast
	@# grid every one of the four carries; no grid, no recording.
	@#
	@# One recipe line throughout, because make gives each line its own shell and
	@# `exit 1` on line one does not stop line two -- this Makefile has already
	@# paid for that lesson once, in `test-if-possible`.
	@set -e; \
	tmp=$$(mktemp -d); trap 'rm -rf "$$tmp"' EXIT; \
	for p in "/:current" "/hourly/:hourly" "/10-days/:10days" "/3-days/:3days"; do \
	  path=$${p%%:*}; name=$${p##*:}; \
	  curl -fsS --compressed -A '$(UA)' "$(GM_URL)$$path" > "$$tmp/$$name.html"; \
	  if ! grep -q 'data-row=' "$$tmp/$$name.html"; then \
	    echo; echo "  refusing to record: $(GM_URL)$$path carries no forecast grid."; \
	    grep -q 'widget-no-data' "$$tmp/$$name.html" \
	      && echo "  it says so itself (widget-no-data): an outage on their side, not a parser bug."; \
	    echo "  Your existing fixtures are untouched. Try again when it is back."; \
	    echo; exit 1; \
	  fi; \
	  python3 tools/trim_fixtures.py "$$tmp/$$name.html" \
	    || { echo "  Your existing fixtures are untouched."; exit 1; }; \
	done; \
	for name in current hourly 10days 3days; do \
	  mv "$$tmp/$$name.html" "tests/fixtures/$(GM_PREFIX)-$$name.html"; \
	done; \
	wc -c tests/fixtures/$(GM_PREFIX)-*.html
	@# All four together, and that matters more than it looks: they are fetched
	@# in the same second in production, and a set captured across midnight makes
	@# the parts of Tuesday hang off Monday in the fixtures and nowhere else --
	@# a test failure with no bug behind it, or worse, a test that agrees with one.
	@$(MAKE) test-if-possible

# Yandex's per-day page: the one `/api/day` fetches when somebody opens a day,
# and `app/sources/yandex_day.py` reads (DECISIONS.md §25).
#
# `.../details/auto/10-day-weather/day-N` is one day per URL and carries more
# than the ten-day page does: eight three-hourly columns with temperature,
# feels-like, condition, wind *and gusts*, precipitation probability,
# visibility and road state, plus sunrise, sunset and day length. All of it in
# the self-labelling accessibility prose that makes this source safe to read.
#
# The suite reads `ya-day5.html`, so DAY=5 is the default and the one that
# matters; the tests restamp its date, so any day's page will do.
#
#     make fixtures-day
#     make fixtures-day DAY=3
DAY        ?= 5
fixtures-day:
	curl -fsS --compressed -A '$(UA)' -H 'Accept-Language: ru-RU,ru;q=0.9' \
	  '$(YA_URL)/details/auto/10-day-weather/day-$(DAY)' \
	  > tests/fixtures/ya-day$(DAY).html
	python3 tools/trim_fixtures.py tests/fixtures/ya-day$(DAY).html
	@wc -c tests/fixtures/ya-day$(DAY).html
	@echo "\n  Recorded. make check says whether yandex_day still reads it.\n"

# The test suite runs against committed fixtures and therefore cannot notice
# that the real pages have moved. This reads the live /api/health and fails if
# any source has slipped to a lower extraction tier -- the early warning, on a
# calm day, rather than on the morning the forecast mattered. Stdlib only.
#     make canary
#     make canary SITE=http://localhost:8080/weather
#     make canary CANARY_ARGS='--allow-missing gismeteo'
canary:
	@python3 tools/canary.py --site '$(SITE)' $(CANARY_ARGS)

selftest:
	@test -n "$(DEBUG_TOKEN)" || (echo "set DEBUG_TOKEN=... first" && exit 1)
	@curl -fsS -H "X-Debug-Token: $(DEBUG_TOKEN)" "$(SITE)/api/debug/selftest" | jq

# Six-row matrix: three header sets against HTTP/1.1 and HTTP/2. Tells you
# whether a 403 is the headers, the transport, or the TLS fingerprint.
probe:
	docker run --rm -i -v "$(CURDIR)/tools/probe403.py:/probe.py:ro" $(IMAGE) python /probe.py

# Every (host, egress) pair the app would try, in order, with what each one
# actually returns. Pass candidate proxies to test them before committing one:
#     make routes ARGS='http://1.2.3.4:8080 http://5.6.7.8:3128'
routes:
	docker run --rm -i -v "$(CURDIR)/tools/route_probe.py:/probe.py:ro" \
	  -e GISMETEO_HOSTS -e GISMETEO_PROXY -e UPSTREAM_PROXY \
	  $(IMAGE) python /probe.py $(ARGS)

clean:
	rm -rf .pytest_cache screenshots
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
