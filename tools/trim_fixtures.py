#!/usr/bin/env python3
"""Cut a recorded upstream page down to what this app's parsers read.

**Why this exists.** The pages in `tests/fixtures/` are test input: real
captures from Yandex and Gismeteo/Meteofor that the parsers are run against,
because markup typed out by hand only tests what somebody believed the page
said. A capture is also a complete copy of somebody else's site -- its markup,
scripts, trackers, adverts and news teasers -- and a public repository has no
business redistributing that. So a recorded page is passed through this
before it is committed: what the parsers in `app/` read stays, with the few
passages the tests read as an independent second opinion, and the rest of the
page is not reproduced. The `make fixtures*` recipes run it on every recording.

    python3 tools/trim_fixtures.py tests/fixtures/current.html [...]
    python3 tools/trim_fixtures.py --check tests/fixtures/*.html

**What survives.** Every element one of the parsers' own XPaths can match,
whole -- the lists in `KEEP` are those XPaths, copied from the functions named
beside them -- and the bare tags of its ancestors, so each surviving piece
keeps its place in the document. Of the inline scripts, only the payloads a
parser decodes:

* Yandex's RSC flight stream (`self.__next_f.push([1, "..."])`) is the whole
  page a second time, encoded for React. `extract.py` takes four values out of
  it -- `locality`, `locationLinguistics`, the `slug`/`lat`/`lon` triple and
  `fact` -- so the pushes holding any part of those survive, with the one
  holding `userLocationLaasFact`: the weather where Yandex thinks the
  *requester* is, which the tests exist to prove is never read, and which can
  only prove it while it is there to be refused. The per-day page's stream is
  read by nothing and goes entirely.
* Gismeteo's `window.M.state` keeps what `gismeteo.py` reads of it, `city`
  and `weather.cw`, byte for byte; the site menu, ad config, translation
  tables and widget schema go.

Each trimmed page opens with a comment saying so. On Gismeteo pages it also
gives the page's own clock (`<time-value class="current-time">`) as an ISO
date, because `test_the_sources_overlap` decides whether two recordings
describe the same days from the ISO dates in the raw pages, and the only ones
the ten-day page carried were the publication dates of the news teasers this
removes.

**How it cuts.** By splicing the recorded text, never by re-serialising a
parsed tree: every byte that survives is the byte that was recorded. That is
not fastidiousness. The tests read the raw markup with regexes as a second
opinion on the parsers (`_row_pairs`, `_page_now`, the year in
`_recorded_date`), and a serialiser turns `&nbsp;` into a character `\\s`
matches, rewrites quotes and lower-cases attribute names -- each a way for a
regex that matched one thing to start matching another. Cutting only removes
text, so a first match that survives is still the first match. React's empty
`<!-- -->` comments survive too, inside kept elements: they split text nodes,
and `itertext()` -- which is how the day cards' prose is cut into lines -- would
see two lines run together without them.

The splice needs to know where every element starts and ends in the text, and
`html.parser` says; lxml decides what to keep, because lxml is what the
parsers use. The two are paired start tag by start tag, and must agree on
every one. They need not agree on nesting, and on Yandex they do not: its
`<h1>` holds a `<p>`, which libxml2 reads as closing the heading. A kept
element is therefore cut from its start tag to the end tag that closes it *in
the text*, which carries such quirks along whole, so lxml reads the cut-out
piece exactly as it read the page. That is checked rather than assumed: every
element a `KEEP` XPath matches must serialise identically, as lxml sees it, in
the recording and in the trimmed page, or nothing is written.

**Why it can be trusted.** After cutting, the original and the trimmed page
are both run through the app's parsers -- for Yandex once more with each
extraction tier removed, exactly as `tests/test_ladder.py` removes them, and
for Gismeteo with the state blob, the `data-row` keys, the captions and the
header sentence removed in turn -- and the readings must be identical, field
for field. If they are not, a redesign has moved something these lists do not
know about, and nothing is written. Nor is it for a page the parsers cannot
read at all. Either way the recording is left exactly as it came, to fix the
parser against -- and must not be committed like that. Where the app itself
cannot be imported (lxml present but not httpx, say) the check is skipped with
a warning, and `make check` is the backstop.

Idempotent: a trimmed page comes out byte for byte as it went in.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import datetime as dt
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from lxml import etree
from lxml import html as LH

ROOT = Path(__file__).resolve().parent.parent

# A class matched as a whole token, the way `gismeteo._TOKEN` matches it.
_TOKEN = '//*[contains(concat(" ", normalize-space(@class), " "), " {} ")]'
_HEAD = ("/html/head/meta[@charset]",                         # still says utf-8
         "/html/head/title", '//link[@rel="canonical"]')      # identity checks

KEEP: dict[str, tuple[str, ...]] = {
    "yandex": (
        *_HEAD,
        "//h1",                                               # extract.identity
        '//*[contains(@class,"AppFact_temperature")]',        # extract._current_from_dom
        '//*[contains(@class,"AppFact_feels")]',
        '//*[contains(@class,"AppFact_warning")]',            # ... and extract._nowcast
        '//*[contains(@class,"AppFact_details")]',
        '//*[contains(@class,"AppForecastDay_dayCard")]',     # extract._days
        '//*[contains(@class,"AppForecastDay_container")]',
        '//*[contains(@class,"AppHourlyItem_container")]',    # extract._hours
        # Read by no parser: the page's own prose about now («Сейчас в
        # Йошкар-Оле пасмурно, температура воздуха +9°...»), which
        # test_extract holds the parsed reading against.
        '//*[contains(@class,"AppWeatherFAQ_section")]',
    ),
    "yandex-day": (
        *_HEAD,
        "//time[@datetime]",                                  # yandex_day._stamps
        '//*[contains(@class,"AppDetailedForecastBlock_block__")]',   # _columns
        '//*[contains(@class,"AppDetailsCard_table")]',       # yandex_day._astronomy
    ),
    "gismeteo": (
        *_HEAD,
        "//h1",                                               # gismeteo._identity
        _TOKEN.format("place"),                               # gismeteo._place_line
        _TOKEN.format("current-time"),                        # gismeteo._now_column
        "//temperature-value[@value]",                        # gismeteo._current, tier 3
        '//*[contains(@class,"widget-row")]',                 # _hours, _days, _parts, _find_row
        "//*[@data-row]",                                     # gismeteo._find_row, tier 1
    ),
}

# Inside a kept element these still go: nothing reads them, a script is exactly
# the kind of thing this is here to not redistribute, and a `/cdn-cgi/` link
# is Cloudflare's decoy for scrapers. (Yandex's FAQ block carries its own text
# again as JSON-LD; that is the only one on the pages recorded so far.)
_JUNK = frozenset({"script", "style", "noscript", "iframe"})
_JUNK_XPATH = ("|".join(f".//{t}" for t in sorted(_JUNK))
               + '|.//a[contains(@href,"/cdn-cgi/")]')

# The flight stream exactly as `extract.flight` reads it -- run over the whole
# page, not script by script, so a push that never closes swallows what
# follows here just as it does there.
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,\s*(".*?")\]\)', re.S)
# What `extract.identity` and `extract._current_from_flight` look up in it,
# and the decoy the tests prove is never read.
_FLIGHT_KEYS = re.compile(
    r'"(?:locality|locationLinguistics|userLocationLaasFact)"\s*:\s*'
    r'|(?<![A-Za-z])"fact"\s*:\s*')
_SLUG_LAT_LON = re.compile(r'"slug"\s*:\s*"[a-z0-9-]+"\s*,\s*"lat"\s*:\s*-?[\d.]+'
                           r'\s*,\s*"lon"\s*:\s*-?[\d.]+')

_STATE = re.compile(r"window\.M\.state\s*=\s*")               # gismeteo.state
# All `gismeteo.py` ever asks of it: `city` (identity, time zone, the
# prepositional name) whole, and `weather.cw`, the current conditions when the
# site still sends them. None means the whole value.
_STATE_KEEP: dict[str, tuple[str, ...] | None] = {"city": None, "weather": ("cw",)}

_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input",
                   "keygen", "link", "meta", "param", "source", "track", "wbr"})


class TrimError(Exception):
    """A page this tool will not cut. It is left as recorded."""


# --- where everything is ----------------------------------------------------

class _Node:
    """One element and where it sits in the recorded text."""

    __slots__ = ("children", "close", "el", "end", "open_end", "parent",
                 "start", "tag")

    def __init__(self, tag: str, start: int, open_end: int,
                 parent: _Node | None) -> None:
        self.tag, self.start, self.open_end, self.parent = tag, start, open_end, parent
        self.close = self.end = open_end   # where the end tag starts / ends
        self.children: list[_Node] = []
        self.el: Any = None                # the same element, as lxml sees it


class _Tree(HTMLParser):
    """Every element's offsets: start tag, end tag, children.

    Nested the way the text is written, which is not always the way libxml2
    reads it -- see the module docstring for why that is the right extent to
    cut by.
    """

    def __init__(self, raw: str) -> None:
        super().__init__(convert_charrefs=True)
        self.raw = raw
        self.lines = [0] + [m.end() for m in re.finditer("\n", raw)]
        self.root = _Node("#document", 0, 0, None)
        self.stack = [self.root]
        self.elements: list[_Node] = []
        self.doctype = ""
        self.feed(raw)
        self.close()
        for n in self.stack:               # whatever is open at the end of the file
            n.close = n.end = len(raw)

    def _at(self) -> int:
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def _open(self, tag: str, empty: bool) -> None:
        start = self._at()
        node = _Node(tag, start, start + len(self.get_starttag_text() or ""),
                     self.stack[-1])
        self.stack[-1].children.append(node)
        self.elements.append(node)
        if not empty:
            self.stack.append(node)

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        self._open(tag, tag in _VOID)

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        self._open(tag, True)              # `<path/>`: libxml2 reads it as empty too

    def handle_endtag(self, tag: str) -> None:
        at = self._at()
        if not self.raw.startswith("</", at):
            raise TrimError(f"lost track of the text at the </{tag}> near character {at}")
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                for n in self.stack[i + 1:]:          # closed by implication, here
                    n.close = n.end = at
                self.stack[i].close = at
                self.stack[i].end = self.raw.index(">", at) + 1
                del self.stack[i:]
                return
        # A stray end tag closes nothing, for lxml as for browsers.

    def handle_decl(self, decl: str) -> None:
        if not self.doctype and decl.lower().startswith("doctype"):
            self.doctype = f"<!{decl}>"


def _aligned(raw: str) -> tuple[_Tree, Any]:
    """Both views of the page, start tag for start tag, or `TrimError`."""
    tree = _Tree(raw)
    doc = LH.document_fromstring(raw)
    els = [e for e in doc.iter() if isinstance(e.tag, str)]
    for i, (n, e) in enumerate(zip(tree.elements, els, strict=False)):
        if n.tag != e.tag or not raw.startswith("<", n.start):
            raise TrimError(f"start tag #{i} is <{n.tag}> at character {n.start} to "
                            f"html.parser and <{e.tag}> to lxml")
        n.el = e
    if len(tree.elements) != len(els):
        raise TrimError(f"html.parser sees {len(tree.elements)} start tags and lxml "
                        f"{len(els)} elements")
    return tree, doc


def _kept(doc: Any, kind: str) -> list[str]:
    """Every element a `KEEP` XPath matches, as lxml reads it, less its junk."""
    out = []
    for xp in KEEP[kind]:
        for e in doc.xpath(xp):
            if not isinstance(e, LH.HtmlElement):
                continue
            if e.xpath(_JUNK_XPATH):
                e = copy.deepcopy(e)
                for j in e.xpath(_JUNK_XPATH):
                    j.drop_tree()          # its tail stays, as it does in the cut
            out.append(etree.tostring(e, encoding="unicode", with_tail=False))
    return out


# --- what to keep -----------------------------------------------------------

def kind_of(doc: Any, raw: str) -> str:
    """Which page this is. Not by file name: a recording is checked as it lands."""
    if doc.xpath('//*[contains(@class,"AppDetailedForecastBlock_block__")]'):
        return "yandex-day"
    if doc.xpath('//*[contains(@class,"AppForecastDay_") or contains(@class,"AppFact_")]'):
        return "yandex"
    if doc.xpath('//*[contains(@class,"widget-row")]') or _STATE.search(raw):
        return "gismeteo"
    raise TrimError("not a page this tool knows: Yandex /pogoda, its per-day page, "
                    "or Gismeteo/Meteofor")


def _balanced(s: str, start: int) -> str | None:
    """The `{...}`/`[...]` literal at `start` -- `extract._balanced`, copied so
    trimming needs nothing but lxml."""
    if start >= len(s) or s[start] not in "{[":
        return None
    opener, closer = s[start], "}" if s[start] == "{" else "]"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def _flight_pushes(raw: str, scripts: list[_Node]) -> set[_Node]:
    """The push scripts holding any part of a value something reads.

    A push that does not decode is skipped by `extract.flight`, so it is
    dropped here; on the pages recorded so far those were the two analytics
    scripts riding in the stream. Spans rather than key positions, so a value
    split across two pushes keeps both.
    """
    chunks: list[tuple[int, int, str]] = []         # raw start, raw end, decoded
    for m in _PUSH.finditer(raw):
        try:
            chunks.append((m.start(), m.end(), json.loads(m.group(1))))
        except ValueError:
            continue
    stream, bounds, at = [], [], 0
    for _, _, text in chunks:
        stream.append(text)
        bounds.append((at, at + len(text)))
        at += len(text)
    s = "".join(stream)
    spans = []
    for m in _FLIGHT_KEYS.finditer(s):
        spans.append((m.start(), m.end() + len(_balanced(s, m.end()) or "")))
    first = _SLUG_LAT_LON.search(s)                   # only the first is read
    if first:
        spans.append(first.span())
    keep: set[_Node] = set()
    for (a, b), (start, end, _) in zip(bounds, chunks, strict=True):
        if any(a < y and x < b for x, y in spans):
            keep |= {n for n in scripts if n.start < end and start < n.end}
    return keep


def _members(obj: str) -> list[str]:
    """`{"a":1,"b":{...}}` -> `['"a":1', '"b":{...}']`, each verbatim."""
    out, depth, start, in_str, esc = [], 0, 1, False, False
    for i, ch in enumerate(obj):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                out.append(obj[start:i])
        elif ch == "," and depth == 1:
            out.append(obj[start:i])
            start = i + 1
    return [m.strip() for m in out if m.strip()]


def _pick(obj: str, keep: dict[str, Any]) -> str:
    """The members of the JSON object `obj` named in `keep`, each verbatim --
    or, where `keep` names sub-keys, cut down the same way."""
    out = []
    for mem in _members(obj):
        key, at = json.JSONDecoder().raw_decode(mem)
        if key not in keep:
            continue
        value = mem[mem.index(":", at) + 1:].strip()
        if keep[key] is not None and value.startswith("{"):
            mem = mem[:at] + ":" + _pick(value, dict.fromkeys(keep[key]))
        out.append(mem)
    return "{" + ",".join(out) + "}"


def _state(raw: str, scripts: list[_Node]) -> dict[_Node, str]:
    """The script carrying `window.M.state`, rewritten to what it is read for."""
    m = _STATE.search(raw)
    blob = _balanced(raw, m.end()) if m else None
    if blob is None:
        return {}
    node = next((n for n in scripts if n.open_end <= m.start() < n.close), None)
    if node is None:
        raise TrimError("window.M.state is not inside a <script>")
    whole, small = json.loads(blob), _pick(blob, _STATE_KEEP)
    want = {k: ({s: whole[k][s] for s in sub if s in whole[k]}
                if sub is not None and isinstance(whole[k], dict) else whole[k])
            for k, sub in _STATE_KEEP.items() if k in whole}
    if json.loads(small) != want:
        raise TrimError("could not cut window.M.state down without changing it")
    return {node: f"window.M.state = {small}"}


def _clock(doc: Any) -> str:
    """Gismeteo's own clock, `<time-value class="current-time" timestamp>`."""
    for ts in doc.xpath(_TOKEN.format("current-time") + "/@timestamp"):
        if ts.isdigit():
            when = dt.datetime.fromtimestamp(int(ts), tz=dt.UTC)
            return f" The page's own clock: {when:%Y-%m-%dT%H:%M:%SZ}."
    return ""


def trim(raw: str) -> tuple[str, str]:
    """The trimmed page, and which kind of page it was."""
    tree, doc = _aligned(raw)
    kind = kind_of(doc, raw)
    node_of = {n.el: n for n in tree.elements}
    keep = {node_of[e] for xp in KEEP[kind] for e in doc.xpath(xp)
            if isinstance(e, LH.HtmlElement) and e in node_of}
    scripts = [n for n in tree.elements if n.tag == "script"]
    rewrite: dict[_Node, str] = {}
    if kind == "yandex":
        keep |= _flight_pushes(raw, scripts)
    elif kind == "gismeteo":
        rewrite = _state(raw, scripts)
    if not keep - {node_of[e] for xp in _HEAD for e in doc.xpath(xp)}:
        raise TrimError(f"nothing a parser reads was found on this {kind} page")

    def inside(n: _Node, nodes: set[_Node]) -> bool:
        p = n.parent
        while p is not None:
            if p in nodes:
                return True
            p = p.parent
        return False

    keep = {n for n in keep if not inside(n, keep)}            # outermost only
    shells: set[_Node] = set()
    for n in (*keep, *rewrite):
        p = n.parent
        while p is not None and p not in shells:
            shells.add(p)
            p = p.parent

    note = ("<!-- Test fixture, trimmed by tools/trim_fixtures.py to what the "
            "parsers in app/ and the tests read; the rest of the recorded page "
            f"is not reproduced.{_clock(doc) if kind == 'gismeteo' else ''} -->")

    def whole(n: _Node) -> str:
        """`n` as recorded, less any junk inside it."""
        cuts, todo = [], list(n.children)
        while todo:
            c = todo.pop()
            if c.tag in _JUNK or (c.tag == "a" and "/cdn-cgi/" in (c.el.get("href") or "")):
                cuts.append(c)
            else:
                todo.extend(c.children)
        out, at = [], n.start
        for c in sorted(cuts, key=lambda c: c.start):
            out.append(raw[at:c.start])
            at = c.end
        out.append(raw[at:n.end])
        return "".join(out)

    def emit(n: _Node) -> str:
        if n in keep:
            return whole(n)
        if n in rewrite:
            return raw[n.start:n.open_end] + rewrite[n] + raw[n.close:n.end]
        if n not in shells and n.tag not in ("html", "head", "body"):
            return ""
        parts = [s for s in map(emit, n.children) if s]
        if n.tag == "head":
            parts.insert(0, note)
        inner = "".join(f"\n{s}" for s in parts) + ("\n" if parts else "")
        return raw[n.start:n.open_end] + inner + raw[n.close:n.end]

    body = "".join(s for s in map(emit, tree.root.children) if s)
    out = f"{tree.doctype}\n{body}\n" if tree.doctype else f"{body}\n"
    if _kept(LH.document_fromstring(out), kind) != _kept(doc, kind):
        raise TrimError("an element the parsers read does not survive the cut "
                        "intact -- the markup nests in a way this tool does not "
                        "handle yet")
    return out, kind


# --- the proof --------------------------------------------------------------

def _parsers() -> tuple[Any, str | None]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from app import extract
        from app.sources import gismeteo, yandex_day
    except Exception as e:  # anything at all: the check is optional
        return None, f"{type(e).__name__}: {e}"
    return (extract, gismeteo, yandex_day), None


def _plain(x: Any) -> Any:
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return _plain(dataclasses.asdict(x))
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    return x


def _try(fn: Any, *a: Any, **kw: Any) -> Any:
    try:
        return _plain(fn(*a, **kw))
    except Exception as e:  # a refusal is a reading too, and must match
        return f"raises {type(e).__name__}: {e}"


# The ladder, verbatim from tests/test_ladder.py.
_NO_FLIGHT = re.compile(r"self\.__next_f\.push\(\[1,.*?\]\)", re.S)
_NO_A11Y = re.compile(r'class="([^"]*\bvisuallyHidden\b[^"]*)"')


def readings(kind: str, html: str, parsers: Any, today: dt.date) -> dict[str, Any]:
    """Everything the parsers make of `html`, with each fallback forced too.

    `today` is passed in, not read here, so the two pages being compared are
    read as of the same day even if midnight falls between them.
    """
    X, G, YD = parsers
    if kind == "yandex":
        bare = _NO_FLIGHT.sub("", html)
        return {
            "as recorded": _try(X.parse, html, today=today),
            "tier 1 removed": _try(X.parse, bare, today=today),
            "tier 2 removed": _try(X.parse, _NO_A11Y.sub('class="gone"', html), today=today),
            "tiers 1 and 2 removed": _try(X.parse, _NO_A11Y.sub('class="gone"', bare),
                                          today=today),
        }
    if kind == "yandex-day":
        stamps = YD._stamps(LH.fromstring(html))
        want = stamps[0].date() if stamps else today
        return {"as recorded": _try(YD.parse, html, want=want)}

    st = G.state(html) or {}

    def grid(doc: Any, st: dict) -> dict[str, Any]:
        return {
            "identity": _try(G._identity, doc, st),
            "current": _try(G._current, doc, st),
            "hours": _try(G._hours, doc, st),
            "days": _try(G._days, doc, today=today),
            "parts": _try(G._parts, doc, today=today),
        }

    def without(xpath: str, change: Any) -> dict[str, Any]:
        doc = LH.fromstring(html)
        for e in doc.xpath(xpath):
            change(e)
        return grid(doc, st)

    return {
        "state read": {"city": st.get("city"),
                       "cw": (st.get("weather") or {}).get("cw")},
        "as recorded": grid(LH.fromstring(html), st),
        "landing page": _try(G.parse, html, today=today),
        "no state blob": grid(LH.fromstring(html), {}),
        "no data-row": without("//*[@data-row]", lambda e: e.attrib.pop("data-row")),
        "no captions": without('//*[contains(@class,"widget-row-caption")]',
                               lambda e: e.set("class", "gone")),
        "no header sentence": without(_TOKEN.format("place"),
                                      lambda e: e.drop_tree()),
    }


def _read_nothing(kind: str, r: dict[str, Any]) -> bool:
    got = r["as recorded"]
    if kind != "gismeteo":
        return isinstance(got, str)                  # it raised
    return not any(isinstance(got[k], list) and got[k] and got[k][0]
                   for k in ("current", "hours", "days", "parts"))


def _diff(a: Any, b: Any, path: str = "") -> str:
    """Where two readings first part company."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in [*a, *(k for k in b if k not in a)]:
            if a.get(k) != b.get(k):
                return _diff(a.get(k), b.get(k), f"{path}.{k}" if path else k)
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            if x != y:
                return _diff(x, y, f"{path}[{i}]")
    return f"{path or 'reading'}: {a!r:.200} became {b!r:.200}"


# --- the command ------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pages", nargs="+", type=Path)
    ap.add_argument("--check", action="store_true",
                    help="change nothing; exit 1 if any page is not trimmed yet")
    args = ap.parse_args(argv)

    parsers, why = (None, None) if args.check else _parsers()
    if why:
        print(f"warning: the app does not import here ({why}), so the trimmed "
              f"pages are NOT checked against the parsers. `make check` will.")
    failed = False
    for path in args.pages:
        raw = path.read_text(encoding="utf-8", errors="replace")
        try:
            out, kind = trim(raw)
            if trim(out)[0] != out:
                raise TrimError("trimming it twice gives a different page -- a bug here")
        except TrimError as e:
            print(f"{path}: {e}. Left as recorded -- do not commit it like this.")
            failed = True
            continue
        size = f"{len(raw.encode()):,}"
        if out == raw:
            print(f"{path}: already trimmed ({size} bytes)")
            continue
        if args.check:
            print(f"{path}: not trimmed ({size} bytes)")
            failed = True
            continue
        if parsers is not None:
            today = dt.date.today()
            before = readings(kind, raw, parsers, today)
            if _read_nothing(kind, before):
                print(f"{path}: the parsers read nothing from this {kind} page. Left "
                      f"as recorded, to fix the parser against -- do not commit it "
                      f"like this.")
                failed = True
                continue
            after = readings(kind, out, parsers, today)
            if after != before:
                print(f"{path}: trimming would change what the parsers read -- "
                      f"{_diff(before, after)}. Left as recorded; teach KEEP in "
                      f"{Path(__file__).name} about whatever moved.")
                failed = True
                continue
        path.write_text(out, encoding="utf-8", newline="")
        print(f"{path}: {size} -> {len(out.encode()):,} bytes ({kind})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
