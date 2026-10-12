"""Guarded CLI that loads the synthetic catalog.

Run it as `python -m eventssound.entrypoints.cli.seed_catalog`.

Safety rules, all enforced before any connection is opened:
- nothing happens without `--confirm` (a dry run prints what would be seeded and exits 2);
- a non-local database host, or `APP_ENV=production`, is refused (exit 3) unless the environment
  variable `ALLOW_REMOTE_SEED` is exactly `1`;
- output never contains the connection string, host, user, password or driver error text.

`ALLOW_REMOTE_SEED` is read here via `os.environ` (injectable as `environ`) and deliberately is
NOT a `Settings` field: it is a one-off operator override of this script, not application
configuration, so it must not appear in `.env.example` or be set by a deploy. This is the single,
documented exception to "environment variables are read only through Settings".
"""

import argparse
import os
import sys
from collections.abc import Mapping, Sequence

from pydantic import ValidationError
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.db.seed import seed_catalog
from eventssound.adapters.db.seed_data import SEED_BOOKINGS, SEED_ITEMS, SEED_PACKAGES
from eventssound.adapters.db.session import build_engine, build_session_factory
from eventssound.application.errors import RepositoryUnavailable
from eventssound.config import Settings
from eventssound.domain.errors import DomainError

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db"})
EXIT_FAILURE, EXIT_DRY_RUN, EXIT_REFUSED = 1, 2, 3


def _host_is_local(host: str) -> bool:
    # A leading slash is a unix-socket directory; anything else must be a known local name.
    return host.startswith("/") or host.lower() in LOCAL_HOSTS


def _query_values(url: URL, key: str) -> list[str]:
    value = url.query.get(key)
    values = [value] if isinstance(value, str) else list(value or ())
    return [part.strip() for entry in values for part in entry.split(",")]


def is_local_target(database_url: str) -> bool:
    """True only when every host the driver could connect to is local.

    libpq lets `?host=`, `?hostaddr=` and `?service=` override the URL host, so they count too.
    A URL without any host means a unix socket and is local. Raises ArgumentError when the URL
    cannot be parsed; the caller must not echo that error (it can contain the URL).
    """
    url = make_url(database_url)
    if "service" in url.query:
        return False  # resolved through pg_service.conf, which this script cannot inspect
    if "hostaddr" in url.query:
        return False  # a raw address bypasses name resolution; require the explicit override
    hosts = [url.host or "", *_query_values(url, "host")]
    return all(_host_is_local(host) for host in hosts if host)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seed_catalog",
        description="Upsert the synthetic catalog into the configured database.",
    )
    parser.add_argument("--confirm", action="store_true", help="actually write to the database")
    return parser


def _is_production(settings: Settings) -> bool:
    return settings.app_env.strip().lower() == "production"


def main(
    argv: Sequence[str] | None = None,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    summary = (
        f"{len(SEED_ITEMS)} items, {len(SEED_PACKAGES)} packages "
        f"and {len(SEED_BOOKINGS)} demo bookings"
    )
    if not args.confirm:
        print(f"dry run: would upsert {summary}. Pass --confirm to write.")
        return EXIT_DRY_RUN

    try:
        settings = settings or Settings()  # type: ignore[call-arg]
    except ValidationError:
        print("DATABASE_URL is not configured", file=sys.stderr)
        return EXIT_FAILURE
    database_url = settings.database_url.get_secret_value()
    try:
        if make_url(database_url).get_backend_name() != "postgresql":
            raise ArgumentError("unsupported database")
        local = is_local_target(database_url)
    except ArgumentError:
        print("DATABASE_URL is not a usable PostgreSQL URL", file=sys.stderr)
        return EXIT_FAILURE

    allowed = (os.environ if environ is None else environ).get("ALLOW_REMOTE_SEED") == "1"
    if (not local or _is_production(settings)) and not allowed:
        print(
            "refusing to seed a non-local or production target; "
            "set ALLOW_REMOTE_SEED=1 to override",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    engine = None
    if session_factory is None:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
    try:
        seed_catalog(session_factory, SEED_ITEMS, SEED_PACKAGES, SEED_BOOKINGS)
    except RepositoryUnavailable:
        print("seed failed: the database is unavailable", file=sys.stderr)
        return EXIT_FAILURE
    except DomainError:
        print("seed failed: the seed definitions are invalid", file=sys.stderr)
        return EXIT_FAILURE
    finally:
        if engine is not None:
            engine.dispose()
    print(f"seeded {summary} (target: {'local' if local else 'remote'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
