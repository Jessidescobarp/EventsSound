"""The IANA database must not depend on the host: Windows and python:3.12-slim ship none."""

import tomllib
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_tzdata_is_a_runtime_dependency() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert any(dep.replace(" ", "").startswith("tzdata") for dep in project["dependencies"])


@pytest.mark.parametrize("month", [1, 7])
def test_bogota_is_utc_minus_five_all_year(month: int) -> None:
    zone = ZoneInfo("America/Bogota")
    assert datetime(2026, month, 1, tzinfo=zone).utcoffset() == timedelta(hours=-5)
