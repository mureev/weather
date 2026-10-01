"""Rules that survive the people who wrote them.

This project is edited by a long succession of sessions, each of which arrives
knowing nothing and leaves in an hour. Comments and `AGENTS.md` tell them the
rules; this file *enforces* them, because a rule that is only written down is a
rule that gets broken by someone acting in perfectly good faith.

Two kinds of check live here, and both are deliberately crude:

**Layering.** Which module may import what. Enforced on the import graph rather
than on behaviour, because the whole value of a boundary is that it holds even
when you cannot see why it matters.

**Never-agains.** Source-level assertions about mistakes that have actually been
made here. Grepping source in a test is not elegant. It is, however, the
cheapest possible way to make a specific past failure impossible to repeat, and
in a codebase whose main risk is a stranger silently undoing a hard-won fix,
that trade is a bargain. Each one names the failure it prevents; if you are
reading this because one failed, read *why* before deciding it is in your way.

If you need to break a rule here, change the rule deliberately and say why in
`DECISIONS.md`. Do not work around it.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
STATIC = ROOT / "static"

PY_MODULES = sorted(p for p in APP.rglob("*.py") if p.name != "__init__.py")


def module_name(path: Path) -> str:
    rel = path.relative_to(APP).with_suffix("")
    return ".".join(rel.parts)


def imports_of(path: Path) -> set[str]:
    """Every module this file imports, relative ones resolved to app-local
    dotted names so `from ..config import settings` reads as `config`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkg = module_name(path).rsplit(".", 1)[:-1]
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                out.add(node.module or "")
            else:
                base = pkg[: len(pkg) - node.level + 1]
                out.add(".".join([*base, node.module] if node.module else base))
    return {m for m in out if m}


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def code_only(path: Path) -> str:
    """The source with comments and docstrings blanked out.

    Necessary because half the rules below are about what the code *does*, and
    this codebase documents its own past mistakes at length -- a naive grep for
    `geoid=` finds the paragraph in `cities.py` explaining why you must never
    use it. A test that fires on its own warning label is worse than no test:
    the next session deletes the warning to get green.

    Line numbering is preserved so failures still point somewhere real.
    """
    text = source(path)
    lines = text.splitlines()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, holders) or not node.body:
            continue
        first = node.body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            for i in range(first.lineno - 1, (first.end_lineno or first.lineno)):
                lines[i] = ""
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            row, col = tok.start
            if lines[row - 1]:
                lines[row - 1] = lines[row - 1][:col]
    return "\n".join(lines)


def js_code_only(path: Path) -> str:
    """The same idea for JavaScript, and needed for the same reason.

    `app.js` documents the bug where 58px in the CSS met 54px in the JS -- by
    quoting both numbers. A grep for restated constants finds its own tombstone
    and fails, which teaches the next session to delete the explanation.
    """
    text = source(path)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(^|[^:\\])//.*$", r"\1", text, flags=re.M)


# --- layering ---------------------------------------------------------------

class TestNothingReachesUpward:
    """The dependency arrows in `AGENTS.md`, as code.

    A source adapter that imports the orchestrator can no longer be tested in
    isolation, and the next person to add a fourth source inherits the cycle.
    """

    UPWARD: ClassVar = {"service", "routing", "main"}

    @pytest.mark.parametrize("path", [p for p in PY_MODULES if "sources" in p.parts],
                             ids=lambda p: p.name)
    def test_a_source_adapter_knows_nothing_about_orchestration(self, path):
        bad = imports_of(path) & self.UPWARD
        assert not bad, f"{path.name} imports {bad}: adapters are leaves"

    @pytest.mark.parametrize("name", ["models", "ru_text", "sun", "cities"])
    def test_the_leaves_stay_leaves(self, name):
        """These are imported by nearly everything. If one of them starts
        importing back, every module in the project becomes coupled to it."""
        local = {m.split(".")[0] for m in imports_of(APP / f"{name}.py")}
        forbidden = local & {"service", "routing", "http", "extract", "sources",
                             "validation", "main"}
        assert not forbidden, f"{name}.py reaches up into {forbidden}"


class TestPureModulesStayPure:
    """`extract`, `ru_text`, `validation` and `sun` are pure functions over
    strings and numbers. That is why they can be tested exhaustively against
    real captured HTML with no network and no clock -- which is, in turn, the
    only reason this project's test suite is worth anything.

    The moment one of them fetches something, that property is gone and nobody
    notices until the suite starts needing the internet.
    """

    PURE: ClassVar = ["extract", "ru_text", "validation", "sun",
                      "models", "cities"]

    @pytest.mark.parametrize("name", PURE)
    def test_no_network_library(self, name):
        bad = imports_of(APP / f"{name}.py") & {"httpx", "requests", "urllib",
                                                "urllib.request", "aiohttp",
                                                "socket", "http.client"}
        assert not bad, f"{name}.py imports {bad}: it is supposed to be pure"

    @pytest.mark.parametrize("name", ["extract", "ru_text", "validation",
                                      "sources.gismeteo"])
    def test_the_clock_is_only_ever_a_default_for_an_argument(self, name):
        """A parser that reads `date.today()` internally gives a different
        answer in January than in July, and its tests pass in exactly one of
        them. Every date-dependent function here takes `today=`; the clock may
        appear *only* as that argument's default, which is why the fixtures can
        pin a day and the suite still means something in six months.

        The permitted idiom is exactly `today or dt.date.today()` -- caller
        wins, clock is the fallback. Anything else is a hidden dependency."""
        text = code_only(APP / Path(name.replace(".", "/")).with_suffix(".py"))
        text = re.sub(r"today\s+or\s+dt\.date\.today\(\)", "", text)
        leftovers = re.findall(r"(date\.today\(\)|datetime\.now\(|dt\.now\()", text)
        assert not leftovers, \
            f"{name} reads the clock outside an argument default: {leftovers}"


class TestSingleResponsibilityWhereItCosts:
    def test_only_http_py_builds_a_client(self):
        """One place configures the egress proxy, the timeout and HTTP/2.
        Two places means one of them will miss the proxy, and the symptom is a
        source that works locally and 403s on the server."""
        offenders = [p.name for p in PY_MODULES
                     if p.name != "http.py" and "AsyncClient(" in source(p)]
        assert not offenders, f"{offenders} construct their own httpx client"

    def test_only_main_py_imports_the_web_framework(self):
        """Keeps FastAPI at the edge. Everything below it is importable from a
        script, a test or a diagnostic without standing up an app."""
        offenders = [p.name for p in PY_MODULES
                     if p.name != "main.py" and "fastapi" in imports_of(p)]
        assert not offenders, f"{offenders} import fastapi"

    def test_the_app_logs_rather_than_prints(self):
        """`print` in a container goes nowhere useful and cannot be filtered by
        level. Diagnostics under tools/ are exempt: printing is their job."""
        offenders = [p.name for p in PY_MODULES
                     if re.search(r"^\s*print\(", source(p), re.M)]
        assert not offenders, f"{offenders} use print() instead of logging"

    def test_only_ru_text_decides_how_a_sentence_starts(self):
        """Capitalising a condition was written out by hand at eight call
        sites -- `cond[0].upper() + cond[1:]`, once per parser, once per series
        -- and the ninth path simply forgot. Gismeteo's tier-2 recovery reads
        the site's header sentence, where the phrase follows a city name and is
        lowercase, so switching tabs turned «Пасмурно» into «пасмурно».

        The bug was not any of the eight sites. It was that a rule with eight
        copies has no owner, and the tenth caller will forget too. Same species
        as `--hour-w` in two languages, and the same remedy: one place decides,
        everyone else asks.
        """
        idiom = re.compile(r"\[0\]\.upper\(\)\s*\+")
        offenders = [p.name for p in PY_MODULES
                     if p.name != "ru_text.py" and idiom.search(source(p))]
        assert not offenders, (
            f"{offenders} capitalise by hand; call `ru_text.sentence` instead")

    @pytest.mark.parametrize("path", PY_MODULES, ids=lambda p: p.name)
    def test_every_module_says_what_it_is_for(self, path):
        """The first thing a stranger reads. A module with no docstring is a
        module the next session will guess about."""
        doc = ast.get_docstring(ast.parse(source(path)))
        assert doc and len(doc) > 40, f"{path.name} has no useful module docstring"


# --- never again ------------------------------------------------------------

class TestMistakesThatCannotBeRepeated:
    """Each of these is a bug that shipped. The test is the tombstone."""

    def test_geoid_never_comes_back(self):
        """`?geoid=41` *is* Yoshkar-Ola and is ignored by the server, so it
        looks like it works while addressing nothing. Worse, `robots.txt`
        disallows query strings on Gismeteo. Address by slug or lat/lon.
        (`DECISIONS.md` §2)"""
        offenders = [p.name for p in PY_MODULES if "geoid=" in code_only(p)]
        assert not offenders, f"{offenders} address a page by geoid"

    def test_every_degree_pattern_guards_against_a_leading_digit(self):
        """`(\\d{1,2})\\s*°` reads `743°` as `+43`: a pressure value becomes a
        plausible temperature that passes every bounds check, reads plausibly,
        and is wrong. Any pattern matching a degree sign must refuse a
        preceding digit.

        Checked on the *compiled* pattern rather than the source text, because
        the guard is assembled from a fragment (`_G`) and a source-level grep
        would either miss it or be satisfied by the wrong thing."""
        from app import ru_text

        checked = 0
        for name in dir(ru_text):
            pattern = getattr(ru_text, name)
            if isinstance(pattern, re.Pattern) and "°" in pattern.pattern:
                checked += 1
                assert "(?<!" in pattern.pattern, \
                    f"ru_text.{name} matches ° with no lookbehind guard"
        assert checked, "no degree pattern found -- has the parser moved?"

    @pytest.mark.parametrize("model,table", [("Day", "DAY_CONTRACTS"),
                                             ("DayPart", "PART_CONTRACTS"),
                                             ("Hour", "HOUR_CONTRACTS")])
    def test_every_number_has_a_contract(self, model, table):
        """A numeric field with no entry in the contract table is unvalidated.

        Which sounds mild, and is not: unvalidated means an out-of-range value
        is *served*, and this app's entire argument is that it would rather
        show a blank than a plausible wrong number. Thirteen numeric fields
        arrived on `Day` in one sitting; the odds of remembering all thirteen
        in the validator by hand are not good, and nothing else would have
        noticed the omission -- the field would simply pass through.

        On its first run this found `precip_prob`, which had been on the model
        since the beginning and had never been checked.
        """
        from dataclasses import fields as dataclass_fields

        from app import models, validation

        cls = getattr(models, model)
        contracts = getattr(validation, table)
        numeric = {f.name for f in dataclass_fields(cls)
                   if "float" in str(f.type)}
        covered = {name for name, _ in contracts}
        assert not (numeric - covered), (
            f"unvalidated numeric fields on {model}: "
            f"{sorted(numeric - covered)}. Add them to validation.{table} with "
            f"the range they must satisfy -- a field with no contract is "
            f"served unchecked.")
        unknown = {rule for _, rule in contracts if rule not in validation.RANGES}
        assert not unknown, (
            f"{table} names rules that RANGES does not define: "
            f"{sorted(unknown)} -- these silently check nothing at all.")

    def test_every_icon_a_parser_can_emit_exists_in_the_shell(self):
        """An icon key with no `<symbol>` renders as the `unknown` glyph — a
        question mark where the weather should be, visible to the user and to
        no test.

        Found the other way round, which is worse: `cloudy-night` did not
        exist, so `nightify` quietly handed back the *day* form and the night
        rows of the day screen drew a sun at three in the morning. Nothing was
        missing on screen; the wrong thing was present. This walks every key
        the vocabulary can produce, in both day and night forms, against the
        symbols the shell actually defines.
        """
        from app import ru_text, sun

        symbols = set(re.findall(r'symbol id="i-([a-z-]+)"',
                                 source(STATIC / "index.html")))
        assert symbols, "no icon symbols found -- has the shell moved?"

        emit = {ru_text.icon_key(c) for c in ru_text.CONDITIONS}
        emit |= set(getattr(ru_text, "_YA_ICON", {}).values())
        emit = {k for k in emit if k}
        emit |= {sun.nightify(k, True) for k in emit}
        emit |= {sun.nightify(k, False) for k in emit}

        missing = sorted(k for k in emit if k and k not in symbols)
        assert not missing, (
            f"the parsers can produce {missing} and the shell has no symbol "
            f"for them -- they would render as the unknown glyph")

    def test_the_unicode_minus_is_still_first(self):
        """Yandex renders minus as U+2212. Miss it and every winter temperature
        comes out positive -- and it is completely invisible in July."""
        text = source(APP / "ru_text.py")
        m = re.search(r'MINUSES\s*=\s*"(.*?)"', text)
        assert m, "the MINUSES table is gone"
        assert "−" in m.group(1), "U+2212 dropped from the minus table"

    def test_nobody_guesses_night_from_a_fixed_hour_window(self):
        """`hour >= 21 or hour < 5` is right in Yoshkar-Ola in August and wrong
        for most of the rest of the year. Day and night are computed from the
        place and the clock in `sun.py`. (`DECISIONS.md` §13)"""
        for path in PY_MODULES:
            if path.name == "sun.py":
                continue
            assert not re.search(r"hour\s*[<>]=?\s*\d+\s*(and|or)\s*hour",
                                 code_only(path)), \
                f"{path.name} is guessing day/night from a fixed hour window"

    def test_no_constant_is_written_down_in_two_languages(self):
        """CSS owns the layout numbers; JS reads them back.

        Restating one is how the hourly curve drifted 4px per column, then how
        the status-bar tint drifted from the scrim, and it would have been how
        the screen animation drifted from its own timeout. Third time it became
        a test; this is the fourth, and the test no longer names the properties
        it protects -- it derives them from the code, so the next one is covered
        the moment it is written rather than the moment someone remembers.
        """
        js = js_code_only(STATIC / "app.js")
        css = source(STATIC / "index.html")

        read = set(re.findall(r"""cssVar\(\s*['"](--[\w-]+)['"]""", js)) | \
            set(re.findall(r"""getPropertyValue\(\s*['"](--[\w-]+)['"]""", js))
        assert read, "app.js reads no CSS custom property back at all"
        missing = sorted(n for n in read if f"{n}:" not in css)
        assert not missing, \
            f"app.js reads {missing} but the stylesheet never defines them"

        # And the other direction: a literal in the JS that repeats a value the
        # stylesheet already owns is the bug itself, whatever it is called.
        for name in sorted(read):
            m = re.search(rf"{re.escape(name)}\s*:\s*([^;{{}}]+);", css)
            if not m:
                continue
            value = m.group(1).strip()
            if len(value) < 4:                 # too short to be a coincidence
                continue
            assert value not in js, (
                f"{name} is {value} in the stylesheet and the same literal "
                f"appears in app.js -- read it back, do not restate it")


class TestTheFixturesAreOneRecording:
    """All three sources must describe the same fortnight.

    Re-recording one source and not the others produces a fixture set that is
    internally impossible: in August 2026 Gismeteo was re-recorded alone, and
    its ten days (13–22 Aug) shared **not one date** with Yandex's (31 Jul–9
    Aug). Everything downstream then failed for reasons that had nothing to do
    with the code — the day screen showed an empty table when you switched
    source, because the day being asked for did not exist in the other source.

    That failure took a while to read, so it is asserted directly here. The
    message is the fix: `make fixtures && make fixtures-gm`, both, together.
    """

    @staticmethod
    def _days(name: str) -> list[str]:
        raw = (ROOT / "tests" / "fixtures" / name).read_text(
            encoding="utf-8", errors="replace")
        return sorted(set(re.findall(r"20\d\d-[01]\d-[0-3]\d", raw)))

    # Known red, and marked so rather than skipped: a skip is silent, and since
    # the CI gate began meaning what it says, a plain failure here blocks every
    # deploy. Meteofor's outage of 15 August 2026 (DECISIONS.md §32) meant
    # Yandex could be re-recorded and Gismeteo could not. `strict` is the half
    # that matters: the day both are re-recorded together and agree, this
    # passes, the unexpected pass fails the suite, and the marker comes off.
    @pytest.mark.xfail(strict=True, reason=(
        "the Yandex and Gismeteo fixtures are two recordings with no date in "
        "common (Gismeteo could not be re-recorded during its 15 August 2026 "
        "outage). Strict: this fails loudly the day the fixtures are "
        "re-recorded and agree -- then delete this marker."))
    def test_the_sources_overlap(self):
        ya = self._days("current.html")
        gm = self._days("mf-10days.html")
        if not ya or not gm:
            pytest.skip("a fixture is missing its dates")
        shared = set(ya) & set(gm)
        assert shared, (
            f"the fixtures are different recordings: Yandex spans "
            f"{ya[0]}..{ya[-1]} and Gismeteo {gm[0]}..{gm[-1]}, with no date "
            f"in common. Re-record both -- `make fixtures && make fixtures-gm`")


class TestNothingPinsTheDocument:
    """The single most expensive line this project has ever contained was

        body.locked { position: fixed; ... }

    a scroll lock, and the standard one. In a standalone iOS web app it does
    two things nobody expects:

    1. **It collapses the viewport to the small viewport.** `innerHeight` goes
       from 852 to 793 -- the display minus the status-bar inset -- and stays
       there for as long as the lock is on. Every consequence of that was
       investigated for six deploys as though it were a layout bug: an
       unpaintable 59pt band along the bottom of the phone, content cut off at
       the fold, `dvh` disagreeing with `lvh`. It was the lock.
    2. **It relayouts the whole document**, and it was doing so in the same
       task that starts the sheet's transition -- so the animation's opening
       frames were never painted. Two screen recordings measured the sheet
       first appearing at 505pt and 573pt of a travel starting at 793.

    Both symptoms vanished together the moment `position: fixed` came off. The
    diagnostic on the device now reports `inner 393x852` and `ниже вьюпорта
    0pt`, where it used to report 793 and 59.

    The replacement is `overflow: hidden` on the scrolling element, which is
    what WebKit has honoured since **iOS 16.3**. The note that justified the
    pin predated that fix by three years and was inherited without re-dating.

    This is asserted at the source, because it is a rule about what may not be
    *written*: a browser that does not collapse its viewport -- every desktop
    one -- cannot show the failure.
    """

    ROOTS = ("html", "body")

    @pytest.mark.parametrize("el", ROOTS)
    def test_the_scroll_lock_never_pins_the_root(self, el):
        css = source(STATIC / "index.html")
        for m in re.finditer(rf"^{el}[.#\[][^{{]*\{{([^}}]*)\}}", css, re.S | re.M):
            body = m.group(1).replace(" ", "").replace("\n", "")
            assert "position:fixed" not in body, (
                f"a `{el}` rule sets `position: fixed`. In a standalone iOS "
                f"web app that shrinks the viewport by the status-bar inset "
                f"and relayouts the document -- see DECISIONS.md §26. Lock "
                f"with `overflow: hidden` instead.")

    def test_the_lock_is_there_and_is_overflow_based(self):
        css = source(STATIC / "index.html").replace(" ", "").replace("\n", "")
        assert "html.locked{" in css, "the scroll lock is gone entirely"
        rule = css.split("html.locked{", 1)[1].split("}", 1)[0]
        assert "overflow:hidden" in rule, \
            "the lock no longer blocks scrolling"

    def test_the_front_end_restores_no_scroll_offset(self):
        """A lock that changes no geometry has nothing to put back. Saving and
        restoring `scrollY` is the tell that something is being pinned again --
        and `window.scrollTo` on the way out relayouts the document exactly
        when the exit animation needs the main thread."""
        # `\b...\(` and not a substring search: `scrollTop` contains
        # `scrollTo`, and the sheet reads `scrollTop` legitimately to decide
        # whether a drag may start. The first version of this test fired on
        # that, which is the same species of mistake as a grep matching its
        # own warning label.
        js = js_code_only(STATIC / "app.js")
        assert not re.search(r"\bscrollTo\s*\(", js), (
            "app.js restores a scroll offset, which means something moved the "
            "page. Nothing should have to.")


class TestAFullScreenPanelIsSizedByTheViewportNotTheDisplay:
    """Five attempts at one 59pt band, and this is the one that catches the
    fifth -- which was mine, and which made things worse rather than nothing.

    On this phone the web view is 393x793 sitting at the top of an 852pt
    display. `100dvh`, `100svh`, `innerHeight` and `bottom: 0` all report 793,
    which is **right**: 793 is what the device shows. `100vh` and `100lvh`
    report 852, which is the glass, not the canvas.

    Sizing a panel with `lvh` therefore does not extend it down the screen. It
    was tried, and the box obediently measured 852 while the paint still
    stopped at 793 -- so the last 59pt of the scroll content moved into a
    region the device never draws. A band you can see beats content you
    cannot. The band is not a CSS problem; it is where iOS puts the web view,
    which is the status-bar style in the <head>.
    """

    PANELS = ("screen", "sky")

    @staticmethod
    def _rule(css: str, selector: str) -> str:
        m = re.search(rf"^\.{selector}\{{(.*?)\}}", css, re.S | re.M)
        assert m, f"no `.{selector}` rule in index.html -- did it get renamed?"
        return m.group(1)

    @pytest.mark.parametrize("selector", PANELS)
    def test_it_is_not_sized_by_the_large_viewport(self, selector):
        rule = self._rule(source(STATIC / "index.html"), selector)
        for unit in ("lvh", "vh"):
            assert not re.search(rf"\d\s*{unit}\b", rule), (
                f"`.{selector}` is sized with `{unit}`, which is the display "
                f"(852pt) and not the web view (793pt). The extra 59pt is "
                f"never painted, so this hides the end of the panel's content "
                f"instead of revealing more of it. Use `inset: 0` or `dvh`.")

    @pytest.mark.parametrize("selector", PANELS)
    def test_its_bottom_edge_is_the_bottom_of_the_viewport(self, selector):
        """Not the height -- the *bottom*. `.screen` is a sheet now and starts
        partway down on purpose, so what has to hold is that nothing is left
        between it and the fold. Everything past the fold is canvas nobody can
        paint, and a gap above it is the original bug."""
        rule = self._rule(source(STATIC / "index.html"), selector).replace(" ", "")
        assert "inset:0" in rule or "bottom:0" in rule or "dvh" in rule, (
            f"`.{selector}` no longer reaches the bottom of the viewport -- see "
            f"the comment above the rule, and DECISIONS.md §26.")


class TestThePrivacyPromiseIsStructural:
    """The project's entire premise: the phone talks only to this server.

    `test_api.py` and `test_ui.py` assert this at the HTTP and network layers,
    which is where it counts. These are the cheap authoring-time versions --
    they fail the moment someone *types* a foreign URL, rather than when the
    page is next loaded in a browser under Playwright.
    """

    @pytest.mark.parametrize("name", ["index.html", "app.js", "sw.js"])
    def test_no_absolute_foreign_url_in_the_shell(self, name):
        text = source(STATIC / name)
        found = [u for u in re.findall(r"https?://[\w.-]+", text)
                 if "w3.org" not in u]        # SVG namespaces are not requests
        assert not found, f"{name} names a foreign origin: {found}"

    def test_the_shell_has_no_connection_hints(self):
        """`preconnect`, `dns-prefetch` and `preload` open real connections
        before a line of JS runs, so a CSP that blocks the fetch still leaks
        the DNS lookup."""
        text = source(STATIC / "index.html")
        for rel in ("preconnect", "dns-prefetch", "prefetch", "preload"):
            assert f'rel="{rel}"' not in text, f"index.html has a {rel} hint"

    def test_no_analytics_or_telemetry_sneaks_in(self):
        blob = " ".join(source(STATIC / n) for n in
                        ("index.html", "app.js", "sw.js")).lower()
        for smell in ("gtag", "analytics", "sentry", "datadog", "mixpanel",
                      "googletagmanager", "hotjar", "beacon("):
            assert smell not in blob, f"the shell mentions {smell!r}"
