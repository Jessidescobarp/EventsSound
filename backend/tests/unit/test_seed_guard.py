"""The seed CLI guard: confirmation, local-host check and secret-free output. No database."""

import pytest
from sqlalchemy.exc import OperationalError

from eventssound.config import Settings
from eventssound.entrypoints.cli import seed_catalog as cli

SENTINELS = ("sentinel_user", "sentinel_pw", "sentinel-host", "sentinel_db")
REMOTE_URL = (
    "postgresql+psycopg://sentinel_user:sentinel_pw@sentinel-host.example.com:5432/sentinel_db"
)


def url_for(host: str, query: str = "") -> str:
    return f"postgresql+psycopg://sentinel_user:sentinel_pw@{host}/sentinel_db{query}"


def settings_for(url: str, app_env: str = "local") -> Settings:
    return Settings(_env_file=None, DATABASE_URL=url, app_env=app_env)  # type: ignore[call-arg]


class RecordingFactory:
    """Stands in for a sessionmaker; every use fails like an unreachable database would."""

    def __init__(self) -> None:
        self.calls = 0

    def begin(self):
        self.calls += 1
        raise OperationalError("SELECT 1", {}, Exception("could not connect to sentinel-host"))


def assert_no_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    captured = capsys.readouterr()
    for secret in SENTINELS:
        assert secret not in captured.out + captured.err


@pytest.fixture(autouse=True)
def no_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("an engine must not be built in these tests")

    monkeypatch.setattr(cli, "build_engine", forbidden)
    monkeypatch.delenv("ALLOW_REMOTE_SEED", raising=False)


@pytest.mark.parametrize(
    ("url", "local"),
    [
        (url_for("localhost:5432"), True),
        (url_for("LOCALHOST"), True),
        (url_for("127.0.0.1:5433"), True),
        (url_for("[::1]:5432"), True),
        (url_for("db"), True),
        ("postgresql+psycopg:///sentinel_db", True),
        ("postgresql+psycopg://sentinel_user@/sentinel_db?host=/var/run/postgresql", True),
        (url_for("localhost", "?host=localhost"), True),
        (url_for("ep-cool-123.us-east-2.aws.neon.tech"), False),
        (url_for("10.0.0.5"), False),
        (url_for("0.0.0.0"), False),
        (url_for("localhost.evil.example.com"), False),
        (url_for("127.0.0.1.nip.io"), False),
        (url_for("dbserver"), False),
        ("postgresql+psycopg:///sentinel_db?host=remote.example.com", False),
        ("postgresql+psycopg:///sentinel_db?host=localhost,remote.example.com", False),
        ("postgresql+psycopg:///sentinel_db?hostaddr=10.0.0.1", False),
        ("postgresql+psycopg:///sentinel_db?service=production", False),
        (url_for("localhost", "?host=remote.example.com"), False),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_target_classification(url: str, local: bool) -> None:
    assert cli.is_local_target(url) is local


def test_dry_run_exits_2_and_touches_nothing(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    factory = RecordingFactory()

    code = cli.main([], session_factory=factory)

    assert code == 2
    assert factory.calls == 0
    out = capsys.readouterr().out
    assert "dry run: would upsert 20 items, 4 packages and 5 demo bookings" in out
    assert "--confirm" in out


def test_unknown_arguments_are_rejected_by_the_parser(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["--confirm", "--remote"], settings=settings_for(REMOTE_URL))

    assert caught.value.code == 2
    assert_no_secrets(capsys)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]", "db"])
def test_local_hosts_proceed_without_any_override(
    host: str, capsys: pytest.CaptureFixture[str]
) -> None:
    factory = RecordingFactory()

    code = cli.main(["--confirm"], settings=settings_for(url_for(host)), session_factory=factory)

    assert factory.calls == 1
    assert code == 1  # the fake database is down; the guard itself let the run through
    assert_no_secrets(capsys)


@pytest.mark.parametrize(
    "allow", [None, "true", "0", "", "yes", " 1", "1 ", "11", "TRUE"], ids=repr
)
def test_remote_host_is_refused_unless_the_flag_is_exactly_1(
    allow: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    factory = RecordingFactory()
    environ = {} if allow is None else {"ALLOW_REMOTE_SEED": allow}

    code = cli.main(
        ["--confirm"], settings=settings_for(REMOTE_URL), session_factory=factory, environ=environ
    )

    assert code == 3
    assert factory.calls == 0
    assert "refusing to seed" in capsys.readouterr().err


def test_remote_host_proceeds_with_the_explicit_override(
    capsys: pytest.CaptureFixture[str],
) -> None:
    factory = RecordingFactory()

    cli.main(
        ["--confirm"],
        settings=settings_for(REMOTE_URL),
        session_factory=factory,
        environ={"ALLOW_REMOTE_SEED": "1"},
    )

    assert factory.calls == 1
    assert_no_secrets(capsys)


def test_the_flag_is_read_from_the_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = RecordingFactory()
    settings = settings_for(REMOTE_URL)

    assert cli.main(["--confirm"], settings=settings, session_factory=factory) == 3
    monkeypatch.setenv("ALLOW_REMOTE_SEED", "1")
    cli.main(["--confirm"], settings=settings, session_factory=factory)

    assert factory.calls == 1


@pytest.mark.parametrize("app_env", ["production", "Production", " PRODUCTION "])
def test_production_needs_the_override_even_on_a_local_host(
    app_env: str, capsys: pytest.CaptureFixture[str]
) -> None:
    factory = RecordingFactory()
    settings = settings_for(url_for("localhost"), app_env)

    assert cli.main(["--confirm"], settings=settings, session_factory=factory, environ={}) == 3
    assert factory.calls == 0
    cli.main(
        ["--confirm"],
        settings=settings,
        session_factory=factory,
        environ={"ALLOW_REMOTE_SEED": "1"},
    )

    assert factory.calls == 1
    assert_no_secrets(capsys)


def test_a_database_failure_is_reported_without_driver_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli.main(
        ["--confirm"],
        settings=settings_for(url_for("localhost")),
        session_factory=RecordingFactory(),
    )

    assert code == 1
    captured = capsys.readouterr()
    assert "database is unavailable" in captured.err
    assert "could not connect" not in captured.out + captured.err


@pytest.mark.parametrize("url", ["not a url", "mysql://sentinel_user:sentinel_pw@h/sentinel_db"])
def test_an_unusable_database_url_is_reported_without_echoing_it(
    url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    factory = RecordingFactory()

    code = cli.main(["--confirm"], settings=settings_for(url), session_factory=factory)

    assert code == 1
    assert factory.calls == 0
    assert_no_secrets(capsys)


def test_missing_configuration_is_reported_generically(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None))

    assert cli.main(["--confirm"]) == 1
    assert "DATABASE_URL is not configured" in capsys.readouterr().err


def test_the_flag_is_not_a_settings_field() -> None:
    assert not [name for name in Settings.model_fields if "remote" in name.lower()]
