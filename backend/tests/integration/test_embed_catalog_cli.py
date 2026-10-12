"""embed_catalog CLI: guards before any connection, safe output, idempotent refresh."""

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from conftest import SECRETS_IN_UNREACHABLE_URL, UNREACHABLE_URL
from eventssound.adapters.db.seed import seed_catalog
from eventssound.adapters.db.seed_data import SEED_ITEMS, SEED_PACKAGES
from eventssound.config import Settings
from eventssound.entrypoints.cli import embed_catalog as cli

LOCAL = "postgresql+psycopg://u:p@127.0.0.1:5432/db"
REMOTE = "postgresql+psycopg://u:S3cr3t@ep-cool-123.example.com/db?sslmode=require"
KEY = "sk-or-v1-supersecretvalue1234567890"


def settings(url: str = LOCAL, **values: object) -> Settings:
    values.setdefault("embedding_provider", "fake")
    return Settings(_env_file=None, DATABASE_URL=url, **values)  # type: ignore[arg-type, call-arg]


@pytest.fixture(autouse=True)
def no_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests of the guards must never open a connection."""

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a connection was attempted")

    monkeypatch.setattr(cli, "build_engine", forbidden)


def run(capsys: pytest.CaptureFixture[str], argv: list[str], **kwargs: object) -> tuple[int, str]:
    code = cli.main(argv, **kwargs)  # type: ignore[arg-type]
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_a_dry_run_exits_2_and_connects_to_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    code, output = run(capsys, [], settings=settings(), environ={})

    assert code == cli.EXIT_DRY_RUN
    assert "dry run" in output and "--confirm" in output


def test_unknown_arguments_are_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--bogus"])
    capsys.readouterr()


def test_embeddings_off_is_a_clear_failure(capsys: pytest.CaptureFixture[str]) -> None:
    code, output = run(
        capsys, ["--confirm"], settings=settings(embedding_provider="off"), environ={}
    )

    assert code == cli.EXIT_FAILURE and "EMBEDDING_PROVIDER" in output


def test_a_remote_target_is_refused_without_the_override(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for environ in ({}, {"ALLOW_REMOTE_SEED": "true"}, {"ALLOW_REMOTE_SEED": "0"}):
        code, output = run(
            capsys,
            ["--confirm"],
            settings=settings(
                REMOTE, embedding_provider="openrouter", embedding_model="m", openrouter_api_key=KEY
            ),  # fmt: skip
            environ=environ,
        )

        assert code == cli.EXIT_REFUSED, environ
        assert "S3cr3t" not in output and "ep-cool" not in output and KEY not in output


def test_production_is_refused_even_on_a_local_host(capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = run(capsys, ["--confirm"], settings=settings(LOCAL, app_env="production"), environ={})

    assert code == cli.EXIT_REFUSED


def test_fake_embeddings_are_never_written_to_a_remote_target_even_with_the_override(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, output = run(
        capsys,
        ["--confirm"],
        settings=settings(REMOTE, embedding_provider="fake"),
        environ={"ALLOW_REMOTE_SEED": "1"},
    )

    assert code == cli.EXIT_REFUSED and "fake" in output.lower()


def test_an_unusable_url_is_reported_without_echoing_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, output = run(
        capsys, ["--confirm"], settings=settings("mysql://user:pw@host/db"), environ={}
    )

    assert code == cli.EXIT_FAILURE and "pw" not in output


def test_missing_configuration_is_reported_generically(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None))  # type: ignore[call-arg]

    code, output = run(capsys, ["--confirm"], environ={})

    assert code == cli.EXIT_FAILURE and "DATABASE_URL" in output


def test_an_unreachable_database_is_reported_without_driver_text(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from eventssound.adapters.db.session import build_engine

    monkeypatch.setattr(cli, "build_engine", build_engine)

    code, output = run(capsys, ["--confirm"], settings=settings(UNREACHABLE_URL), environ={})

    assert code == cli.EXIT_FAILURE
    assert not any(secret in output for secret in SECRETS_IN_UNREACHABLE_URL)


# --- against a real database ----------------------------------------------------------------------


def stored(url: str) -> int:
    from sqlalchemy import create_engine

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT count(*) FROM catalog_embeddings")).scalar_one()
    finally:
        engine.dispose()


@pytest.fixture
def real_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    from eventssound.adapters.db.session import build_engine

    monkeypatch.setattr(cli, "build_engine", build_engine)


def test_main_embeds_the_seeded_catalog_and_a_second_run_embeds_nothing(
    session_factory, migrated_database: str, real_engine: None,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    seed_catalog(session_factory, SEED_ITEMS, SEED_PACKAGES)
    cfg = settings(migrated_database)
    allow = {"ALLOW_REMOTE_SEED": "1"}  # the CI database host may not be on the local list
    if make_url(migrated_database).host not in cli.LOCAL_HOSTS:
        pytest.skip("fake embeddings are refused on a non-local database host")

    first, out1 = run(capsys, ["--confirm"], settings=cfg, environ=allow)
    second, out2 = run(capsys, ["--confirm"], settings=cfg, environ=allow)

    assert (first, second) == (0, 0)
    assert "embedded 24, skipped 0, deleted 0" in out1
    assert "embedded 0, skipped 24, deleted 0" in out2
    assert stored(migrated_database) == 24
    password = make_url(migrated_database).password
    assert not password or password not in out1 + out2


def test_a_database_without_the_migration_is_refused_with_exit_4(
    database_url: str, real_engine: None, capsys: pytest.CaptureFixture[str]
) -> None:
    from conftest import reset_schema

    if make_url(database_url).host not in cli.LOCAL_HOSTS:
        pytest.skip("needs a local database host")
    reset_schema(database_url)

    code, _ = run(capsys, ["--confirm"], settings=settings(database_url), environ={})

    assert code == cli.EXIT_SCHEMA
