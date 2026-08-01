"""Documentation that cannot quietly go stale.

This project's whole premise is that the reasoning outlives the code -- its
predecessor lost every line and was rebuilt from surviving documentation in an
afternoon. Which makes documentation drift a correctness problem here, not a
tidiness one: a `README` that describes a module that no longer exists is worse
than no `README`, because it will be believed.

So the parts of the docs that *can* be checked mechanically are. Not the prose,
which no test can judge -- but the inventories and the counts, which are
exactly the parts that rot silently and which a human reviewer skims.

The count in particular earned its test the hard way: it was hand-edited three
times in one afternoon and was wrong after two of them. That is the same defect
as the hourly column width being written down twice, and it gets the same fix.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
DECISIONS = (ROOT / "DECISIONS.md").read_text(encoding="utf-8")


def collected_tests() -> int:
    """The real number, from pytest itself.

    A subprocess rather than a collection hook, so the answer is the same
    whether the suite was run whole or a single file was run in isolation.
    """
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider", str(ROOT / "tests")],
        capture_output=True, text=True, cwd=ROOT, timeout=300)
    m = re.search(r"(\d+)\s+tests?\s+collected", out.stdout) or \
        re.search(r"(\d+)/(\d+) tests collected", out.stdout)
    if not m:
        pytest.skip(f"could not read a collection count from pytest: {out.stdout[-300:]}")
    return int(m.group(1))


class TestTheCountsAreReal:
    def test_the_readme_says_how_many_tests_there_are_and_is_right(self):
        claimed = {int(n) for n in re.findall(r"(\d+)\s+tests\b", README)}
        assert claimed, "the README no longer states a test count"
        actual = collected_tests()
        assert claimed == {actual}, (
            f"README says {sorted(claimed)} tests, pytest collects {actual}. "
            f"Run: sed -i 's/{max(claimed)} tests/{actual} tests/g' README.md")


class TestTheInventoriesAreComplete:
    """Three lists of files live in the docs. Each is the first thing someone
    picking this up cold will read, and each is one `git add` away from lying.
    """

    def test_every_app_module_appears_in_the_readme_layout(self):
        layout = next(b for b in README.split("```")
                      if "app/" in b and "config.py" in b)
        missing = [p.name for p in sorted((ROOT / "app").glob("*.py"))
                   if p.name != "__init__.py" and p.name not in layout]
        assert not missing, f"undocumented modules in README's layout: {missing}"

    def test_every_source_adapter_appears_too(self):
        missing = [p.name for p in sorted((ROOT / "app" / "sources").glob("*.py"))
                   if p.name != "__init__.py" and p.name not in README]
        assert not missing, f"undocumented source adapters: {missing}"

    def test_every_diagnostic_is_in_the_tools_table(self):
        table = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
        missing = [p.name for p in sorted((ROOT / "tools").iterdir())
                   if p.suffix in (".py", ".sh") and p.name not in table]
        assert not missing, f"undocumented diagnostics: {missing}"

    def test_every_make_target_that_exists_is_in_the_help_or_deliberately_not(self):
        """`make help` greps the header comments, so a target added without a
        header line is invisible to the person who needs it most."""
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        targets = set(re.findall(r"^([a-z][a-z-]*):", makefile, re.M))
        documented = set(re.findall(r"^#   make ([a-z-]+)", makefile, re.M))
        # Plumbing nobody types directly. Named explicitly so that adding to
        # this set is a decision rather than an omission.
        internal = {"help", "lint", "fmt", "test", "test-fast", "mock", "shots",
                    "build", "restart", "reload-nginx", "sync-config", "ps",
                    "clean", "selftest"}
        assert not (targets - documented - internal), \
            f"targets with no `make help` line: {sorted(targets - documented - internal)}"


class TestEverySettingIsDiscoverable:
    """`.env.example` is the only place anyone will look for "what can I
    configure". A setting that exists in `config.py` and nowhere else is a
    setting nobody will ever find, including the session that needs it at 2am
    because a source started refusing the server."""

    def test_every_environment_variable_is_in_the_example_file(self):
        config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        declared = set(re.findall(r'_[sifb]\(\s*"([A-Z][A-Z0-9_]*)"', config))
        assert declared, "no settings found -- has config.py changed shape?"
        missing = sorted(n for n in declared if n not in env)
        assert not missing, f"settings absent from .env.example: {missing}"

    def test_the_example_file_invents_nothing(self):
        """The other direction. A documented variable the code never reads is
        worse than an undocumented one: someone will set it and wonder why
        nothing happens."""
        config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
        env = (ROOT / ".env.example").read_text(encoding="utf-8")
        mentioned = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]{3,})=", env, re.M))
        # Read elsewhere than config.py, or consumed by compose/nginx rather
        # than by the app.
        elsewhere = {"PORT", "YW_MOCK", "APP_BUILD", "APP_BUILT_AT",
                     "VIRTUAL_HOST", "LETSENCRYPT_HOST", "TZ"}
        phantom = sorted(n for n in mentioned - elsewhere if n not in config)
        assert not phantom, f".env.example documents unread variables: {phantom}"


class TestTheBuildStampCanDistinguishBuilds:
    def test_it_does_not_fall_back_to_a_constant(self):
        """`/api/health` reports the build so you can tell whether a deploy
        landed. It fell back to the literal "dev", and since this repo has no
        commits, *every* image was stamped `dev` -- a field that looks like
        information and carries none, which is worse than no field.

        Any fallback is fine as long as two builds differ."""
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        line = next(ln for ln in makefile.splitlines()
                    if ln.startswith("BUILD ") or ln.startswith("BUILD\t")
                    or ln.split("?=")[0].strip() == "BUILD")
        fallback = line.split("||")[-1]
        assert "date" in fallback or "uuid" in fallback or "RANDOM" in fallback, \
            f"the build stamp falls back to something constant: {fallback.strip()}"


class TestDecisionsStayNumbered:
    def test_the_sections_are_consecutive(self):
        """They get cross-referenced by number from the code, so a duplicate or
        a gap sends the next reader to the wrong argument."""
        nums = [int(n) for n in re.findall(r"^## (\d+)\.", DECISIONS, re.M)]
        assert nums == list(range(1, len(nums) + 1)), f"section numbers: {nums}"

    def test_every_reference_from_the_code_resolves(self):
        """`DECISIONS.md §7` in a docstring is a promise that §7 exists and is
        still about what the docstring thinks it is about."""
        biggest = max(int(n) for n in re.findall(r"^## (\d+)\.", DECISIONS, re.M))
        refs: set[int] = set()
        for path in list(ROOT.glob("app/**/*.py")) + list(ROOT.glob("tests/*.py")) \
                + list(ROOT.glob("tools/*.py")) + [ROOT / "README.md"]:
            refs |= {int(n) for n in
                     re.findall(r"DECISIONS\.md`?\s*§(\d+)",
                                path.read_text(encoding="utf-8"))}
        assert refs, "nothing references DECISIONS.md any more -- suspicious"
        assert max(refs) <= biggest, \
            f"code references §{max(refs)} but DECISIONS.md stops at §{biggest}"

    def test_each_decision_says_what_would_reverse_it(self):
        """The file's own rule, in its own header: a decision recorded without
        its reversal condition becomes dogma. Enforced loosely -- some entries
        argue the point in prose rather than under a heading -- but a section
        with neither is one nobody can safely revisit."""
        sections = re.split(r"^## \d+\.", DECISIONS, flags=re.M)[1:]
        thin = [s.split("\n")[0].strip() for s in sections
                if "what would change it" not in s.lower()
                and "why" not in s.lower()]
        assert not thin, f"decisions with no reasoning or reversal: {thin}"
