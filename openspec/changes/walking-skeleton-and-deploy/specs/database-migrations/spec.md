# Delta Spec: database-migrations

New capability. Verified by pytest against Postgres (Compose locally, service container in CI) and a CLI step.

## ADDED Requirements

### Requirement: Local Postgres service
`docker-compose.yml` MUST define a `db` Postgres service so that `docker compose up db` yields a reachable database for the backend using values from `.env.example`.

#### Scenario: Backend connects locally
- GIVEN `docker compose up db` is running and `DATABASE_URL` points to it
- WHEN the session factory executes `SELECT 1`
- THEN it returns 1

### Requirement: SQLAlchemy 2.0 setup
The backend MUST build the engine and session factory from `DATABASE_URL` in the `adapters` layer, using SQLAlchemy 2.0 style APIs, and expose a declarative `Base` metadata for Alembic.

#### Scenario: Session provided via DI
- GIVEN the app factory with a test database URL
- WHEN a dependency requests a session
- THEN a session bound to that URL is yielded and closed after use

### Requirement: Alembic baseline
Alembic MUST be initialised, wired to the `Base` metadata and `DATABASE_URL` (no credentials in `alembic.ini`), with one empty baseline revision.

#### Scenario: Upgrade to head
- GIVEN an empty Postgres database
- WHEN `alembic upgrade head` runs
- THEN it exits 0 and `alembic_version` holds the baseline revision id

#### Scenario: Idempotent upgrade
- GIVEN the database is already at head
- WHEN `alembic upgrade head` runs again
- THEN it exits 0 with no changes

#### Scenario: Downgrade is a no-op
- GIVEN the database is at head
- WHEN `alembic downgrade base` runs
- THEN it exits 0 and no application tables exist

#### Scenario: Single head
- GIVEN the migration scripts
- WHEN `alembic heads` runs
- THEN exactly one head is reported
