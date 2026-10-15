"""The demo-user seed CLI: guard rules, idempotence, and no password in storage or output."""

import pytest
from sqlalchemy import create_engine, text

from eventssound.adapters.auth.hasher import Argon2Hasher
from eventssound.config import Settings
from eventssound.entrypoints.cli import seed_users as cli

ADMIN_PASSWORD = "admin-demo-password"
CLIENT_PASSWORD = "client-demo-password"
ENV = {
    "ALLOW_REMOTE_SEED": "1",  # the CI database host may not be on the local list
    "SEED_ADMIN_PASSWORD": ADMIN_PASSWORD,
    "SEED_CLIENT_PASSWORD": CLIENT_PASSWORD,
}


def rows(url: str) -> dict[str, tuple[str, str]]:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT email, role, password_hash FROM users"))
            return {email: (role, stored) for email, role, stored in result}
    finally:
        engine.dispose()


def test_dry_run_writes_nothing_and_needs_no_database(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([], environ={}) == cli.EXIT_DRY_RUN
    assert "dry run" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["SEED_ADMIN_PASSWORD", "SEED_CLIENT_PASSWORD"])
def test_short_or_missing_password_is_refused_without_echoing_values(
    missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {**ENV, missing: "short"}

    assert cli.main(["--confirm"], environ=env) == cli.EXIT_FAILURE
    err = capsys.readouterr().err
    assert missing in err and "short" not in err.replace(missing, "")


def test_production_target_is_refused_without_the_override(
    migrated_database: str,
) -> None:
    settings = Settings(_env_file=None, DATABASE_URL=migrated_database, app_env="production")  # type: ignore[call-arg]
    env = {k: v for k, v in ENV.items() if k != "ALLOW_REMOTE_SEED"}

    assert cli.main(["--confirm"], settings=settings, environ=env) == cli.EXIT_REFUSED
    assert rows(migrated_database) == {}


def test_twice_upserts_two_hashed_accounts_and_prints_no_secret(
    migrated_database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(_env_file=None, DATABASE_URL=migrated_database)  # type: ignore[call-arg]

    assert cli.main(["--confirm"], settings=settings, environ=ENV) == 0
    first = rows(migrated_database)
    assert cli.main(["--confirm"], settings=settings, environ=ENV) == 0
    second = rows(migrated_database)

    assert {e: r for e, (r, _) in second.items()} == {
        "admin@eventsounddr.example": "admin",
        "cliente@eventsounddr.example": "client",
    }
    assert set(first) == set(second)
    hasher = Argon2Hasher()
    assert hasher.verify(second["admin@eventsounddr.example"][1], ADMIN_PASSWORD)
    assert hasher.verify(second["cliente@eventsounddr.example"][1], CLIENT_PASSWORD)
    stored = " ".join(h for _, h in second.values())
    out = capsys.readouterr()
    for secret in (ADMIN_PASSWORD, CLIENT_PASSWORD):
        assert secret not in stored and secret not in out.out and secret not in out.err
