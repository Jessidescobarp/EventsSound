---
name: database-conventions
description: "Trigger: database, table, column, index, Alembic migration, SQLAlchemy session, Neon, pgvector, DATABASE_URL. Apply Postgres schema and migration rules."
metadata:
  author: Jessid Alberto Escobar Palacio
  version: "1.0"
---

## Activation Contract

Use when creating or changing tables, models, migrations, sessions, database settings, or database tests in `backend/`.

## Hard Rules

Naming (Postgres, snake_case, ASCII, English):

- Tables: plural nouns (`events`, `equipment_items`). Columns: singular (`starts_at`, `unit_price_cents`).
- Primary key `id`; foreign key `<entity>_id`; timestamps `*_at` (timezone-aware); booleans `is_*`/`has_*`.
- Money as integer cents or `Numeric`, never float.
- Money: `*_cents` is the generic example; COP has no practical minor unit, so this project stores whole pesos in `*_cop` BIGINT columns (see the quote-domain-core design). Never float.
- Constraint and index names are generated, not hand-written. `adapters/db/session.py` sets `NAMING_CONVENTION` on `Base.metadata`:

```python
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
```

- Check constraints need an explicit short `name=` (the convention uses it).
- Models subclass `Base` from `eventssound.adapters.db.session`; they live in `adapters/db/`, never in `domain/`.
- Data is synthetic only. Never seed real customer data.

## Alembic rules

Files: `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/versions/NNNN_slug.py` (baseline: `0001_baseline.py`).

- `env.py` reads the URL from `Settings` (not from `alembic.ini`) and targets `Base.metadata`. Autogenerate output must be reviewed by hand.
- Every revision has a working `downgrade()`. `test_migrations.py` runs upgrade, repeat upgrade (no-op), and downgrade to `base`.
- Exactly one head (`test_there_is_exactly_one_head`). Rebase and renumber instead of merging heads.
- One concern per revision: schema changes and data changes go in separate revisions.
- Never edit a revision that has been merged; add a new one.
- Safe changes on a live table: add nullable column, backfill in a later revision, then add `NOT NULL`. Drop in two steps (stop using, then drop).
- `CREATE EXTENSION IF NOT EXISTS vector` (pgvector) is planned for P2 in its own revision. Local and CI use the `pgvector/pgvector:pg16` image (planned in compose/CI); Neon supports the extension. Vector columns and indexes (HNSW/IVFFlat) are planned; do not add them before a feature needs them.
- Migrations run at container start (`alembic upgrade head` in `start.sh`, planned) because the free host has no pre-deploy hook.
- Use the direct (non-pooled) Neon endpoint for migrations; DDL and pooled connections do not mix.

## Sessions and transactions

- The engine is created lazily (`build_engine`); no connection opens at import or app creation.
- Engine settings tuned for a suspending serverless database: `pool_pre_ping=True`, `pool_recycle=300`, `pool_size=3`, `max_overflow=2`, `connect_timeout=10`.
- `sessionmaker(expire_on_commit=False)`; sessions are short-lived and opened with `with factory() as session:`.
- Adapters receive the session factory in `__init__` (see `SqlAlchemyDatabaseHealth`); use cases never see a `Session`.
- One use case call equals one transaction; commit explicitly in the adapter, roll back on exception.
- Sync SQLAlchemy plus psycopg 3 is the chosen stack; do not mix in async engines.

## URL and secrets

- `DATABASE_URL` is a `SecretStr` in `Settings`; call `.get_secret_value()` only where the engine is built.
- A validator rewrites `postgres://` and `postgresql://` to `postgresql+psycopg://`, keeping query params such as `sslmode`.
- Never print, log, or put a connection string in an exception message or docs. Never read `.env*` files in tooling.
- Errors returned to clients carry no host, user, or driver detail.

## Decision Gates

| Situation | Action |
| --------- | ------ |
| Need a new table | Model in `adapters/db/`, autogenerate, review, add test |
| Change existing column | New revision, expand then contract |
| Need test data | Fixtures or factories in tests, not migrations |
| Need a database in tests | Throwaway local Postgres via `DATABASE_URL_TEST` |
| Tempted to point tests at the Neon production branch | Never. Use a Neon dev branch or local Postgres |

## Execution Steps

1. Write the failing test (`DATABASE_URL_TEST` set locally).
2. Edit the model, run `uv run alembic revision --autogenerate -m "<slug>"`.
3. Review the revision, write `downgrade()`, confirm a single head.
4. Run upgrade, downgrade to `base`, upgrade again.
5. Run `uv run pytest` and `uv run ruff check .`.

## Output Contract

Report: revision id, forward and backward verification, naming-convention compliance, and confirmation that no secret or real host was written anywhere.

## References

- `backend/src/eventssound/adapters/db/session.py`, `backend/migrations/env.py` (branch `feat/backend-db-docker`)
- `openspec/changes/walking-skeleton-and-deploy/specs/database-migrations/spec.md`
