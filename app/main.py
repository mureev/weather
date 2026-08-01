"""FastAPI routes, security headers, static mount.

Everything hangs off `BASE_PATH` (default `/weather`) so the app can live as a
subsection of an existing site without a single hardcoded path anywhere else.
Set `BASE_PATH=""` and the same image serves a bare subdomain.

The header block is not decoration. `default-src 'self'` is what makes the
privacy claim true rather than aspirational: it is a browser-enforced guarantee
that no byte of this page comes from anywhere but this origin, so no third
party -- not a CDN, not a font host, and above all not a map-tile server -- ever
sees the phone's IP alongside a location. `geolocation=(self)` keeps the GPS
button working while denying it to anything embedded.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from . import cities
from .config import settings
from .models import Status
from .service import ORDER, cache_stats, client, get_weather, invalidate
from .sources import geocode
from .splash import DEVICES, gradient_png
from .version import BUILD, BUILT_AT, SHELL, info

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), 20),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("yw")

STATIC = Path(__file__).resolve().parent.parent / "static"
BASE = settings.base_path

app = FastAPI(title="CM Weather", docs_url=None, redoc_url=None, openapi_url=None)

# Compression, and it is not a micro-optimisation. Measured on the real
# payloads: the weather JSON goes 22.8 kB -> 2.5 kB (89% -- it is a very
# repetitive document), the shell HTML 32 kB -> 11 kB, the script 29 kB ->
# 11 kB. A cold load drops from about 103 kB to about 28 kB, which on a phone
# on mobile data is the difference between "instant" and "loading".
#
# Nothing in front of us was doing it: nginx-proxy's vhost block for /weather/
# has no gzip directive, so every byte was going out raw.
#
# `minimum_size` because compressing a 200-byte 304 or a short error costs more
# than it saves, and BREACH is not a concern here for the usual reason: the
# responses contain no secret to extract. There is no session, no CSRF token
# and no auth material anywhere in the payload.
app.add_middleware(GZipMiddleware, minimum_size=800, compresslevel=6)

api = APIRouter()

CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "object-src 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp: Response = await call_next(request)
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Permissions-Policy"] = (
        "geolocation=(self), camera=(), microphone=(), interest-cohort=()"
    )
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    return resp


# --- API -------------------------------------------------------------------

@api.get("/api/weather")
async def weather(city: str | None = None,
                  lat: float | None = None,
                  lon: float | None = None,
                  force: bool = False):
    """One normalized shape, carrying every source.

    All three readings are taken at the same moment and shipped together, so
    the switcher in the UI is a client-side choice with no refetch -- and, more
    importantly, so that comparing them compares like with like.
    """
    place = None
    if lat is not None and lon is not None:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise HTTPException(400, "coordinates out of range")
        # A fix near a registry city uses the registry entry: it has a verified
        # slug, which is a more reliable way to ask than raw coordinates.
        place = cities.nearest(lat, lon) or cities.ad_hoc(lat, lon)
    elif city:
        place = cities.get(city)
        if place is None:
            raise HTTPException(404, f"unknown city {city!r}")
    else:
        place = cities.default()

    w = await get_weather(place, force=force)
    status = 200 if w.health.status is not Status.DOWN else 503
    return JSONResponse(w.to_dict(), status_code=status,
                        headers={"Cache-Control": "no-cache"})


@api.get("/api/cities")
async def city_list():
    return {"default": settings.default_city,
            "cities": [{"slug": p.slug, "name": p.name} for p in cities.listing()]}


@api.get("/api/search")
async def search(q: str = Query(min_length=2, max_length=64)):
    async with client() as c:
        found = await geocode.search(c, q)
    return {"results": [
        {"slug": p.slug, "name": p.name, "subtitle": geocode.subtitle(p),
         "lat": p.lat, "lon": p.lon}
        for p in found
    ]}


@api.get("/api/health")
async def health():
    """Deliberately opinionated. A health check that returns 200 because the
    process is alive tells you nothing worth knowing."""
    w = await get_weather(cities.default())
    ok = w.health.status in (Status.OK, Status.DEGRADED)
    return JSONResponse(
        {"status": w.health.status.value,
         "build": BUILD, "built_at": BUILT_AT, "shell": SHELL,
         "selected": w.selected,
         "age_s": w.health.age_s,
         # Pairwise deltas. Informational -- with three sources on screen this
         # no longer decides anything, but it is the first number worth
         # looking at when a reading smells wrong.
         "divergence_c": w.health.divergence_c,
         "warnings": w.health.warnings,
         "detail": w.health.detail,
         "sources": {
             k: {"available": sv.available, "reason": sv.reason,
                 "temp_c": sv.current.temp_c if sv.current else None,
                 "provenance": sv.provenance,
                 "fallback_profile": sv.fallback_profile,
                 "dropped": sv.dropped_fields,
                 "warnings": sv.warnings,
                 "detail": sv.detail,
                 "days": len(sv.daily), "hours": len(sv.hourly)}
             for k, sv in w.sources.items()}},
        status_code=200 if ok else 503,
    )


# --- debug (token-gated) ---------------------------------------------------

def _require_token(request: Request) -> None:
    if not settings.debug_token:
        raise HTTPException(404)
    if request.headers.get("X-Debug-Token") != settings.debug_token:
        raise HTTPException(403, "bad debug token")


@api.get("/api/debug/raw")
async def debug_raw(request: Request, city: str | None = None,
                    lat: float | None = None, lon: float | None = None):
    """Dump the upstream HTML verbatim, so a fixture can be re-recorded from
    the box that actually does the fetching. This is the maintenance loop: save
    it into tests/fixtures, run pytest, and the diff says exactly which
    assumption broke."""
    _require_token(request)
    from .sources.yandex_html import fetch_html, urls_for

    place = (cities.ad_hoc(lat, lon) if lat is not None and lon is not None
             else (cities.get(city) if city else cities.default()))
    if place is None:
        raise HTTPException(404, "unknown city")
    async with client() as c:
        html_text = await fetch_html(c, urls_for(place)[0])
    return Response(html_text, media_type="text/html; charset=utf-8")


@api.get("/api/debug/selftest")
async def debug_selftest(request: Request, city: str | None = None):
    """Fetch, parse and validate reported separately, with the rule that
    answered for each field. You learn *where* the break is, not that there is
    one."""
    _require_token(request)
    from .extract import check_identity, parse
    from .sources.yandex_html import fetch_html, urls_for

    place = cities.get(city) if city else cities.default()
    if place is None:
        raise HTTPException(404, "unknown city")
    out: dict = {"place": place.slug, "stages": {}}
    t0 = time.time()
    async with client() as c:
        for url in urls_for(place):
            stage: dict = {"url": url}
            try:
                html_text = await fetch_html(c, url)
                stage["fetch"] = {"ok": True, "bytes": len(html_text),
                                  "ms": int((time.time() - t0) * 1000)}
            except Exception as e:
                stage["fetch"] = {"ok": False, "error": str(e)}
                out["stages"][url] = stage
                continue
            try:
                got = parse(html_text)
                stage["parse"] = {
                    "ok": True,
                    "identity": got.ident.__dict__,
                    "identity_check": check_identity(got.ident),
                    "provenance": got.provenance,
                    "days": len(got.daily), "hours": len(got.hourly),
                    "current": got.current.__dict__ if got.current else None,
                    "nowcast": got.nowcast,
                }
            except Exception as e:
                stage["parse"] = {"ok": False, "error": str(e)}
            out["stages"][url] = stage
    out["cache"] = cache_stats()
    return out


@api.post("/api/debug/flush")
async def debug_flush(request: Request, city: str | None = None):
    _require_token(request)
    invalidate(city)
    return {"flushed": city or "all"}


# --- static ----------------------------------------------------------------

@api.get("/manifest.webmanifest")
async def manifest():
    return JSONResponse({
        "name": "Погода",
        "short_name": "Погода",
        "start_url": f"{BASE}/",
        "scope": f"{BASE}/",
        "display": "standalone",
        # Both must equal the critical-CSS colour at the top of index.html and
        # `--sky1`'s default. iOS generates the standalone launch screen from
        # `background_color`, so any disagreement here is a visible flash
        # between the splash and the app. It was #0b1220 against a first paint
        # of #0d1630 -- close enough to look like a bug rather than a choice,
        # and dark enough to read as plain black on a phone.
        "background_color": "#0d1630",
        "theme_color": "#0d1630",
        "lang": "ru",
        "icons": [
            {"src": f"{BASE}/icons/icon-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "any"},
            {"src": f"{BASE}/icons/icon-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "any"},
            {"src": f"{BASE}/icons/icon-maskable.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }, media_type="application/manifest+json")


# Every size we will ever draw, precomputed as a set. Bounding this is not
# tidiness: `gradient_png` allocates width x height x 3 bytes before
# compressing, so an open-ended size parameter is a memory-exhaustion
# primitive that costs one curl to fire. Only sizes a real iPhone asks for.
_SPLASH_SIZES = {(w * dpr, h * dpr) for w, h, dpr in DEVICES}


@api.get("/splash/{name}.png")
async def splash(name: str):
    """The iOS launch image, drawn as the sky the app is about to paint.

    The splash itself cannot be disabled -- it is the operating system's
    app-launch screen. What it *contains* is ours, and an image identical to
    the first frame makes the handover invisible. See `splash.py`.
    """
    try:
        size, scheme = name.rsplit("-", 1)
        width, height = (int(n) for n in size.split("x"))
    except ValueError:
        raise HTTPException(status_code=404, detail="no such splash") from None
    if (width, height) not in _SPLASH_SIZES or scheme not in ("dark", "light"):
        raise HTTPException(status_code=404, detail="no such splash")
    return Response(gradient_png(width, height, scheme), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=604800"})


@api.get("/sw.js")
async def service_worker():
    """Served from the app root so its scope covers the whole subsection.

    The shell hash is substituted here rather than stored in the file, so the
    cache version can never drift from the thing it is meant to version.
    """
    body = (STATIC / "sw.js").read_text(encoding="utf-8") \
        .replace("__SHELL_VERSION__", f"yw-{SHELL}")
    return Response(body, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache",
                             "Service-Worker-Allowed": f"{BASE}/"})


@api.get("/api/version")
async def version():
    return info()


@api.get("/config.js")
async def config_js():
    body = (f'window.YW_BASE={BASE!r};'
            f'window.YW_GEO={"true" if settings.allow_geolocation else "false"};'
            f'window.YW_PRECISION={settings.coord_precision};'
            f'window.YW_SOURCES={list(ORDER)!r};'
            f'window.YW_BUILD={BUILD!r};')
    return Response(body, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"})


@api.get("/")
async def index():
    return FileResponse(STATIC / "index.html",
                        headers={"Cache-Control": "no-cache"})


# How long a browser may keep each kind of asset without asking again.
#
# The shell revalidates every time: it is unhashed, so a cached copy that never
# checks is a device pinned to an old build for ever -- the exact bug the
# derived service-worker version exists to prevent, reintroduced one layer up.
# Revalidation is cheap: an unchanged file answers 304 in a couple of hundred
# bytes, and the service worker means it usually is not asked at all.
#
# Icons are different. They are content, not code, they change roughly never,
# and nothing depends on them being current. A week costs one request a week.
_CACHE_BY_SUFFIX = {
    ".png": "public, max-age=604800",
    ".ico": "public, max-age=604800",
    ".svg": "public, max-age=604800",
    ".woff2": "public, max-age=604800, immutable",
}


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    """Starlette's StaticFiles sends ETag and Last-Modified but no
    Cache-Control, which leaves the decision to browser heuristics. Being
    explicit is free and makes the behaviour the same everywhere."""
    response = await call_next(request)
    if "cache-control" not in response.headers:
        suffix = Path(request.url.path).suffix
        response.headers["Cache-Control"] = _CACHE_BY_SUFFIX.get(suffix, "no-cache")
    return response


app.include_router(api, prefix=BASE)
app.mount(f"{BASE}/", StaticFiles(directory=STATIC, html=True), name="static")


@app.get("/")
async def root_redirect():
    return RedirectResponse(f"{BASE}/" if BASE else "/index.html")


@app.get("/healthz")
async def liveness():
    """For the container runtime. Says only that the process is up, which is
    all a liveness probe should ever claim -- /api/health is the opinionated
    one."""
    return {"ok": True}
