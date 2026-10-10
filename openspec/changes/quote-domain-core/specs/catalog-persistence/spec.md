# Delta Spec: catalog-persistence

Change: quote-domain-core. Builds on the `database-migrations` capability of walking-skeleton-and-deploy (Alembic, `Base`, naming convention).

## ADDED Requirements

### Requirement: Schema
The database MUST contain tables `equipment_items`, `service_packages`, `package_items` and `bookings`, with Postgres snake_case English names, `id` primary keys, `<entity>_id` foreign keys, and timezone-aware `*_at` timestamps.

- `equipment_items`: `code` (unique, NOT NULL, stable English slug), `display_name`, `category`, `stock_quantity` (>= 0), `unit_price_cop` (BIGINT, >= 0).
- `service_packages`: `code` (unique), `display_name`, `description`, `discount_bps` (0..10000).
- `package_items`: `package_id` FK, `item_id` FK, `quantity` (> 0); unique on (`package_id`, `item_id`); deleting a package cascades to its rows, deleting an item referenced by a package is restricted.
- `bookings`: `item_id` FK, `quantity` (> 0), `starts_at`, `ends_at` (timestamptz, `ends_at > starts_at`), `status` (constrained set including `pending`, `confirmed`, `cancelled`), `created_at`; index supporting lookup by (`item_id`, `starts_at`, `ends_at`).

Money columns MUST be integer whole pesos named `*_cop`; floats and `Numeric` MUST NOT be used for money. Monetary decimals MUST NOT be stored as cents. Check constraints MUST have explicit short `name=` values; constraint and index names MUST come from `NAMING_CONVENTION`. Models MUST subclass `Base` and live in `adapters/db/`, never in `domain/`.

#### Scenario: Constraints enforced
- Given a migrated database
- When inserting an item with negative stock, a booking with `ends_at <= starts_at`, a duplicate item `code`, or a package item with quantity 0
- Then the database rejects each insert with an integrity error

#### Scenario: Naming compliance
- Given the migrated schema
- When constraints and indexes are listed
- Then all names follow `pk_`, `fk_`, `uq_`, `ck_`, `ix_` conventions

#### Scenario: Timestamps keep timezone
- Given a booking stored from a UTC-5 datetime
- When it is read back
- Then it is timezone-aware and represents the same instant

### Requirement: Reversible migrations
Schema MUST be created by Alembic revisions numbered after `0001_baseline` (two revisions: catalog tables, then package and bookings tables). Each revision MUST have a working `downgrade()`. The history MUST keep exactly one head. Revisions MUST contain schema only; seed data MUST NOT be inserted by migrations.

#### Scenario: Upgrade, repeat, downgrade
- Given an empty database
- When `upgrade head`, `upgrade head` again, and `downgrade base` are run
- Then each step succeeds, the repeat is a no-op, and the four tables are absent after downgrade

#### Scenario: Single head
- Given the migrations directory
- When heads are listed
- Then exactly one head exists

#### Scenario: No data in migrations
- Given a freshly migrated database
- When rows are counted
- Then all four tables are empty

### Requirement: Repository ports in the application layer
`application/` MUST define Protocol ports for reading the catalog (list items, list packages with members, get item/package by code) and for reading bookings by item and interval. Ports MUST use domain types, MUST NOT import SQLAlchemy, FastAPI or adapters, and use cases MUST depend only on ports. The architecture test (`test_architecture.py`) MUST keep passing.

#### Scenario: Dependency rule
- Given the new modules
- When the architecture test runs
- Then no domain module imports framework code and no application module imports adapters

### Requirement: SQLAlchemy adapters
`adapters/db/` MUST implement the ports with SQLAlchemy 2.0 sync sessions, receive the session factory in `__init__`, map rows to domain objects (never leak ORM objects), run one use case call in one transaction, and roll back on exception. Errors MUST NOT contain connection strings, hosts or credentials.

#### Scenario: Round trip
- Given seeded rows
- When the catalog adapter lists items and packages
- Then it returns domain objects with integer `Money` prices and package members with quantities

#### Scenario: Bookings by interval
- Given bookings inside and outside a window
- When the booking adapter is queried for an item and window
- Then it returns every non-cancelled booking whose interval may influence the window after buffer expansion (the adapter takes the buffer or a widened window as input)

### Requirement: DB test policy
Tests needing a database MUST skip cleanly when `DATABASE_URL_TEST` is unset and MUST fail (never skip) when it is set but unreachable. Tests MUST NOT target a production database.

#### Scenario: Unset
- Given `DATABASE_URL_TEST` is unset
- When the suite runs
- Then DB tests are reported as skipped and unit tests still run

#### Scenario: Set but unreachable
- Given `DATABASE_URL_TEST` is set to an unreachable database
- When DB tests run
- Then they fail with an error that does not print the connection string
