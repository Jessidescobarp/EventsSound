"""Guarded CLI that embeds the catalog for vector search.

Run it as `python -m eventssound.entrypoints.cli.embed_catalog --confirm` from the developer's
machine; the app never refreshes embeddings at runtime. The guard is the one of the seed CLI:

- nothing happens without `--confirm` (a dry run exits 2 and opens no connection);
- a non-local database host, or `APP_ENV=production`, is refused (exit 3) unless the environment
  variable `ALLOW_REMOTE_SEED` is exactly `1`;
- the deterministic `fake` provider is NEVER written to a remote or production database, override
  or not: its vectors carry no meaning and would poison retrieval;
- the migration head must be applied first (exit 4) and the catalog must not be empty;
- rows of any OTHER embedding model are deleted (one active model): run it with the model
  the deployed app uses, or retrieval silently falls back to keywords;
- output has counts only, never the URL, host, user, password, key or driver text.

`ALLOW_REMOTE_SEED` is read here via `os.environ` (injectable as `environ`) for the same reason
as in the seed CLI: it is a one-off operator override, not application configuration. This module
is the second documented exception to "environment variables are read only through Settings".
"""

import argparse
import os
import sys
from collections.abc import Mapping, Sequence

from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from eventssound.adapters.db.catalog_repository import SqlAlchemyCatalogRepository
from eventssound.adapters.db.embedding_store import SqlAlchemyEmbeddingStore
from eventssound.adapters.db.session import build_engine, build_session_factory
from eventssound.adapters.db.storage import check_schema
from eventssound.adapters.embeddings.fake import FakeEmbeddingProvider
from eventssound.adapters.embeddings.openrouter import OpenRouterEmbeddingProvider
from eventssound.application.catalog import list_catalog
from eventssound.application.embedding_index import refresh_embeddings
from eventssound.application.embeddings import EmbeddingProvider
from eventssound.application.errors import (
    AuthenticationFailed,
    ConnectionFailed,
    InvalidStoredData,
    RepositoryUnavailable,
    SchemaNotReady,
)
from eventssound.application.llm import LlmError
from eventssound.config import Settings
from eventssound.entrypoints.cli.seed_catalog import LOCAL_HOSTS, is_local_target, migration_head

__all__ = ["LOCAL_HOSTS", "main"]

EXIT_FAILURE, EXIT_DRY_RUN, EXIT_REFUSED, EXIT_SCHEMA = 1, 2, 3, 4
FAKE_MODEL = "fake-embedding"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="embed_catalog",
        description="Embed the catalog with the configured provider (idempotent).",
    )
    parser.add_argument("--confirm", action="store_true", help="actually write to the database")
    return parser


def _build_embedder(settings: Settings) -> tuple[EmbeddingProvider, str]:
    if settings.embedding_provider == "fake":
        return FakeEmbeddingProvider(settings.embedding_dimensions, FAKE_MODEL), FAKE_MODEL
    embedder = OpenRouterEmbeddingProvider(
        settings.openrouter_api_key, settings.embedding_model, settings.embedding_dimensions
    )
    return embedder, settings.embedding_model


def _storage_failure(error: RepositoryUnavailable) -> int:
    if isinstance(error, SchemaNotReady):
        print(
            "embed failed: the database schema is missing or out of date; "
            "run alembic upgrade head first",
            file=sys.stderr,
        )
        return EXIT_SCHEMA
    if isinstance(error, ConnectionFailed):
        print("embed failed: cannot connect to the database", file=sys.stderr)
    elif isinstance(error, AuthenticationFailed):
        print("embed failed: the database rejected the credentials", file=sys.stderr)
    else:
        print("embed failed: unexpected database error", file=sys.stderr)
    return EXIT_FAILURE


def main(
    argv: Sequence[str] | None = None,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    environ: Mapping[str, str] | None = None,
    embedder: EmbeddingProvider | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if not args.confirm:
        print("dry run: would embed the catalog with the configured provider. Pass --confirm.")
        return EXIT_DRY_RUN

    try:
        settings = settings or Settings()  # type: ignore[call-arg]
    except ValidationError:
        print("DATABASE_URL or the embedding settings are not valid", file=sys.stderr)
        return EXIT_FAILURE
    if settings.embedding_provider == "off":
        print("EMBEDDING_PROVIDER is off: set it to fake or openrouter first", file=sys.stderr)
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

    production = settings.app_env.strip().lower() == "production"
    if (not local or production) and env.get("ALLOW_REMOTE_SEED") != "1":
        print(
            "refusing to write to a non-local or production target; "
            "set ALLOW_REMOTE_SEED=1 to override",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if (not local or production) and settings.embedding_provider == "fake":
        print(
            "refusing to write fake embeddings to a non-local or production target",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    try:
        expected_revision = migration_head()
    except LookupError:
        print("embed failed: migration scripts not found", file=sys.stderr)
        return EXIT_FAILURE

    engine = None
    if session_factory is None:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
    provider, model = (embedder, settings.embedding_model or FAKE_MODEL) if embedder else (None, "")
    try:
        check_schema(session_factory, expected_revision)
        if provider is None:
            provider, model = _build_embedder(settings)
        catalog = list_catalog(SqlAlchemyCatalogRepository(session_factory))
        if not catalog.items:
            # Refreshing an empty catalog would delete every stored embedding.
            print("embed failed: the catalog is empty (seed it first)", file=sys.stderr)
            return EXIT_FAILURE
        result = refresh_embeddings(
            catalog, provider, SqlAlchemyEmbeddingStore(session_factory), model
        )
    except RepositoryUnavailable as error:
        return _storage_failure(error)
    except InvalidStoredData:
        print("embed failed: a stored catalog row is invalid", file=sys.stderr)
        return EXIT_FAILURE
    except LlmError:
        print("embed failed: the embedding provider did not answer usably", file=sys.stderr)
        return EXIT_FAILURE
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
        if engine is not None:
            engine.dispose()
    print(
        f"embedded {result.embedded}, skipped {result.skipped}, deleted {result.deleted} "
        f"(target: {'local' if local else 'remote'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
