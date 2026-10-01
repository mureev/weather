"""City registry.

Places are addressed by **lat/lon, never by geoid.** `?geoid=` is vestigial on
the modern front end: passing `geoid=41` (which is genuinely Yoshkar-Ola)
returned weather for *Columbus, Ohio*, because Yandex geolocated the requesting
IP instead. It does not error. It just quietly serves the wrong city, which is
the worst failure mode there is.

The slug path (`/pogoda/ru/yoshkar-ola`) is preferred when we have one because
it is the least ambiguous, but every entry carries coordinates so there is
always a second way to ask.
"""

from __future__ import annotations

import logging
import re

from .config import settings
from .models import Place
from .ru_text import latin

log = logging.getLogger(__name__)

# slug, Russian name, lat, lon, yandex slug, English name. The English names
# are the ones English speakers use -- Moscow, not the transliterated Moskva.
_BUILTIN: tuple[tuple[str, str, float, float, str, str], ...] = (
    ("yoshkar-ola", "Йошкар-Ола", 56.6344, 47.8999, "yoshkar-ola", "Yoshkar-Ola"),
    ("cheboksary", "Чебоксары", 56.1439, 47.2489, "cheboksary", "Cheboksary"),
    ("kazan", "Казань", 55.7963, 49.1064, "kazan", "Kazan"),
    ("nizhny-novgorod", "Нижний Новгород", 56.3269, 44.0059, "nizhniy-novgorod",
     "Nizhny Novgorod"),
    ("moscow", "Москва", 55.7558, 37.6173, "moscow", "Moscow"),
    ("saint-petersburg", "Санкт-Петербург", 59.9311, 30.3609, "sankt-peterburg",
     "Saint Petersburg"),
)


def _parse_extra(spec: str) -> list[Place]:
    """`slug:Название:lat:lon[:yandex-slug]`, comma separated.

    A malformed entry is skipped with a warning rather than taking the app
    down. Losing one city is annoying; refusing to serve any weather because
    somebody fat-fingered a comma is worse.
    """
    out: list[Place] = []
    for raw in filter(None, (p.strip() for p in spec.split(","))):
        parts = raw.split(":")
        if len(parts) < 4:
            log.warning("EXTRA_CITIES: skipping malformed entry %r", raw)
            continue
        slug, name, lat, lon = parts[0], parts[1], parts[2], parts[3]
        ys = parts[4] if len(parts) > 4 else slug
        try:
            out.append(
                Place(slug=slug.strip(), name=name.strip(),
                      lat=float(lat), lon=float(lon), yandex_slug=ys.strip() or None,
                      name_en=latin(name.strip()))
            )
        except ValueError:
            log.warning("EXTRA_CITIES: bad coordinates in %r", raw)
    return out


REGISTRY: dict[str, Place] = {
    s: Place(slug=s, name=n, lat=la, lon=lo, yandex_slug=ys, name_en=en)
    for s, n, la, lo, ys, en in _BUILTIN
}
for _p in _parse_extra(settings.extra_cities):
    REGISTRY[_p.slug] = _p


def get(slug: str) -> Place | None:
    return REGISTRY.get((slug or "").strip().lower())


def default() -> Place:
    return REGISTRY.get(settings.default_city) or REGISTRY["yoshkar-ola"]


def listing() -> list[Place]:
    return list(REGISTRY.values())


_SLUG_BAD = re.compile(r"[^a-z0-9-]+")


def slugify_ru(name: str) -> str:
    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
        " ": "-", "-": "-", "'": "",
    }
    s = "".join(table.get(ch, ch) for ch in (name or "").lower())
    return _SLUG_BAD.sub("-", s).strip("-") or "place"


def ad_hoc(lat: float, lon: float, name: str | None = None) -> Place:
    """A place that isn't in the registry -- a GPS fix, or a search hit.

    Coordinates are rounded before they go anywhere. The client rounds too;
    doing it again here means a hand-crafted request cannot make us send,
    cache or log a precise fix -- except in uvicorn's access log, which writes
    the request line down as it arrived, before any of this runs.
    """
    p = settings.coord_precision
    lat, lon = round(float(lat), p), round(float(lon), p)
    label = name or f"{lat:.2f}, {lon:.2f}"
    return Place(
        slug=f"@{lat:.2f},{lon:.2f}",
        name=label,
        lat=lat,
        lon=lon,
        yandex_slug=None,
        ad_hoc=True,
        name_en=latin(label),
    )


def nearest(lat: float, lon: float, max_km: float = 25.0) -> Place | None:
    """If a GPS fix lands near a registry city, prefer the registry entry --
    it has a verified Yandex slug, which is a more reliable way to ask than
    raw coordinates."""
    best, best_d = None, float("inf")
    for p in REGISTRY.values():
        d = _haversine_km(lat, lon, p.lat, p.lon)
        if d < best_d:
            best, best_d = p, d
    return best if best is not None and best_d <= max_km else None


def _haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    dlat = radians(b_lat - a_lat)
    dlon = radians(b_lon - a_lon)
    h = sin(dlat / 2) ** 2 + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(h))
