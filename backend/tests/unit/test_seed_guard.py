"""The seed CLI guard: confirmation, local-host check and secret-free output. No database."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import ArgumentError, OperationalError

from eventssound.adapters.db.seed import SeedResult
from eventssound.application.errors import (
    AuthenticationFailed,
    ConnectionFailed,
    RepositoryUnavailable,
    SchemaNotReady,
)
from eventssound.config import Settings
from eventssound.domain.errors import InvalidCatalog
from eventssound.entrypoints.cli import seed_catalog as cli

BACKEND_DIR = Path(__file__).resolve().parents[2]
SENTINELS = ("sentinel_user", "sentinel_pw", "sentinel-host", "sentinel_db", "evil")
LIBPQ_ENVIRONMENT = ("PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")
REMOTE_URL = (
    "postgresql+psycopg://sentinel_user:sentinel_pw@sentinel-host.example.com:5432/sentinel_db"
)
HOSTLESS_URL = "postgresql+psycopg:///sentinel_db"


def url_for(host: str, query: str = "") -> str:
    return f"postgresql+psycopg://sentinel_user:sentinel_pw@{host}/sentinel_db{query}"


def settings_for(url: str, app_env: str = "local") -> Settings:
    return Settings(_env_file=None, DATABASE_URL=url, app_env=app_env)  # type: ignore[call-arg]


class RecordingFactory:
    """Stands in for a sessionmaker; every use fails like an unreachable database would."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        return self.begin()

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
    # The schema check has its own tests; here it passes so that the guard logic is what runs.
    monkeypatch.setattr(cli, "migration_head", lambda: "head")
    monkeypatch.setattr(cli, "check_schema", lambda factory, expected: None)
    for name in ("ALLOW_REMOTE_SEED", *LIBPQ_ENVIRONMENT):
        monkeypatch.delenv(name, raising=False)


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
        # Hosts are never trimmed: " localhost" is not "localhost" to the resolver.
        (url_for("", "?host=%20localhost"), False),
        (url_for("", "?host=localhost,%20127.0.0.1"), False),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_target_classification(url: str, local: bool) -> None:
    assert cli.is_local_target(url, environ={}) is local


def test_dry_run_exits_2_and_touches_nothing(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    factory = RecordingFactory()

    code = cli.main([], session_factory=factory)

    assert code == 2
    assert factory.calls == 0
    out = capsys.readouterr().out
    assert "dry run: would upsert 23 items and 4 packages" in out
    assert "5 demo bookings" in out
    assert "--no-bookings" in out
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
    assert "cannot connect to the database" in captured.err
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


def test_invalid_seed_definitions_are_reported_generically(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise InvalidCatalog("detail that must stay out of the output: sentinel_pw")

    monkeypatch.setattr(cli, "seed_catalog", broken)

    code = cli.main(
        ["--confirm"],
        settings=settings_for(url_for("localhost")),
        session_factory=RecordingFactory(),
    )

    assert code == 1
    assert "seed definitions are invalid" in capsys.readouterr().err


# --- libpq environment: a missing host in the URL is filled in by PG* variables -----------------


@pytest.mark.parametrize(
    "environment",
    [
        {"PGHOST": "sentinel-host.example.com"},
        {"PGHOST": "localhost"},
        {"PGHOSTADDR": "10.0.0.5"},
        {"PGSERVICE": "production"},
        {"PGSERVICEFILE": "/etc/pg_service.conf"},
    ],
    ids=lambda environment: next(iter(environment)),
)
def test_a_hostless_url_is_local_only_without_libpq_environment(
    environment: dict[str, str],
) -> None:
    assert cli.is_local_target(HOSTLESS_URL, environ={}) is True
    assert cli.is_local_target(HOSTLESS_URL, environ=environment) is False


@pytest.mark.parametrize(
    ("environment", "local"),
    [
        ({"PGHOSTADDR": "10.0.0.5"}, False),  # connects to the address, whatever the name says
        ({"PGSERVICE": "production"}, False),
        ({"PGHOST": "sentinel-host.example.com"}, True),  # an explicit host wins over PGHOST
        ({"PGHOST": "", "PGHOSTADDR": "", "PGSERVICE": ""}, True),  # empty means unset
    ],
    ids=["pghostaddr", "pgservice", "pghost-overridden", "empty-values"],
)
def test_libpq_environment_with_an_explicit_localhost(
    environment: dict[str, str], local: bool
) -> None:
    assert cli.is_local_target(url_for("localhost"), environ=environment) is local


def test_main_refuses_a_hostless_url_when_pghost_is_set(
    capsys: pytest.CaptureFixture[str],
) -> None:
    factory = RecordingFactory()

    code = cli.main(
        ["--confirm"],
        settings=settings_for(HOSTLESS_URL),
        session_factory=factory,
        environ={"PGHOST": "sentinel-host.example.com"},
    )

    assert code == 3
    assert factory.calls == 0
    assert_no_secrets(capsys)


def test_main_reads_libpq_variables_from_the_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = RecordingFactory()
    settings = settings_for(url_for("localhost"))
    monkeypatch.setenv("PGHOSTADDR", "10.0.0.5")

    assert cli.main(["--confirm"], settings=settings, session_factory=factory) == 3
    assert factory.calls == 0


# --- malformed URLs never raise and never echo a fragment ---------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        url_for("localhost:5432,sentinel-evil:5432"),
        "postgresql+psycopg://sentinel_user:sentinel_pw@[::1/sentinel_db",
        url_for("sentinel-evil:notaport"),
        "not a url",
        "mysql://sentinel_user:sentinel_pw@sentinel-evil/sentinel_db",
    ],
    ids=["multi-host", "bad-ipv6", "bad-port", "garbage", "other-dialect"],
)
def test_malformed_urls_exit_generically_without_a_traceback_or_fragment(
    url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    factory = RecordingFactory()

    code = cli.main(["--confirm"], settings=settings_for(url), session_factory=factory)

    assert code == 1
    assert factory.calls == 0
    captured = capsys.readouterr()
    assert "not a usable PostgreSQL URL" in captured.err
    for secret in SENTINELS:
        assert secret not in captured.out + captured.err


def test_is_local_target_raises_a_parse_error_for_a_multi_host_url() -> None:
    with pytest.raises((ArgumentError, ValueError)):
        cli.is_local_target(url_for("localhost:5432,sentinel-evil:5432"))


# --- the engine is always disposed ---------------------------------------------------------------


class SpyEngine:
    def __init__(self) -> None:
        self.disposed = 0

    def dispose(self) -> None:
        self.disposed += 1


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_the_engine_built_by_the_cli_is_disposed_in_every_case(
    outcome: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy, factory = SpyEngine(), RecordingFactory()
    monkeypatch.setattr(cli, "build_engine", lambda url: spy)
    monkeypatch.setattr(cli, "build_session_factory", lambda engine: factory)
    if outcome == "success":
        monkeypatch.setattr(cli, "seed_catalog", lambda *args, **kwargs: SeedResult(23, 4, 5))

    code = cli.main(["--confirm"], settings=settings_for(url_for("localhost")))

    assert code == (0 if outcome == "success" else 1)
    assert spy.disposed == 1


def test_the_engine_is_disposed_when_the_schema_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = SpyEngine()
    monkeypatch.setattr(cli, "build_engine", lambda url: spy)
    monkeypatch.setattr(cli, "build_session_factory", lambda engine: RecordingFactory())

    def not_ready(factory: object, expected: str) -> None:
        raise SchemaNotReady("old")

    monkeypatch.setattr(cli, "check_schema", not_ready)

    assert cli.main(["--confirm"], settings=settings_for(url_for("localhost"))) == 4
    assert spy.disposed == 1


# --- storage problems get distinct, generic messages ---------------------------------------------


@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (ConnectionFailed("x"), 1, "cannot connect to the database"),
        (AuthenticationFailed("x"), 1, "rejected the credentials"),
        (SchemaNotReady("x"), 4, "run alembic upgrade head first"),
        (RepositoryUnavailable("x"), 1, "unexpected database error"),
    ],
    ids=["connection", "authentication", "schema", "other"],
)
def test_each_storage_problem_has_its_own_message_and_no_url_parts(
    error: Exception,
    code: int,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def failing(factory: object, expected: str) -> None:
        raise error

    monkeypatch.setattr(cli, "check_schema", failing)
    seeded: list[tuple] = []
    monkeypatch.setattr(cli, "seed_catalog", lambda *args, **kwargs: seeded.append(args))

    result = cli.main(
        ["--confirm"],
        settings=settings_for(url_for("localhost")),
        session_factory=RecordingFactory(),
    )

    assert result == code
    assert seeded == []
    captured = capsys.readouterr()
    assert message in captured.err
    for secret in SENTINELS:
        assert secret not in captured.out + captured.err


def test_the_expected_revision_is_the_migration_scripts_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.undo()  # the autouse fixture replaced migration_head
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()

    assert head
    assert cli.migration_head() == head


def test_missing_migration_scripts_are_reported_generically(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.undo()
    monkeypatch.setattr(cli, "MIGRATION_DIRECTORIES", (tmp_path,))

    code = cli.main(
        ["--confirm"],
        settings=settings_for(url_for("localhost")),
        session_factory=RecordingFactory(),
    )

    assert code == 1
    assert "migration scripts not found" in capsys.readouterr().err


# --- demo bookings are catalog-only on remote or production targets ------------------------------


class SeedSpy:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, factory, items, packages, bookings=()):
        self.calls.append((len(tuple(items)), len(tuple(packages)), tuple(bookings)))
        return SeedResult(len(tuple(items)), len(tuple(packages)), len(tuple(bookings)))


def run_seed(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    *,
    argv: tuple[str, ...] = ("--confirm",),
    app_env: str = "local",
    environ: dict[str, str] | None = None,
) -> tuple[int, SeedSpy]:
    spy = SeedSpy()
    monkeypatch.setattr(cli, "seed_catalog", spy)
    code = cli.main(
        list(argv),
        settings=settings_for(url, app_env),
        session_factory=RecordingFactory(),
        environ=environ or {},
    )
    return code, spy


def test_a_local_non_production_run_seeds_the_demo_bookings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, spy = run_seed(monkeypatch, url_for("localhost"))

    assert code == 0
    assert [len(call[2]) for call in spy.calls] == [5]
    out = capsys.readouterr().out
    assert "seeded 23 items, 4 packages and 5 demo bookings (target: local)" in out


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"url": REMOTE_URL, "environ": {"ALLOW_REMOTE_SEED": "1"}}, "remote or production target"),
        (
            {
                "url": url_for("localhost"),
                "app_env": "production",
                "environ": {"ALLOW_REMOTE_SEED": "1"},
            },
            "remote or production target",
        ),
        ({"url": url_for("localhost"), "argv": ("--confirm", "--no-bookings")}, "--no-bookings"),
    ],
    ids=["remote", "production", "flag"],
)
def test_demo_bookings_are_skipped_and_the_summary_says_so(
    kwargs: dict, reason: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, spy = run_seed(monkeypatch, **kwargs)

    assert code == 0
    assert [call[2] for call in spy.calls] == [()]
    captured = capsys.readouterr()
    assert "seeded 23 items and 4 packages" in captured.out
    assert f"demo bookings: skipped ({reason})" in captured.out
    for secret in SENTINELS:
        assert secret not in captured.out + captured.err


def test_no_bookings_is_accepted_on_remote_targets_too(monkeypatch: pytest.MonkeyPatch) -> None:
    code, spy = run_seed(
        monkeypatch,
        REMOTE_URL,
        argv=("--confirm", "--no-bookings"),
        environ={"ALLOW_REMOTE_SEED": "1"},
    )

    assert code == 0
    assert [call[2] for call in spy.calls] == [()]
