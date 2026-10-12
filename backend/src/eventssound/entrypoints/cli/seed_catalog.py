"""Guarded CLI that loads the synthetic catalog.

Run it as `python -m eventssound.entrypoints.cli.seed_catalog`.

Safety rules, all enforced before any connection is opened:
- nothing happens without `--confirm` (a dry run prints what would be seeded and exits 2);
- a non-local database host, or `APP_ENV=production`, is refused (exit 3) unless the environment
  variable `ALLOW_REMOTE_SEED` is exactly `1`;
- the demo bookings (fixed dates, they would block real stock) are only seeded on a local,
  non-production target and never with `--no-bookings`;
- output never contains the connection string, host, user, password or driver error text.

After the connection is configured, and before writing, the script checks that `alembic_version`
holds the head revision of the migration scripts (exit 4 otherwise).

`ALLOW_REMOTE_SEED` is read here via `os.environ` (injectable as `environ`) and deliberately is
NOT a `Settings` field: it is a one-off operator override of this script, not application
configuration, so it must not appear in `.env.example` or be set by a deploy. The libpq variables
`PGHOST`, `PGHOSTADDR`, `PGSERVICE` and `PGSERVICEFILE` are read from the same mapping, because
libpq uses them to fill in or override the host of the URL. This is the single, documented
exception to "environment variables are read only through Settings".
"""

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.db.seed import seed_catalog
from eventssound.adapters.db.seed_data import SEED_BOOKINGS, SEED_ITEMS, SEED_PACKAGES
from eventssound.adapters.db.session import build_engine, build_session_factory
from eventssound.adapters.db.storage import check_schema
from eventssound.application.errors import (
    AuthenticationFailed,
    ConnectionFailed,
    RepositoryUnavailable,
    SchemaNotReady,
)
from eventssound.config import Settings
from eventssound.domain.errors import DomainError

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db"})
EXIT_FAILURE, EXIT_DRY_RUN, EXIT_REFUSED, EXIT_SCHEMA = 1, 2, 3, 4
# Where the migration scripts live: next to the working directory (the container, `backend/`)
# or next to the source tree (running from elsewhere in a checkout).
MIGRATION_DIRECTORIES = (
    Path.cwd() / "migrations",
    Path(__file__).resolve().parents[4] / "migrations",
)


def _host_is_local(host: str) -> bool:
    # A leading slash is a unix-socket directory; anything else must be a known local name.
    return host.startswith("/") or host.lower() in LOCAL_HOSTS


def _query_values(url: URL, key: str) -> list[str]:
    # Not trimmed: the resolver would not trim " localhost" either.
    value = url.query.get(key)
    values = [value] if isinstance(value, str) else list(value or ())
    return [part for entry in values for part in entry.split(",")]


def is_local_target(database_url: str, environ: Mapping[str, str] | None = None) -> bool:
    """True only when every host the driver could connect to is local.

    libpq lets the query string and the environment override or fill in the URL host:
    `?host=` values (comma-separated lists included) must all be local, `?hostaddr=`,
    `?service=` and the variables `PGHOSTADDR`, `PGSERVICE`, `PGSERVICEFILE` always count as
    non-local, and `PGHOST` counts when the URL names no host at all. A URL without any host
    means a unix socket and is local. Raises ArgumentError or ValueError when the URL cannot be
    parsed; the caller must not echo that error (it can contain parts of the URL).
    """
    env = os.environ if environ is None else environ
    url = make_url(database_url)
    if "service" in url.query or "hostaddr" in url.query:
        return False  # resolved outside the URL (pg_service.conf) or by raw address
    if any(env.get(name) for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")):
        return False
    hosts = [host for host in (url.host or "", *_query_values(url, "host")) if host]
    if not hosts:
        return not env.get("PGHOST")  # a host-less URL takes its host from PGHOST
    return all(_host_is_local(host) for host in hosts)


def migration_head() -> str:
    """The head revision of the migration scripts; LookupError when they cannot be found."""
    for directory in MIGRATION_DIRECTORIES:
        if (directory / "versions").is_dir():
            config = Config()
            config.set_main_option("script_location", str(directory))
            head = ScriptDirectory.from_config(config).get_current_head()
            if head:
                return head
    raise LookupError("migration scripts not found")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seed_catalog",
        description="Upsert the synthetic catalog into the configured database.",
    )
    parser.add_argument("--confirm", action="store_true", help="actually write to the database")
    parser.add_argument(
        "--no-bookings",
        action="store_true",
        help="seed the catalog only (demo bookings are always skipped on remote or production)",
    )
    return parser


def _is_production(settings: Settings) -> bool:
    return settings.app_env.strip().lower() == "production"


def _storage_failure(error: RepositoryUnavailable) -> int:
    if isinstance(error, SchemaNotReady):
        print(
            "seed failed: the database schema is missing or out of date; "
            "run alembic upgrade head first",
            file=sys.stderr,
        )
        return EXIT_SCHEMA
    if isinstance(error, ConnectionFailed):
        print("seed failed: cannot connect to the database", file=sys.stderr)
    elif isinstance(error, AuthenticationFailed):
        print("seed failed: the database rejected the credentials", file=sys.stderr)
    else:
        print("seed failed: unexpected database error", file=sys.stderr)
    return EXIT_FAILURE


def main(
    argv: Sequence[str] | None = None,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if not args.confirm:
        print(
            f"dry run: would upsert {len(SEED_ITEMS)} items and {len(SEED_PACKAGES)} packages, "
            f"plus {len(SEED_BOOKINGS)} demo bookings on local non-production targets "
            "(--no-bookings skips them). Pass --confirm to write."
        )
        return EXIT_DRY_RUN

    try:
        settings = settings or Settings()  # type: ignore[call-arg]
    except ValidationError:
        print("DATABASE_URL is not configured", file=sys.stderr)
        return EXIT_FAILURE
    env = os.environ if environ is None else environ
    database_url = settings.database_url.get_secret_value()
    try:
        if make_url(database_url).get_backend_name() != "postgresql":
            raise ArgumentError("unsupported database")
        local = is_local_target(database_url, env)
    except (ArgumentError, ValueError):
        print("DATABASE_URL is not a usable PostgreSQL URL", file=sys.stderr)
        return EXIT_FAILURE

    production = _is_production(settings)
    if (not local or production) and env.get("ALLOW_REMOTE_SEED") != "1":
        print(
            "refusing to seed a non-local or production target; "
            "set ALLOW_REMOTE_SEED=1 to override",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    try:
        expected_revision = migration_head()
    except LookupError:
        print("seed failed: migration scripts not found", file=sys.stderr)
        return EXIT_FAILURE

    skip_reason = None
    if args.no_bookings:
        skip_reason = "--no-bookings"
    elif not local or production:
        skip_reason = "remote or production target"
    bookings = () if skip_reason else SEED_BOOKINGS

    engine = None
    if session_factory is None:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
    try:
        check_schema(session_factory, expected_revision)
        result = seed_catalog(session_factory, SEED_ITEMS, SEED_PACKAGES, bookings)
    except RepositoryUnavailable as error:
        return _storage_failure(error)
    except DomainError:
        print("seed failed: the seed definitions are invalid", file=sys.stderr)
        return EXIT_FAILURE
    finally:
        if engine is not None:
            engine.dispose()
    target = "local" if local else "remote"
    if skip_reason:
        print(
            f"seeded {result.items} items and {result.packages} packages (target: {target}); "
            f"demo bookings: skipped ({skip_reason})"
        )
    else:
        print(
            f"seeded {result.items} items, {result.packages} packages "
            f"and {result.bookings} demo bookings (target: {target})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
