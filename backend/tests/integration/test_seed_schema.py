"""The schema-version check and error classification against a real Postgres."""

import traceback
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from conftest import SECRETS_IN_UNREACHABLE_URL
from eventssound.adapters.db.session import build_engine, build_session_factory
from eventssound.adapters.db.storage import check_schema
from eventssound.application.errors import AuthenticationFailed, ConnectionFailed, SchemaNotReady
from eventssound.config import Settings
from eventssound.entrypoints.cli import seed_catalog as cli


@pytest.fixture
def plain_factory(alembic_config: Config, database_url: str) -> Iterator[sessionmaker[Session]]:
    """A session factory on an EMPTY database (no tables, no alembic_version)."""
    engine = build_engine(database_url)
    yield build_session_factory(engine)
    engine.dispose()


def head_revision(alembic_config: Config) -> str:
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(alembic_config).get_current_head()
    assert head
    return head


def test_the_head_revision_passes(alembic_config: Config, plain_factory: sessionmaker) -> None:
    command.upgrade(alembic_config, "head")

    check_schema(plain_factory, head_revision(alembic_config))


def test_a_database_without_tables_is_not_ready(
    alembic_config: Config, plain_factory: sessionmaker
) -> None:
    with pytest.raises(SchemaNotReady):
        check_schema(plain_factory, head_revision(alembic_config))


def test_an_older_revision_is_not_ready(
    alembic_config: Config, plain_factory: sessionmaker
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "0001")

    with pytest.raises(SchemaNotReady):
        check_schema(plain_factory, head_revision(alembic_config))


def test_an_empty_version_table_is_not_ready(
    alembic_config: Config, plain_factory: sessionmaker
) -> None:
    command.upgrade(alembic_config, "head")
    with plain_factory.begin() as session:
        session.execute(text("DELETE FROM alembic_version"))

    with pytest.raises(SchemaNotReady):
        check_schema(plain_factory, head_revision(alembic_config))


def test_an_unreachable_database_is_a_connection_failure_without_url_parts(
    unreachable_session_factory: sessionmaker,
) -> None:
    with pytest.raises(ConnectionFailed) as caught:
        check_schema(unreachable_session_factory, "0002")

    rendered = str(caught.value) + "".join(traceback.format_exception(caught.value))
    for secret in SECRETS_IN_UNREACHABLE_URL:
        assert secret not in rendered


def wrong_password_url(database_url: str) -> str:
    url = make_url(database_url).set(password="definitely-wrong-password")
    return url.render_as_string(hide_password=False)


def trusts_everyone(database_url: str) -> bool:
    engine = create_engine(wrong_password_url(database_url), connect_args={"connect_timeout": 3})
    try:
        with engine.connect():
            return True
    except Exception:
        return False
    finally:
        engine.dispose()


def test_a_wrong_password_is_an_authentication_failure(database_url: str) -> None:
    if trusts_everyone(database_url):
        pytest.skip("the test server does not check passwords (trust authentication)")
    engine = build_engine(wrong_password_url(database_url))
    try:
        with pytest.raises(AuthenticationFailed) as caught:
            check_schema(build_session_factory(engine), "0002")
    finally:
        engine.dispose()

    assert "definitely-wrong-password" not in str(caught.value) + "".join(
        traceback.format_exception(caught.value)
    )


def run_cli(url: str, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    settings = Settings(_env_file=None, DATABASE_URL=url)  # type: ignore[call-arg]
    code = cli.main(["--confirm", *argv], settings=settings, environ={"ALLOW_REMOTE_SEED": "1"})
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_stops_with_a_distinct_code_when_the_schema_is_missing(
    alembic_config: Config, database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run_cli(database_url, capsys)

    assert code == 4
    assert "run alembic upgrade head first" in err
    assert out == ""
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            tables = connection.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
            ).scalar_one()
    finally:
        engine.dispose()
    assert tables == 0


def test_cli_stops_when_the_schema_is_one_revision_behind(
    alembic_config: Config, database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "0001")

    code, _, err = run_cli(database_url, capsys)

    assert code == 4
    assert "out of date" in err


def test_cli_reports_bad_credentials_without_the_password(
    database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    if trusts_everyone(database_url):
        pytest.skip("the test server does not check passwords (trust authentication)")

    code, out, err = run_cli(wrong_password_url(database_url), capsys)

    assert code == 1
    assert "rejected the credentials" in err
    assert "definitely-wrong-password" not in out + err


def counts(url: str) -> tuple[int, int]:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return (
                connection.execute(text("SELECT count(*) FROM equipment_items")).scalar_one(),
                connection.execute(text("SELECT count(*) FROM bookings")).scalar_one(),
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("argv", "app_env"),
    [(("--no-bookings",), "local"), ((), "production")],
    ids=["flag", "production"],
)
def test_cli_writes_the_catalog_but_no_demo_bookings_when_they_are_skipped(
    migrated_database: str,
    argv: tuple[str, ...],
    app_env: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(_env_file=None, DATABASE_URL=migrated_database, app_env=app_env)  # type: ignore[call-arg]

    code = cli.main(["--confirm", *argv], settings=settings, environ={"ALLOW_REMOTE_SEED": "1"})

    assert code == 0
    assert counts(migrated_database) == (20, 0)
    assert "demo bookings: skipped" in capsys.readouterr().out
