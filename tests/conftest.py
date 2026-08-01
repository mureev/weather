import datetime as dt
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

FIX = pathlib.Path(__file__).parent / "fixtures"

# The day the fixtures were recorded. Pinning it keeps date arithmetic
# deterministic -- otherwise "Сегодня, 31 июля" resolves to a different year
# every time the suite runs after new year's.
FIXTURE_DAY = dt.date(2026, 7, 31)


def read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="session")
def current_html() -> str:
    return read("current.html")


@pytest.fixture(scope="session")
def latlon_html() -> str:
    return read("latlon.html")


@pytest.fixture(scope="session")
def details_html() -> str:
    return read("details.html")


@pytest.fixture
def today() -> dt.date:
    return FIXTURE_DAY
