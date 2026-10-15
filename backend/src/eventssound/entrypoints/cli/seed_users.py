"""Guarded CLI that creates the two synthetic demo accounts (one admin, one client).

Run it as `python -m eventssound.entrypoints.cli.seed_users`. It reuses the safety rules of
`seed_catalog`: no write without `--confirm` (dry run exits 2), a non-local database or
`APP_ENV=production` is refused (exit 3) unless `ALLOW_REMOTE_SEED=1`, and the schema must be at
the head revision (exit 4).

The passwords come from `SEED_ADMIN_PASSWORD` and `SEED_CLIENT_PASSWORD` (at least 12
characters), read through the injectable `environ` like `ALLOW_REMOTE_SEED`; they are not
`Settings` fields. Only argon2id hashes reach the database and nothing printed contains a
password, a hash, the connection string or driver error text.
"""

import argparse
import os
import sys
from collections.abc import Mapping, Sequence

from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.auth.hasher import Argon2Hasher
from eventssound.adapters.db.session import build_engine, build_session_factory
from eventssound.adapters.db.storage import check_schema
from eventssound.adapters.db.user_seed import SeedUser, seed_users
from eventssound.application.errors import RepositoryUnavailable
from eventssound.config import Settings
from eventssound.domain.user import Role
from eventssound.entrypoints.cli.seed_catalog import (
    EXIT_DRY_RUN,
    EXIT_FAILURE,
    EXIT_REFUSED,
    _is_production,
    _storage_failure,
    is_local_target,
    migration_head,
)

MIN_PASSWORD_CHARS = 12
ACCOUNTS = (
    ("admin@eventsounddr.example", Role.ADMIN, "SEED_ADMIN_PASSWORD"),
    ("cliente@eventsounddr.example", Role.CLIENT, "SEED_CLIENT_PASSWORD"),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seed_users", description="Upsert the synthetic admin and client accounts."
    )
    parser.add_argument("--confirm", action="store_true", help="actually write to the database")
    return parser


def main(
    argv: Sequence[str] | None = None,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    env = os.environ if environ is None else environ
    if not args.confirm:
        names = ", ".join(variable for _, _, variable in ACCOUNTS)
        print(
            f"dry run: would upsert {len(ACCOUNTS)} accounts (admin and client). "
            f"Set {names} (min {MIN_PASSWORD_CHARS} characters) and pass --confirm to write."
        )
        return EXIT_DRY_RUN

    for _, _, variable in ACCOUNTS:
        if len(env.get(variable, "")) < MIN_PASSWORD_CHARS:
            print(
                f"{variable} must be set to at least {MIN_PASSWORD_CHARS} characters",
                file=sys.stderr,
            )
            return EXIT_FAILURE

    try:
        settings = settings or Settings()  # type: ignore[call-arg]
    except ValidationError:
        print("DATABASE_URL is not configured", file=sys.stderr)
        return EXIT_FAILURE
    database_url = settings.database_url.get_secret_value()
    try:
        if make_url(database_url).get_backend_name() != "postgresql":
            raise ArgumentError("unsupported database")
        local = is_local_target(database_url, env)
    except (ArgumentError, ValueError):
        print("DATABASE_URL is not a usable PostgreSQL URL", file=sys.stderr)
        return EXIT_FAILURE
    if (not local or _is_production(settings)) and env.get("ALLOW_REMOTE_SEED") != "1":
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

    hasher = Argon2Hasher()
    users = [
        SeedUser(email, role, hasher.hash(env[variable])) for email, role, variable in ACCOUNTS
    ]
    engine = None
    if session_factory is None:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
    try:
        check_schema(session_factory, expected_revision)
        written = seed_users(session_factory, users)
    except RepositoryUnavailable as error:
        return _storage_failure(error)
    finally:
        if engine is not None:
            engine.dispose()
    print(f"seeded {written} accounts (target: {'local' if local else 'remote'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
