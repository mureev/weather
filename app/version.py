"""What this build is, and what the front-end shell is.

Two separate identities, for two separate questions.

**`BUILD`** answers "is my change live?" -- a git SHA baked in at image build.
Without it the only way to tell whether a deploy landed is to squint at the UI
and guess, which is exactly how you end up debugging a fix that was never
shipped. It costs one `--build-arg`.

**`SHELL`** answers "should the service worker throw away its caches?" -- a hash
of the files the service worker actually caches. It exists because the manual
alternative does not survive contact with a real project: over one afternoon
this constant was bumped by hand eight times, and the ninth time is the one you
forget, and the symptom is a redesign that is invisible to every device that
already installed the app while being perfectly visible in a fresh browser.
That is a genuinely horrible bug to diagnose.

Deriving it from content means the question "did the shell change?" is answered
by the shell, not by whoever last edited it.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"

# Files the service worker precaches. Changing any of them must invalidate it.
SHELL_FILES = ("index.html", "app.js", "sw.js")


def shell_hash() -> str:
    h = hashlib.sha256()
    for name in SHELL_FILES:
        p = STATIC / name
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


# Baked at image build; "dev" when running from a checkout.
BUILD: str = os.environ.get("APP_BUILD", "dev")
BUILT_AT: str = os.environ.get("APP_BUILT_AT", "")
SHELL: str = shell_hash()


def info() -> dict[str, str]:
    return {"build": BUILD, "built_at": BUILT_AT, "shell": SHELL}
