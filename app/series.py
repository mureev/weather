"""Operations on an hourly series.

One function, and it exists because the same question got answered twice in two
different ways and the two disagreed in production.

The question is "which of these entries describes this instant". The parser
needed it to attach a condition to the current reading; the coherence validator
needed it to check that the two agree. Written separately, the parser matched on
the real timestamps the page ships and the validator matched on hour labels with
a wraparound -- so on a reading taken at 23:00 against a strip running
00:00..21:00, the parser said 21:00 and the validator said 00:00, and the app
reported itself broken on every fetch.

Both were defensible. Only one could be right. That is the whole argument for
this module existing: `DECISIONS.md` already carries an entry about a constant
written down twice, and this was the same failure in logic rather than in a
number -- which is harder to spot and no less certain to diverge.
"""

from __future__ import annotations

import datetime as dt

from .models import Hour
from .sun import zone


def covering(hours: list[Hour], when: int | None,
             tz: str | None = None) -> Hour | None:
    """The entry describing the instant `when` (a UTC epoch), or None.

    Prefers the real timestamps in `Hour.at`, which are unambiguous. Falls back
    to the hour labels only when no entry carries one, and then refuses to
    answer unless a label lands within an hour of the target -- because the
    fallback cannot tell which side of midnight a bare "00:00" belongs to, and
    a confident wrong answer here is exactly the bug that started all this.

    Returning None is a real answer and callers must handle it. "I cannot line
    these up" is worth more than a plausible mismatch.
    """
    if not hours or when is None:
        return None

    stamped = [h for h in hours if h.at is not None]
    if stamped:
        return min(stamped, key=lambda h: abs(h.at - when))

    if tz is None:
        # No timestamps and no clock to interpret the labels against. Refusing
        # is the answer; guessing is how this module came to exist.
        return None
    target = dt.datetime.fromtimestamp(int(when), tz=zone(tz))
    best, best_gap = None, None
    for h in hours:
        hh = label_hour(h.time)
        if hh is None:
            continue
        gap = min((hh - target.hour) % 24, (target.hour - hh) % 24)
        if best_gap is None or gap < best_gap:
            best, best_gap = h, gap
    return best if best_gap is not None and best_gap <= 1 else None


def label_hour(text: str | None) -> int | None:
    """The hour out of `"21:00"` or `"2026-07-31T21:00"`."""
    t = (text or "").strip()
    try:
        return int(t[11:13]) if "T" in t else int(t.split(":")[0])
    except (ValueError, IndexError):
        return None


def align_to_now(hours: list[Hour], current, when: int | None,
                 tz: str | None = None) -> list[Hour]:
    """Trim the series to start at the present hour, and put it there if absent.

    The three sources disagree about what an "hourly forecast" begins with, and
    each is reasonable on its own page:

    * Gismeteo's `/hourly/` page runs from the **next** whole hour, because the
      page shows the current conditions in a separate card above it.
    * Open-Meteo returns the whole calendar day, so at 11:00 the first third of
      the series is already in the past.
    * Yandex starts at the current hour.

    Rendered identically by us, that produced a strip whose first column was
    the next hour on one tab, this morning on another, and now on the third --
    with the app labelling whichever came first "сейчас" until recently.

    So the series is normalised: drop what has already happened, and if nothing
    covers the present hour, put the *observation* at the head. That last part
    is not an invention. It is the same reading already shown in the hero, at
    the time it was taken, moved into the series it belongs to -- which is
    exactly what Gismeteo's own page does with its «Сейчас» card.

    Returns the list unchanged when there is no instant to align to. Guessing
    would be the alternative, and this module exists because of a guess.
    """
    if not hours or when is None:
        return hours

    zone_ = zone(tz) if tz else dt.UTC
    stamp = dt.datetime.fromtimestamp(int(when), tz=zone_)
    top_of_hour = int(stamp.replace(minute=0, second=0, microsecond=0).timestamp())

    def still_ahead(h: Hour) -> bool:
        if h.at is not None:
            return h.at >= top_of_hour
        hh = label_hour(h.time)
        return hh is None or hh >= stamp.hour

    def is_this_hour(h: Hour) -> bool:
        if h.at is not None:
            return top_of_hour <= h.at < top_of_hour + 3600
        return label_hour(h.time) == stamp.hour

    ahead = [h for h in hours if still_ahead(h)]
    if ahead and is_this_hour(ahead[0]):
        return ahead

    # Nothing covers the present hour: the source starts in the future. Lead
    # with what we actually observed rather than opening on a forecast and
    # calling it now.
    #
    # Note the rule this does *not* use: `covering` picks the entry nearest an
    # instant, which is right for "what should I compare this against" and
    # wrong here. At 11:20 against a strip beginning 12:00, the nearest entry
    # is 12:00 -- forty minutes away and firmly in the future. Nearest is not
    # the same question as covering, and conflating them left the strip opening
    # on the next hour with the current one missing entirely.
    if current is None or current.temp_c is None:
        return ahead or hours
    return [Hour(time=stamp.strftime("%H:%M"), at=int(when),
                 temp_c=current.temp_c, feels_like_c=current.feels_like_c,
                 condition=current.condition, icon=current.icon), *ahead]
