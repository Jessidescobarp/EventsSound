# Delta Spec: catalog-persistence

Change: quote-domain-core. Builds on the `database-migrations` capability of walking-skeleton-and-deploy (Alembic, `Base`, naming convention).

## ADDED Requirements

### Requirement: Schema
The database MUST contain exactly four tables, `equipment_items`, `service_packages`, `package_items` and a FLAT `bookings` (scope cut 3, design D10), with Postgres snake_case English names, `id` primary keys, `<entity>_id` foreign keys where a row is referenced by id, and timezone-aware timestamps.

- `equipment_items`: `code` (unique, NOT NULL, stable English slug), `name`, `category` (VARCHAR + CHECK: sound, lighting, dj, stage, effects, video), `stock_quantity` (>= 0), `unit_price_cop` (BIGINT, >= 0), `created_at`, `updated_at`.
- `service_packages`: `code` (unique), `name`, `discount_bps` (0..10000), `created_at`, `updated_at`.
- `package_items`: `package_id` FK, `equipment_item_id` FK, `quantity` (> 0); unique on (`package_id`, `equipment_item_id`); deleting a package cascades to its rows, deleting an item referenced by a package is restricted.
- `bookings`: one row per equipment item per booking: `booking_code` (the domain `Booking.code`), `item_code` (FK to `equipment_items.code`, RESTRICT), `quantity` (> 0), `starts_at`, `ends_at` (timestamptz, `ends_at > starts_at`), `status` (CHECK in `pending`, `confirmed`, `cancelled`), `created_at`, `updated_at`; unique on (`booking_code`, `item_code`); index on (`item_code`, `starts_at`, `ends_at`). There is no `booking_items` table.

Money columns MUST be integer whole pesos named `*_cop`; floats and `Numeric` MUST NOT be used for money. Monetary decimals MUST NOT be stored as cents. Check constraints MUST have explicit short `name=` values; constraint and index names MUST follow `NAMING_CONVENTION` (the migration writes them literally). Domain bounds MUST match the columns so that a valid domain value always fits: names at most 120 characters (`VARCHAR(120)`), integer quantities and stock at most `2**31 - 1` (`INTEGER`), codes at most 64 characters. The CHECK value lists MUST equal the `EquipmentCategory` and `BookingStatus` enums and the numeric CHECK bounds MUST agree with the domain boundaries (tests read `pg_get_constraintdef`). Models MUST subclass `Base` and live in `adapters/db/`, never in `domain/`. `migrations/env.py` MUST import the models module so autogenerate sees the metadata.

#### Scenario: Constraints enforced
- Given a migrated database
- When inserting an item with negative stock, a booking with `ends_at <= starts_at` or quantity <= 0 or an unknown status or an unknown item code, a duplicate item `code`, or a package item with quantity 0
- Then the database rejects each insert with an integrity error naming the violated constraint

#### Scenario: Drift between models and migration
- Given a migrated database
- When the models metadata is compared with the database (`alembic.autogenerate.compare_metadata`)
- Then the difference is empty

#### Scenario: Naming compliance
- Given the migrated schema
- When constraints and indexes are listed
- Then all names follow `pk_`, `fk_`, `uq_`, `ck_`, `ix_` conventions

#### Scenario: Timestamps keep timezone
- Given a booking stored from a UTC-5 datetime
- When it is read back
- Then it is timezone-aware and represents the same instant

### Requirement: Reversible migrations
Schema MUST be created by one Alembic revision after `0001_baseline` (`0002_catalog_and_bookings`: the four tables). The revision MUST have a working `downgrade()` that drops the tables in foreign-key order. The history MUST keep exactly one head. Revisions MUST contain schema only; seed data MUST NOT be inserted by migrations.

#### Scenario: Upgrade, repeat, downgrade
- Given an empty database
- When `upgrade head`, `upgrade head` again, and `downgrade base` are run
- Then each step succeeds, the repeat is a no-op, and the four tables are absent after downgrade (also after `downgrade 0001`, and an upgrade/downgrade/upgrade round trip restores the schema)

#### Scenario: Single head
- Given the migrations directory
- When heads are listed
- Then exactly one head exists

#### Scenario: No data in migrations
- Given a freshly migrated database
- When rows are counted
- Then all four tables are empty

### Requirement: Repository ports in the application layer
`application/` MUST define two Protocol ports: `CatalogRepository.get_catalog() -> Catalog` (whole catalog snapshot) and `BookingRepository.find_reservations(item_codes, window_start, window_end)` (returns item-level `Booking` values; blocking ones at least, the domain ignores cancelled). Ports MUST use domain types, MUST NOT import SQLAlchemy, FastAPI or adapters, and use cases MUST depend only on ports. The booking query input (item codes and a half-open window) is validated by one shared value, `ReservationQuery`: item codes must be a collection of strings (never a bare string), the window must be timezone-aware with `window_end > window_start`, otherwise `InvalidAvailability` is raised before any storage access. Storage failures raise `RepositoryUnavailable`; a stored row that violates the domain contract raises `InvalidStoredData` (neither is a `DomainError`). In-memory fakes (and broken variants raising `RepositoryUnavailable`) live in `tests/fakes.py`. The architecture test (`test_architecture.py`) MUST keep passing.

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
- When the booking adapter is queried for item codes and a window
- Then it returns one `Booking` (with its status and a `code` matching the validated pattern) per stored row of every pending or confirmed booking intersecting the half-open window, ordered by start, code and item code (the use case passes the window widened by the buffer); cancelled rows and other item codes are not returned

#### Scenario: Untrusted stored rows
- Given a stored row whose booking code, item code, quantity, instants or status violate the domain contract (or a catalog row with an unknown category, a malformed code or an absurd price)
- When an adapter maps it
- Then `InvalidStoredData` is raised (never `TypeError`, `KeyError` or a bare `ValueError`) and the row is not skipped silently; values the driver cannot decode (for example an `infinity` timestamp, a SQLAlchemy `DataError`) are `InvalidStoredData` too, not an outage

#### Scenario: Storage failure
- Given an unreachable database whose URL contains a user, password, host and database name
- When an adapter is used
- Then `RepositoryUnavailable` is raised with a generic message, and neither the message nor the formatted traceback contains any of those values

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
