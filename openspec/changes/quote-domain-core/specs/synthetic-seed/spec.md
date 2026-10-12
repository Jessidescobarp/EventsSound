# Delta Spec: synthetic-seed

Change: quote-domain-core. A manual script (not a migration) that loads synthetic catalog data. All data is synthetic; no real customer data.

## ADDED Requirements

### Requirement: Seed content
The seed MUST define exactly 20 equipment items and 4 service packages (scope cut 4), plus a handful of demo bookings. Item and package `code` values and category names MUST be English slugs (`[a-z][a-z0-9_]*`, matched with `fullmatch`); `name` MUST be Spanish. Items MUST cover all categories (sound, lighting, dj, stage, effects, video), with positive integer `unit_price_cop`, stock 1..24 (at least one item with stock > 1), and prices that are multiples of 1000. Every package MUST have 4 to 6 lines of seeded items with positive quantities and `discount_bps` in 500..1500. The demo bookings (`DEMO-nnn` codes) MUST reference seeded items, be unique per (`code`, `item_code`), include pending, confirmed and cancelled statuses, and reduce the availability of at least one item (the cancelled one must not). Seed definitions MUST be plain domain values in `adapters/db/seed_data.py`, validated by unit tests without a database; growing the demo catalog means editing that module only.

#### Scenario: Counts and shape
- Given the seed definitions
- When they are loaded in a unit test
- Then there are 20 items and 4 packages, codes are unique English slugs, and every package member exists

#### Scenario: Pricing works on the seed
- Given the seed catalog and default rules
- When `calculate_price` is called for each package
- Then each returns a valid positive `Quote`

### Requirement: Idempotency
Running the seed repeatedly MUST NOT create duplicates. Rows MUST be matched by `code` (items, packages) or by (`booking_code`, `item_code`) (demo bookings); existing rows MUST be updated to the seed values and package membership MUST be reconciled to the seed definition (stale lines of a seeded package are deleted). The seed MUST NOT delete any other row and MUST NOT modify bookings that are not in its definition. The whole run is one transaction: a failure part way leaves nothing behind. Invalid definitions (duplicate or dangling codes, a booking of an unseeded item, wrong types) raise a domain error and write nothing.

#### Scenario: Run twice
- Given an empty migrated database
- When the seed runs twice with `--confirm`
- Then the database holds 20 items, 4 packages and the demo bookings, the second run changes no counts or values, and `created_at` is unchanged

#### Scenario: Drifted row restored
- Given a seeded item whose price was edited, a package line whose quantity was edited, or a demo booking that was cancelled
- When the seed runs again
- Then the values return to the seed values

#### Scenario: Foreign rows survive
- Given a hand-made item, a hand-made package and a real booking added after seeding
- When the seed runs again
- Then they are all untouched

### Requirement: Explicit confirmation
The seed MUST do nothing and exit with code 2 unless `--confirm` is passed, printing a dry-run line (`dry run: would upsert 20 items, 4 packages and 5 demo bookings. Pass --confirm to write.`) that does not include the database URL. `--confirm` is the only option; unknown arguments are rejected by the argument parser (exit 2). The dry run does not even load `Settings`.

#### Scenario: Missing flag
- Given the script is invoked without `--confirm`
- When it starts
- Then no connection is opened and the exit code is non-zero

### Requirement: Remote host guard
The seed MUST parse the target database host. If the host is not local (`localhost`, `127.0.0.1`, `::1`, `db`, a unix-socket directory, or no host), or `APP_ENV` is `production` (compared case-insensitively after trimming), it MUST refuse to run and exit with code 3 unless the environment variable `ALLOW_REMOTE_SEED` equals exactly `1`. The libpq URL overrides count as hosts: a `?host=` value (comma-separated lists included) must be local too, and `?hostaddr=` or `?service=` are always treated as non-local. A URL that is not a usable PostgreSQL URL exits 1 without echoing it. `ALLOW_REMOTE_SEED` is read only by the seed CLI via `os.environ` (injectable); it is NOT a `Settings` field and `.env.example` does not change (developer rule, supersedes design D14). The check MUST happen before any connection. The seed MUST NOT read `.env*` files directly; it uses `Settings` for `DATABASE_URL` like the rest of the app.

#### Scenario: Local host
- Given `DATABASE_URL` host is `127.0.0.1` and `--confirm` is passed
- When the seed runs
- Then it proceeds

#### Scenario: Remote host refused
- Given a non-local host and `--confirm` but no `ALLOW_REMOTE_SEED`
- When the seed runs
- Then it exits non-zero before connecting

#### Scenario: Remote host allowed explicitly
- Given a non-local host, `--confirm` and `ALLOW_REMOTE_SEED=1`
- When the seed runs
- Then it proceeds

#### Scenario: Value other than 1
- Given `ALLOW_REMOTE_SEED=true`
- When the seed targets a remote host
- Then it is still refused

### Requirement: No secret leakage
The seed MUST NOT print, log, or include in exception text the connection string, host, user or password. It MAY print counts and the word `local` or `remote`.

#### Scenario: Output inspection
- Given any run (success, refusal or failure)
- When stdout, stderr and exception messages are inspected
- Then none contains the database URL, its credentials, or its host
