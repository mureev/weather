"""Rules that survive the people who wrote them.

This project is edited by a long succession of sessions, each of which arrives
knowing nothing and leaves in an hour. Comments and `CLAUDE.md` tell them the
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


# --- layering ---------------------------------------------------------------

class TestNothingReachesUpward:
    """The dependency arrows in `CLAUDE.md`, as code.

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
        """CSS owns the layout numbers; JS reads them back. Restating one is
        how the hourly curve drifted 4px per column, and then how the status
        bar tint drifted from the scrim. Third time it becomes a test."""
        js = source(STATIC / "app.js")
        for name in ("--hour-w", "--scrim"):
            assert name in js, f"app.js no longer reads {name} back from CSS"
        assert not re.search(r"rgba?\(\s*4\s*,\s*8\s*,\s*18", js), \
            "the scrim colour is restated in app.js instead of read from --scrim"


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
