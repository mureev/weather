"""The launch screen, drawn as the app's own sky.

**The splash cannot be turned off.** On iOS and Android alike it is part of the
operating system's app-launch model, the same screen a native app gets, and
there is no opt-out short of not being an installed app at all. So the question
is not whether it appears but what it contains.

Left alone, iOS generates one from the manifest's `background_color`: a flat
rectangle, held while the web view boots, then replaced by a gradient. Two
different pictures, and the eye reads the change as "a splash screen happened".
Supply `apple-touch-startup-image` and iOS holds *that* instead -- so if the
image is the gradient the app is about to draw, the handover is invisible and
there is nothing to notice.

The images are generated here rather than committed, for the reason this
project avoids committed binaries generally: fifteen PNGs that must be
regenerated whenever the palette moves are fifteen chances to forget. These are
computed from the same numbers, at request time, and cached.

**No new dependency.** A PNG is length-prefixed chunks around zlib-compressed
scanlines, and `zlib` and `binascii` are both stdlib. Pillow would be 3 MB to
draw a vertical gradient, on an image we had just spent an afternoon shrinking.
The encoder below is the whole format, minus everything a gradient does not
need: no palette, no interlacing, no alpha.
"""

from __future__ import annotations

import binascii
import struct
import zlib

# The gradient, in the same numbers the stylesheet uses. Written twice because
# CSS cannot draw a PNG and Python cannot read a stylesheet; a test asserts the
# two agree, which is this codebase's standing answer to that problem.
DARK = {"sky1": "#0d1630", "sky2": "#0a1020", "bg": "#0a1020", "hold": 0.0}
LIGHT = {"sky1": "#3f6ba6", "sky2": "#eef2fa", "bg": "#eef2fa", "hold": 0.34}

# Every iPhone still plausibly running this, portrait only. Landscape is
# omitted deliberately: nobody holds a weather app sideways, and an unmatched
# device falls back to the generated splash, which is already the right colour.
# That graceful fallback is why an incomplete list here is safe -- and it will
# be incomplete, because Apple ships new sizes every autumn.
DEVICES: tuple[tuple[int, int, int], ...] = (
    (440, 956, 3),   # 16 Pro Max, 15 Pro Max
    (430, 932, 3),   # 16 Plus, 15 Plus, 14 Pro Max
    (402, 874, 3),   # 16 Pro
    (393, 852, 3),   # 16, 15, 15 Pro, 14 Pro
    (390, 844, 3),   # 14, 13, 13 Pro, 12, 12 Pro
    (428, 926, 3),   # 13 Pro Max, 12 Pro Max
    (375, 812, 3),   # 13 mini, 12 mini, X, XS, 11 Pro
    (414, 896, 3),   # XS Max, 11 Pro Max
    (414, 896, 2),   # XR, 11
    (414, 736, 3),   # 8 Plus
    (375, 667, 2),   # SE (2nd/3rd), 8, 7, 6s
)

_cache: dict[tuple[int, int, str], bytes] = {}


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _row_colour(t: float, palette: dict) -> tuple[int, int, int]:
    """The gradient at fraction `t` down the screen.

    Mirrors `--skygrad`: hold `sky1` to `hold`, ramp to `sky2` at 62%, then
    ramp to `bg` for the rest. Linear in sRGB, which is not how light works but
    is exactly what the browser does -- and matching the browser is the entire
    point of this file.
    """
    stops = ((palette["hold"], _rgb(palette["sky1"])),
             (0.62, _rgb(palette["sky2"])),
             (1.0, _rgb(palette["bg"])))
    if t <= stops[0][0]:
        return stops[0][1]
    lo_t, lo_c = stops[0]
    for hi_t, hi_c in stops[1:]:
        if t <= hi_t or hi_t == 1.0:
            span = hi_t - lo_t
            f = 0.0 if span <= 0 else (t - lo_t) / span
            f = min(max(f, 0.0), 1.0)
            return tuple(round(a + (b - a) * f) for a, b in zip(lo_c, hi_c, strict=True))
        lo_t, lo_c = hi_t, hi_c
    return stops[-1][1]


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF))


def gradient_png(width: int, height: int, scheme: str = "dark") -> bytes:
    """A vertical gradient as an 8-bit truecolour PNG.

    Every scanline is a single colour, so the Up filter makes all but the first
    row a run of zero bytes and zlib reduces a megabyte of pixels to a couple of
    kilobytes. Which is the only reason generating these on demand is sensible.
    """
    key = (width, height, scheme)
    if key in _cache:
        return _cache[key]

    palette = LIGHT if scheme == "light" else DARK
    previous = (0, 0, 0)
    raw = bytearray()
    for y in range(height):
        r, g, b = _row_colour(y / max(height - 1, 1), palette)
        # Filter 2 (Up): this pixel minus the one above. Identical rows become
        # zeros; only the first row and the gradient's slow drift cost anything.
        delta = bytes(((r - previous[0]) & 0xFF, (g - previous[1]) & 0xFF,
                       (b - previous[2]) & 0xFF))
        raw += b"\x02" + delta * width
        previous = (r, g, b)

    png = (b"\x89PNG\r\n\x1a\n"
           + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + _chunk(b"IEND", b""))
    _cache[key] = png
    return png


def link_tags(base: str) -> str:
    """The `<link>` elements iOS matches against, one per device size.

    iOS picks a startup image only on an exact media match -- device width,
    height and pixel ratio -- and silently uses its generated splash otherwise.
    That is unforgiving, and also why the list not being exhaustive is safe.
    """
    out = []
    for w, h, dpr in DEVICES:
        media = (f"(device-width: {w}px) and (device-height: {h}px) and "
                 f"(-webkit-device-pixel-ratio: {dpr}) and (orientation: portrait)")
        for scheme in ("dark", "light"):
            out.append(
                f'<link rel="apple-touch-startup-image" media="{media} and '
                f'(prefers-color-scheme: {scheme})" '
                f'href="{base}/splash/{w * dpr}x{h * dpr}-{scheme}.png">')
    return "\n".join(out)
