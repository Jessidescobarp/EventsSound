# Delta Spec: synthetic-seed

Change: quote-domain-core. A manual script (not a migration) that loads synthetic catalog data. All data is synthetic; no real customer data.

## ADDED Requirements

### Requirement: Seed content
The seed MUST define exactly 30 equipment items and 5 service packages. Item and package `code` values and category names MUST be English slugs (`^[a-z][a-z0-9_]*$`); `name` MUST be Spanish. Items MUST cover all categories (sound, lighting, dj, stage, effects, video), with positive integer `unit_price_cop`, stock >= 1 (at least one item with stock > 1), and prices that are multiples of 1000. Every package MUST reference only seeded items with positive quantities and have `discount_bps` in 0..10000. Seed definitions MUST be plain data, validated by unit tests without a database.

#### Scenario: Counts and shape
- Given the seed definitions
- When they are loaded in a unit test
- Then there are 30 items and 5 packages, codes are unique English slugs, and every package member exists

#### Scenario: Pricing works on the seed
- Given the seed catalog and default rules
- When `calculate_price` is called for each package
- Then each returns a valid positive `Quote`

### Requirement: Idempotency
Running the seed repeatedly MUST NOT create duplicates. Rows MUST be matched by `code`; existing rows MUST be updated to the seed values and package membership MUST be reconciled to the seed definition. The seed MUST NOT delete or modify bookings.

#### Scenario: Run twice
- Given an empty migrated database
- When the seed runs twice with `--confirm`
- Then the database holds 30 items and 5 packages and the second run changes no counts

#### Scenario: Drifted row restored
- Given a seeded item whose price was edited
- When the seed runs again
- Then the price returns to the seed value

### Requirement: Explicit confirmation
The seed MUST do nothing and exit non-zero unless `--confirm` is passed, printing a usage message that does not include the database URL.

#### Scenario: Missing flag
- Given the script is invoked without `--confirm`
- When it starts
- Then no connection is opened and the exit code is non-zero

### Requirement: Remote host guard
The seed MUST parse the target database host. If the host is not local (`localhost`, `127.0.0.1`, `::1`, `db`, or no host), or `APP_ENV` is `production`, it MUST refuse to run and exit non-zero unless the environment variable `ALLOW_REMOTE_SEED` equals exactly `1`. `ALLOW_REMOTE_SEED` is read only by the seed CLI via `os.environ` (injectable); it is NOT a `Settings` field and `.env.example` does not change (developer rule, supersedes design D14). The check MUST happen before any connection. The seed MUST NOT read `.env*` files directly; it uses `Settings` for `DATABASE_URL` like the rest of the app.

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
