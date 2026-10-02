"""Documentation that cannot quietly go stale.

This project's whole premise is that the reasoning outlives the code -- its
predecessor lost every line and was rebuilt from surviving documentation in an
afternoon. Which makes documentation drift a correctness problem here, not a
tidiness one: a `README` that describes a module that no longer exists is worse
than no `README`, because it will be believed.

So the parts of the docs that *can* be checked mechanically are. Not the prose,
which no test can judge -- but the inventories, which are exactly the parts
that rot silently and which a human reviewer skims.

The README's test count used to be one of them -- hand-edited three times in
one afternoon and wrong after two -- and then a test that kept it honest, bumped
by a third of all commits. Since 2026-10-02 the README states no count at all,
which is the other way to have one source (DECISIONS.md §42).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
DECISIONS = (ROOT / "DECISIONS.md").read_text(encoding="utf-8")


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
                    "clean", "selftest", "test-if-possible"}
        assert not (targets - documented - internal), \
            f"targets with no `make help` line: {sorted(targets - documented - internal)}"

    def test_recording_a_fixture_survives_a_machine_without_pytest(self, tmp_path):
        """Reported twice, from a Mac, as `make fixtures-ya` being broken.

        It was not: the fixture recorded perfectly both times and then the
        target announced a failure, because the machine that can *record* often
        cannot *test* -- a laptop has curl and no pytest, and that is a fine
        machine to record from.

        The first fix was a guard that probed for pytest and `exit 0`-ed. It
        printed its message and then ran pytest anyway, which reads as the
        guard having no effect at all. **Make gives every line of a recipe its
        own shell**, so `exit 0` ended a shell that had nothing left to do and
        the next line ran regardless. The whole thing has to be one line.

        So this drives the real target with a `python3` on PATH that has no
        pytest, and asserts both halves: it succeeds, and it does not try.
        """
        shim = tmp_path / "python3"
        shim.write_text(
            "#!/bin/sh\n"
            '[ "$1" = "-c" ] && [ "$2" = "import pytest" ] && exit 1\n'
            f'exec {sys.executable} "$@"\n')
        shim.chmod(0o755)
        env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")
        r = subprocess.run(["make", "test-if-possible"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, (
            f"recording a fixture fails on a machine without pytest:\n"
            f"{r.stdout}\n{r.stderr}")
        assert "pytest is not installed" in r.stdout
        assert "-m pytest" not in r.stdout, (
            "the guard printed its message and then ran the suite anyway -- "
            "check that the whole probe is a single recipe line")


class TestTheLocksSayHowTheyWereMade:
    """A lock is reproducible only if the command written at its top is the
    one that wrote it. Whoever regenerates a lock may never open the Makefile,
    so the header is the documentation; `make lock` repeats both commands, so
    the two have to agree."""

    LOCKS = ("requirements.lock", "requirements-dev.lock")

    def test_make_lock_runs_the_command_each_lock_records(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        recipe = re.search(r"^lock:\n((?:\t.*\n)+)", makefile, re.M)
        assert recipe, "the Makefile has no `lock` target"
        lines = [ln.strip() + " " for ln in recipe.group(1).splitlines()]
        order = []
        for name in self.LOCKS:
            head = (ROOT / name).read_text(encoding="utf-8").splitlines()[:2]
            assert head[0].startswith("# This file was autogenerated by uv"), \
                f"{name} has no uv header -- was it edited by hand?"
            command = head[1].lstrip("#").strip()
            found = [i for i, ln in enumerate(lines) if ln.startswith(command + " ")]
            assert found, (f"{name} says it was made by `{command}`, "
                           f"and `make lock` does not run that")
            order.append(found[0])
        assert order == sorted(order), \
            "make lock writes the dev lock before the app's, which it is resolved against"

    def test_ci_installs_nothing_that_is_not_hash_locked(self):
        """The test jobs decide whether `release` publishes. A tool installed
        by name and version alone is the one part of that decision nobody
        reviewed -- and the pins used to live there, beside the locks."""
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        installs = [ln.strip() for ln in ci.splitlines()
                    if re.search(r"\bpip install\b", ln) and not ln.strip().startswith("#")]
        assert installs, "ci.yml installs nothing -- has it changed shape?"
        # In hash mode pip itself refuses anything without a hash, so the flag
        # on every line is the whole check.
        loose = [ln for ln in installs if "--require-hashes" not in ln]
        assert not loose, f"ci.yml installs outside the locks: {loose}"


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
        # Read elsewhere than config.py: the mock server, the image's build
        # stamp, and the container's own clock.
        elsewhere = {"PORT", "YW_MOCK", "APP_BUILD", "APP_BUILT_AT", "TZ"}
        phantom = sorted(n for n in mentioned - elsewhere if n not in config)
        assert not phantom, f".env.example documents unread variables: {phantom}"


class TestTheBuildStampCanDistinguishBuilds:
    def test_it_does_not_fall_back_to_a_constant(self):
        """`/api/version` reports the build so you can tell whether a deploy
        landed. It fell back to the literal "dev", and since this repo then had
        no commits, *every* image was stamped `dev` -- a field that looks like
        information and carries none, which is worse than no field.

        Any fallback is fine as long as two builds differ."""
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        line = next(ln for ln in makefile.splitlines()
                    if ln.startswith("BUILD ") or ln.startswith("BUILD\t")
                    or ln.split("?=")[0].strip() == "BUILD")
        fallback = line.split("||")[-1]
        assert "date" in fallback or "uuid" in fallback or "RANDOM" in fallback, \
            f"the build stamp falls back to something constant: {fallback.strip()}"


# Decisions that state no reversal condition, each with the reason it does not.
#
# Not a suppression list. It was assembled the day the test above was found to
# have been passing without checking anything (see its docstring), and every
# entry here is a section that had been exempt by accident for months. Writing
# them down turns each one into a choice somebody made; the test fails both when
# a new decision joins them **and** when one of them grows a reversal condition
# and this list is not updated, so it cannot quietly become the place unreviewed
# entries go.
WITHOUT_A_REVERSAL = {
    "3. Values are dropped, never clamped":
        "invariant 1 restated; reversing it is reversing the invariant",
    "5. Geolocation is a button, never automatic":
        "invariant 5; the reversal is 'stop caring what leaves the phone'",
    "6. Gismeteo has partial city coverage, and does not fake the rest":
        "invariant 2; the reversal is serving one city's numbers under "
        "another's name, which is the failure the project is about",
    "8. The hero has no card": "taste, argued in prose, no condition to state",
    "9. The place name is the control": "same -- a layout preference",
    "10. The service-worker version is derived, not typed":
        "invariant 9 restated for the build hash",
    "11. Everything on the sky uses fixed-alpha translucency, not palette "
    "colours": "a consequence of the gradient, not a choice over it",
    "12. A retry is for refusals, never for parse failures": "invariant 6",
    "21. Things deliberately not built":
        "a list of non-decisions; each entry carries its own argument",
}

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
        with neither is one nobody can safely revisit.

        **Two ways this used to pass without checking anything**, and both are
        the reason it is worth reading a green test occasionally:

        The split left the *last* section running to the end of the file, so it
        swallowed the trap list and every appendix below it. Whatever was down
        there supplied the keyword, and the newest decision -- always the last
        one, always the one nobody has reviewed -- was the single entry exempt
        from the rule. It only surfaced when a later section was appended and
        the previous last one suddenly had to stand on its own.

        And `"why"` matches `anywhere`, `whatever`, and the word "why" used in
        passing in any sentence at all, which is most of them. The phrases below
        are the ones this file actually uses as a heading.
        """
        parts = re.split(r"^## (?=\d+\.|\w)", DECISIONS, flags=re.M)
        sections = [s for s in parts if re.match(r"\d+\.", s)]
        assert len(sections) >= 25, (
            f"only {len(sections)} decisions found -- the split stopped "
            f"matching the headings and this test is now checking nothing")
        want = ("what would reverse it", "what would change it",
                "what should refuse", "what would undo")
        thin = {s.split("\n")[0].strip() for s in sections
                if not any(w in s.lower() for w in want)}
        missed = thin - set(WITHOUT_A_REVERSAL)
        assert not missed, f"decisions with no stated reversal condition: {missed}"
        gone = set(WITHOUT_A_REVERSAL) - thin
        assert not gone, (
            f"{sorted(gone)} grew a reversal condition -- good; take them out "
            f"of WITHOUT_A_REVERSAL so the exemption does not outlive the gap")
