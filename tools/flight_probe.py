"""Exploration helper: decode the Next.js RSC flight stream from a fixture."""
from __future__ import annotations

import contextlib
import json
import pathlib
import re
import sys
from collections.abc import Iterator
from typing import Any

PUSH = re.compile(r'self\.__next_f\.push\(\[1,\s*(".*?")\]\)', re.S)


def flight(path: str) -> str:
    h = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    out = []
    for m in PUSH.finditer(h):
        with contextlib.suppress(Exception):
            out.append(json.loads(m.group(1)))
    return "".join(out)


def balanced(s: str, start: int) -> str | None:
    """Extract the balanced {...} or [...] beginning at `start`."""
    if start >= len(s) or s[start] not in "{[":
        return None
    open_c, close_c = ("{", "}") if s[start] == "{" else ("[", "]")
    depth, i, in_str, esc = 0, start, False, False
    while i < len(s):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == open_c:
                depth += 1
            elif ch == close_c:
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
        i += 1
    return None


def objects_with_key(s: str, key: str) -> Iterator[tuple[int, Any]]:
    """Yield every JSON value assigned to `"key":` in the stream."""
    for m in re.finditer(rf'"{re.escape(key)}"\s*:\s*', s):
        j = m.end()
        raw = balanced(s, j)
        if raw is None:
            continue
        try:
            yield m.start(), json.loads(raw)
        except Exception:
            continue


if __name__ == "__main__":
    path, key = sys.argv[1], sys.argv[2]
    s = flight(path)
    for pos, val in objects_with_key(s, key):
        print(f"--- @{pos} {type(val).__name__} "
              f"len={len(val) if hasattr(val,'__len__') else '-'}")
        print(json.dumps(val, ensure_ascii=False)[:1200])
        print()
