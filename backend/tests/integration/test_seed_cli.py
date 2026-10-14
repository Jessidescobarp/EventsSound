"""The seed CLI end to end against a real Postgres (DATABASE_URL_TEST)."""

import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from eventssound.config import Settings
from eventssound.entrypoints.cli import seed_catalog as cli


def counts(url: str) -> tuple[int, int, int, int]:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return tuple(  # type: ignore[return-value]
                connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                for table in ("equipment_items", "service_packages", "package_items", "bookings")
            )
    finally:
        engine.dispose()


def test_main_twice_seeds_once_and_reports_a_safe_summary(
    migrated_database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(_env_file=None, DATABASE_URL=migrated_database)  # type: ignore[call-arg]
    allow = {"ALLOW_REMOTE_SEED": "1"}  # the CI database host may not be on the local list

    assert cli.main(["--confirm"], settings=settings, environ=allow) == 0
    first = counts(migrated_database)
    assert cli.main(["--confirm"], settings=settings, environ=allow) == 0

    assert counts(migrated_database) == first
    assert first[0] == 23
    assert first[1] == 4
    assert first[2] > 0
    out = capsys.readouterr().out
    assert out.count("seeded 23 items, 4 packages and 5 demo bookings") == 2
    password = make_url(migrated_database).password
    assert not password or password not in out


def test_module_entrypoint_runs_as_a_script(migrated_database: str) -> None:
    env = {**os.environ, "DATABASE_URL": migrated_database, "APP_ENV": "local"}
    env.pop("ALLOW_REMOTE_SEED", None)
    local = make_url(migrated_database).host in cli.LOCAL_HOSTS
    if not local:
        env["ALLOW_REMOTE_SEED"] = "1"

    done = subprocess.run(
        [sys.executable, "-m", "eventssound.entrypoints.cli.seed_catalog", "--confirm"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert done.returncode == 0, done.stderr
    assert "seeded 23 items" in done.stdout
    assert counts(migrated_database)[0] == 23
    password = make_url(migrated_database).password
    assert not password or password not in done.stdout + done.stderr
