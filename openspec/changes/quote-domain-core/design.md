# Design: quote-domain-core (P1 Domain core)

> **Scope cuts (2026-10-12):** this design was written for the full 11-PR plan. Where it conflicts with `tasks.md` section "Scope cuts and decisions (2026-10-12)", `tasks.md` wins. Affected: Hypothesis/property tests (D19, D20) replaced by table-driven tests; `booking_items` table (D10) dropped for a flat `bookings` table; seed 20 items / 4 packages (D13); seed CLI keeps only `--confirm` and the remote guard (D14); `Quote` versioning is a single `version` field (D7); OpenAPI/Swagger is public in production (D15/D17); use cases ship inside the API PR. The design body below is intentionally not rewritten.

Inputs: `proposal.md` (same folder, including its Decisions section), `openspec/config.yaml`, `AGENTS.md`, `documentacion/{architecture,decisions}.md`, the P0 backend and the five project skills.
Scope: architecture only. No application code is written in this phase of SDD.

## 1. Technical Approach

Hexagonal, inside-out, strict TDD. A stdlib-only domain owns Money, the catalog, the request, the rule data, `calculate_price` (the eval oracle) and the availability algorithm. `application/` adds two small ports and three use-case functions. `adapters/db/` adds SQLAlchemy models, repositories and an idempotent seed. `entrypoints/api/` adds two read-only routes. Nothing in P0 is rewritten; every change is additive except two test-infrastructure edits (section 11).

```
 entrypoints/api  GET /catalog/items, /catalog/packages --> schemas.py (Pydantic)
        |                                                     |
        v                                                     v
 application      list_catalog | price_quote | check_event_availability     ports: CatalogRepository, BookingRepository
        |
        v
 domain           Money, Catalog, EventRequest, PricingRules, calculate_price -> Quote, check_availability
        ^
 adapters/db      models.py, catalog_repository.py, booking_repository.py, seed_data.py, seed.py
```

Guiding rules (from the skills): no base repository, no speculative abstraction, use cases are plain functions taking ports (same shape as `check_database`), fakes over mocks, ORM models never cross into domain.

## 2. Module and file layout

Flat modules inside each layer (no bounded-context sub-packages: 7 domain modules do not justify them; P0 design said to introduce them only if the code demands it).

```
backend/src/eventssound/
  domain/
    errors.py          DomainError, InvalidMoney, CurrencyMismatch, InvalidRules, InvalidEventRequest, UnknownCatalogEntry
    money.py           Money
    catalog.py         EquipmentCategory, EquipmentItem, PackageLine, ServicePackage, Catalog
    event_request.py   EventType, VenueType, RequestedLine, EventRequest (+ input bounds)
    pricing_rules.py   GuestTier, DistanceBand, NightWindow, PricingRules, default_pricing_rules()
    pricing.py         LineKind, QuoteLine, Quote, calculate_price
    availability.py    BookingStatus, Reservation, AvailabilityRules, default_availability_rules(),
                       available_units, check_availability, check_request_availability, required_units
  application/
    ports.py           (existing) + CatalogRepository, BookingRepository
    errors.py          RepositoryUnavailable
    catalog.py         list_catalog(catalog_repo) -> Catalog
    pricing.py         price_quote(request, catalog_repo, rules) -> Quote
    availability.py    check_event_availability(request, catalog_repo, booking_repo, rules) -> AvailabilityReport
  adapters/db/
    models.py          5 SQLAlchemy models on Base
    catalog_repository.py   SqlAlchemyCatalogRepository
    booking_repository.py   SqlAlchemyBookingRepository
    seed_data.py       SEED_ITEMS, SEED_PACKAGES (domain entities, pure data)
    seed.py            seed_catalog(session_factory, items, packages) -> SeedResult
  entrypoints/
    cli/__init__.py, cli/seed_catalog.py   python -m eventssound.entrypoints.cli.seed_catalog
    api/schemas.py, api/routes/catalog.py, api/container.py (extended), api/app.py (extended)
backend/migrations/versions/0002_catalog_tables.py, 0003_booking_tables.py
```

### D1. Seed is a `python -m` module inside the package, not `backend/scripts/`
The Docker image copies only `src/`, `migrations/`, `alembic.ini`, `start.sh`. A `scripts/` file would not exist in the container, and tests cannot import it without path hacks. A module under `entrypoints/cli/` is importable by tests, runs inside the container (`python -m eventssound.entrypoints.cli.seed_catalog --confirm`), and lives in the driving layer where it belongs. Rejected: `backend/scripts/seed_catalog.py` (proposal's first suggestion; the proposal allowed the `python -m` variant). The seed data lives in `adapters/db/seed_data.py` as domain entities so a plain unit test can validate it with no database.

### D2. Use cases are functions, not classes
`price_quote`, `list_catalog`, `check_event_availability` follow `check_database(database)`: ports are parameters, no state. Rejected: `PriceQuote` classes with `execute()` (state-free, adds an object per call site and a constructor to wire in `container.py`). Revisit in P2 only if the agent needs one object holding all ports.

## 3. Money (`domain/money.py`)

```python
@dataclass(frozen=True, slots=True)
class Money:
    amount: int            # whole pesos (any sign: discount lines are negative)
    currency: str = "COP"  # ^[A-Z]{3}$
```
- Validation in `__post_init__`: `type(amount) is int` (rejects `bool` and `float`), currency regex; raises `InvalidMoney`.
- Operations: `__add__`, `__sub__`, `__neg__` (same currency, else `CurrencyMismatch`), `__mul__`/`__rmul__` by `int` only (a float returns `NotImplemented` and therefore `TypeError`), ordering via `functools.total_ordering` raising on currency mismatch (a tuple `order=True` would silently compare currencies), `Money.zero()`, `Money.sum(iterable, currency)`.
- `percent(bps: int) -> Money`: `bps` basis points (1500 = 15%), integer half-up: `(2 * amount * bps + 10_000) // 20_000`.
- `round_to(step: int) -> Money`: half-up to the nearest multiple of `step`: `(2 * amount + step) // (2 * step) * step`. Python floor division makes this correct for negatives too (half rounds toward +infinity). `step >= 1`.
- No `Decimal`, no `float`, no `Fraction` in the domain. The minor-unit exponent is deliberately absent (COP has none); if a second currency arrives it becomes a field of a currency registry, not of `Money.amount`.
- Serialisation: `Money` is not serialised on its own; `Quote.to_dict()` emits plain ints plus one `currency` (section 6).

### D3. Rounding: percentages to the peso, total to 1000 once, shown as an explicit line
The proposal says "round half-up to nearest 1000 once at the end". The 1000 rounding happens exactly once, on the grand total. But every line must be an integer number of pesos, so a percentage line (`basis * rate_bps / 10_000`) has to be reduced to a whole peso somewhere. We do that with `Money.percent` (integer half-up to the peso) per line. With the synthetic defaults (unit prices multiples of 1000, whole-percent rates) the basis is a multiple of 1000 and every percentage line is already an exact integer, so this sub-peso rounding never fires; it exists only so owner-supplied data cannot produce a non-integer.
The final step adds a `ROUNDING` line equal to `total - raw_total` (omitted when zero). Consequence: `sum(line.amount) == total` always holds, which makes the invariant testable and the quote explainable. Rejected: carrying `Fraction` through the pipeline (lines would not be integer pesos and could not be shown or serialised); rounding each line to 1000 (accumulates error, breaks monotonicity).

## 4. Catalog, request, rules

### Catalog (`domain/catalog.py`)
- `EquipmentCategory(StrEnum)`: `SOUND, LIGHTING, DJ, STAGE, EFFECTS, VIDEO` (values lowercase: `"sound"`, ...).
- `EquipmentItem(code: str, name: str, category, stock_quantity: int, unit_price: Money)`. `unit_price` is per rental day. Validation: `code` matches `^[a-z0-9_]{3,64}$`, `stock_quantity >= 0`, `0 <= unit_price.amount <= 1_000_000_000`, name non-empty. `name` holds the Spanish display name (data, not UI copy).
- `PackageLine(item_code, quantity >= 1)`; `ServicePackage(code, name, lines: tuple[PackageLine, ...], discount_bps: int = 0)`; at least one line, unique `item_code`s, `0 <= discount_bps <= 10_000`.
- `Catalog(items: tuple[EquipmentItem, ...], packages: tuple[ServicePackage, ...])`: frozen; builds `code -> entity` maps in `__post_init__`; rejects duplicate codes and packages that reference unknown items. `item(code)` / `package(code)` raise `UnknownCatalogEntry(code)`. `ServicePackage.base_unit_price(catalog) -> Money` sums `quantity * unit_price` of its lines (a package has no price of its own; it is derived, so catalog edits cannot drift).
- Identity is `code` (stable, human readable, used by seed, API and agent). Database `id` never leaves `adapters/db`.

### D4. Package discount lives on the package, rules only cap it
The proposal lists "package discount" under `PricingRules` and also "optional discount" on `ServicePackage`. Those are two homes for one number. Decision: `ServicePackage.discount_bps` (catalog data, `0` = none, varies per package in the seed) is the discount; `PricingRules.max_package_discount_bps` (default 2000) is the owner's policy ceiling, applied as `min(package, cap)`. Rejected: a single global discount in the rules (cannot express "wedding package 15%, basic 5%"); a nullable per-package override falling back to a rules default (needs the rules to render the catalog API honestly). Flagged in Risks for confirmation.

### EventRequest (`domain/event_request.py`)
```python
class EventType(StrEnum): WEDDING, CORPORATE, BIRTHDAY, QUINCEANERA, GRADUATION, CONCERT, OTHER
class VenueType(StrEnum): INDOOR, OUTDOOR
@dataclass(frozen=True, slots=True)
class RequestedLine: code: str; quantity: int          # >= 1
@dataclass(frozen=True, slots=True)
class EventRequest:
    event_type: EventType; start: datetime; end: datetime      # tz-aware, half-open [start, end)
    guest_count: int; distance_km: int; venue: VenueType
    items: tuple[RequestedLine, ...] = (); packages: tuple[RequestedLine, ...] = ()
```
- Validation (`InvalidEventRequest`): both datetimes tz-aware (`utcoffset() is not None`), `end > start`, duration `<= 31 days`, `1 <= guest_count <= 100_000`, `0 <= distance_km <= 5_000`, at least one line, quantities in `1..10_000`, at most 100 lines. The bounds exist because the agent (P2) will build requests from untrusted text; they also cap the day-iteration loops (OWASP GenAI: unbounded consumption). They are module constants, not rule data.
- Duplicate codes are merged (quantities summed) by a `normalized()` helper used by pricing and availability, so results are independent of input order and duplicates.
- `event_type` and `venue` are carried and validated but do not change the price in P1 (no rule in scope uses them). They are present so P2 tools and RAG need no contract change.

### PricingRules (`domain/pricing_rules.py`), all frozen dataclasses
```python
GuestTier(min_guests: int, surcharge_bps: int)
DistanceBand(up_to_km: int | None, rate_per_km: Money)      # marginal rate, None = open-ended last band
NightWindow(start: time, end: time, surcharge_bps: int)     # wraps midnight when start > end
PricingRules(
    version: str,                         # reported in every Quote
    currency: str,                        # "COP"
    timezone: tzinfo,                     # interpretation zone for weekend/holiday/night
    guest_tiers: tuple[GuestTier, ...],
    weekend_days: frozenset[int],         # date.weekday() values, default {5, 6}
    holidays: frozenset[date],            # default empty: weekends only (decision 4)
    weekend_holiday_surcharge_bps: int,
    night: NightWindow,
    distance_bands: tuple[DistanceBand, ...],
    max_package_discount_bps: int,
    rounding_step: int,                   # pesos
)
```
Validation in `__post_init__`, raising `InvalidRules`: tiers non-empty, first `min_guests == 1`, strictly increasing `min_guests`, `surcharge_bps` non-decreasing and `0 <= bps <= 100_000` (a decreasing tier would break the monotonicity property and is a likely data-entry error); bands non-empty, `up_to_km` strictly increasing, only the last may (and must) be `None`, rates `>= 0` and same currency; `night.start != night.end`; `rounding_step >= 1`; `timezone` not `None`; `max_package_discount_bps` in `0..10_000`.

### D5. Synthetic default rule set (`default_pricing_rules()`), version `"synthetic-v1"`
| Rule | Default |
| ---- | ------- |
| Timezone | `ZoneInfo("America/Bogota")` |
| Guest tiers (min guests: surcharge) | 1: 0%, 101: 10%, 301: 25%, 601: 40% |
| Weekend/holiday | Saturday and Sunday, +15%, holidays empty |
| Night window | 22:00-06:00 local, +20% |
| Distance bands (marginal) | up to 20 km: 0 COP/km; up to 60 km: 3,000 COP/km; beyond: 4,500 COP/km |
| Package discount cap | 20% |
| Rounding step | 1,000 COP |

Owner-supplied rules replace these values via a loader that constructs `PricingRules` (JSON or DB); `calculate_price` never changes. Rejected: `Decimal`/float multipliers (basis points are exact and hashable); a `HolidayCalendar` class (a `frozenset[date]` is the whole contract today).

### D6. Time zones: `zoneinfo` + the `tzdata` package
`ZoneInfo("America/Bogota")` needs the IANA database. Windows has none and `python:3.12-slim` is not guaranteed to ship `/usr/share/zoneinfo`; `ZoneInfo` would raise `ZoneInfoNotFoundError` locally and in the container. Decision: add `tzdata>=2024.1` as a runtime dependency in `pyproject.toml` (lockfile change in PR A2). Rejected: a hand-rolled `timezone(timedelta(hours=-5))` (works today because Colombia has no DST, but encodes an accident and diverges from the "rules interpreted in America/Bogota" decision); `pytz` (legacy API). Storage is always tz-aware (UTC in the database); the domain converts with `dt.astimezone(rules.timezone)` only inside the weekend and night checks. The domain takes a `tzinfo` object, never a name string, so it never touches the tz database itself (the default factory is the only place that builds `ZoneInfo`, and it is stdlib).

## 5. `calculate_price`: exact order of application

Signature (the oracle contract, frozen for P2/P3): `calculate_price(request: EventRequest, catalog: Catalog, rules: PricingRules) -> Quote`. Pure, no I/O, no clock.

1. **Normalize and resolve.** Merge duplicate codes, sort by code, resolve every code against `catalog` (`UnknownCatalogEntry` on the first miss, naming the code). Reject a currency mismatch between catalog and rules.
2. **Rental days.** `rental_days = max(1, ceil((end - start) / 24h))` using integer arithmetic on `timedelta`. Equipment is priced per rental day. A 22:00-03:00 event is one day (the proposal's "multi-day" coverage without per-calendar-day double counting).
3. **Item lines.** For each requested item (sorted by code): `ITEM` line, `amount = quantity * rental_days * unit_price`.
4. **Package lines.** For each requested package (sorted by code): `PACKAGE` line, `unit_amount = base_unit_price(catalog)`, `amount = quantity * rental_days * unit_amount`. Then, if `min(discount_bps, rules.max_package_discount_bps) > 0`, a `PACKAGE_DISCOUNT` line with `basis = package amount`, `rate_bps`, `amount = -basis.percent(rate)`.
5. **Equipment subtotal `E`** = sum of steps 3-4 (net of package discounts). Every percentage below is computed on `E` and they are additive, not compounded. Rationale: each line then reads "x% of E", a human can verify it, results do not depend on rule order, and monotonicity is trivial. Rejected: compounding multipliers (order-sensitive, harder to explain to the client, invites rounding drift).
6. **Guest-size line.** Tier = the last tier with `min_guests <= guest_count`. If `surcharge_bps > 0`: `GUEST_SIZE` line, `amount = E.percent(bps)`.
7. **Weekend/holiday line.** Local dates touched by `[start, end)`: from `start_local.date()` to `(end_local - 1 microsecond).date()` inclusive (end exclusive, so an event ending exactly at 00:00 Saturday does not touch Saturday). If any date has `weekday() in weekend_days` or is in `holidays`, add `WEEKEND_HOLIDAY` (`E.percent(bps)`). One flat surcharge, not per day (a Friday-to-Monday event is charged once; simple, conservative, monotone in `end`).
8. **Night line.** For each touched local date `d`, the window instance is `[d @ night.start, d+1 @ night.end)` if it wraps midnight, else `[d @ start, d @ end)`, built with `datetime.combine(..., tzinfo=rules.timezone)`. If any instance overlaps `[start, end)` (half-open overlap), add `NIGHT` (`E.percent(bps)`). Flat, not pro-rated by hours. Also check the instance starting the day before the first touched date (a 01:00 event overlaps the previous evening's window).
9. **Distance lines.** Progressive marginal bands over `distance_km`: for each band, `km_in_band = min(distance_km, up_to) - previous_up_to` (clamped at 0); one `DISTANCE` line per band with `km_in_band > 0` and a non-zero rate: `quantity = km_in_band`, `unit_amount = rate_per_km`, `code = "distance_band_<n>"`. Per event, not per day (one delivery). Marginal bands avoid cliffs where 61 km costs less than 60.
10. **Raw total** = sum of all lines so far. It is `>= 0` by construction (discount `<= package amount`).
11. **Rounding (once).** `total = raw.round_to(rules.rounding_step)`; if `total != raw`, append a `ROUNDING` line (`amount = total - raw`).
12. Build `Quote`.

Complexity: `O(L log L + D + B)` for `L` lines, `D <= 32` touched dates, `B` bands.

Worked example (default rules, drives the golden test): 2 x speaker at 120,000 + 1 x mixer at 79,900, 150 guests, Saturday 20:00-23:30 Bogota, 45 km. `E = 319,900`; guest 10% = 31,990; weekend 15% = 47,985; night 20% = 63,980; distance 25 km x 3,000 = 75,000; raw 538,855; total 539,000 with a `ROUNDING` line of +145.

### D7. `Quote` / `QuoteLine` shape (the contract P2 and P3 consume)
```python
class LineKind(StrEnum):
    ITEM = "item"; PACKAGE = "package"; PACKAGE_DISCOUNT = "package_discount"
    GUEST_SIZE = "guest_size"; WEEKEND_HOLIDAY = "weekend_holiday"; NIGHT = "night"
    DISTANCE = "distance"; ROUNDING = "rounding"

@dataclass(frozen=True, slots=True)
class QuoteLine:
    kind: LineKind
    code: str                 # catalog code, package code, or rule code ("guest_size", "distance_band_2", "rounding")
    label: str | None         # catalog display name for item/package lines, else None (no prose from rules)
    quantity: int             # units, km, or 1
    periods: int              # rental days for item/package lines, else 1
    unit_amount: Money | None # item/package/distance lines
    rate_bps: int | None      # percentage lines (guest, weekend, night, discount)
    basis: Money | None       # percentage lines: the amount the rate applies to
    amount: Money             # signed; unit lines: quantity * periods * unit_amount; percentage lines: basis.percent(rate_bps)

@dataclass(frozen=True, slots=True)
class Quote:
    schema_version: int       # QUOTE_SCHEMA_VERSION = 1
    rules_version: str
    currency: str
    rental_days: int
    lines: tuple[QuoteLine, ...]
    subtotal: Money           # raw total before the rounding line
    total: Money
    def to_dict(self) -> dict[str, object]: ...
```
Invariants (all property-tested): `sum(l.amount for l in lines) == total`; `total == subtotal` or differs by exactly the `ROUNDING` line; `total.amount % rounding_step == 0`; every non-rounding line is reproducible from its own fields (`unit` lines: `quantity*periods*unit_amount`; percentage lines: `basis.percent(rate_bps)`), so the agent can explain any number without calling the LLM; line order is deterministic (items, packages with their discount, guest, weekend, night, distance, rounding).
`to_dict()` returns only JSON primitives: ints for amounts, one top-level `currency`, `null` for absent fields. `schema_version` is bumped on any shape change; a golden-snapshot test (`test_quote_contract.py`) pins the dict for the worked example so a contract change is a deliberate test edit ("versioned by tests"). Rejected: free-text `description` on lines (the agent composes wording; evals assert numbers and structure); free-form `detail` dicts (untyped, drift-prone); a separate `breakdown` object duplicating `lines`.

## 6. Availability (`domain/availability.py`)

Types: `BookingStatus(StrEnum)`: `PENDING, CONFIRMED, CANCELLED`, with `BookingStatus.blocking() -> {PENDING, CONFIRMED}`. `Reservation(item_code, quantity >= 1, start, end)`: one reserved item of one booking, tz-aware, `end > start`. `AvailabilityRules(buffer: timedelta)` with `default_availability_rules()` = 2 hours (decision 2); validated `>= 0` and a whole number of minutes. Kept apart from `PricingRules`: the buffer is not a pricing datum, and `calculate_price` should not receive fields it never reads.

Naming vs the proposal: the proposal's `bookings` argument becomes `reservations` (the repository returns item-level reservations of blocking bookings only; a `Booking` header exists only in the database for now).

### D8. Algorithm: interval-graph peak concurrency with buffers split in half
Two uses of one unit are compatible iff the gap between them is `>= buffer` (half-open intervals, so a gap of exactly `buffer` is allowed). Expanding every interval by `buffer/2` on each side turns that into plain half-open overlap, and units are interchangeable, so the minimum units needed is the maximum clique of an interval graph = peak concurrency (exact, no heuristics).

`available_units(stock, start, end, reservations, buffer)`:
1. `lo = start - buffer/2`, `hi = end + buffer/2`.
2. Keep reservations whose expanded interval `[r.start - buffer/2, r.end + buffer/2)` overlaps `[lo, hi)` (equivalently `r.start < end + buffer and r.end > start - buffer`).
3. Sweep line: events `(time, +quantity)` at `max(r.start - buffer/2, lo)` and `(time, -quantity)` at `min(r.end + buffer/2, hi)`; sort by `(time, delta)` so releases (negative) precede acquisitions at equal timestamps (half-open: touching intervals do not overlap); track the running sum, `peak = max`.
4. Return `max(0, stock - peak)`.

`check_availability(item, start, end, reservations, buffer, quantity=1)` returns `Availability(item_code, requested, available, is_available = available >= requested)` using `item.stock_quantity` (reservations for other item codes are ignored). `check_request_availability(request, catalog, reservations, buffer)` first computes `required_units`: the sum over loose items plus `package.quantity * line.quantity` for package components, per item code (a package consumes stock like its parts), then checks each item and returns `AvailabilityReport(is_available, shortages: tuple[Shortage(item_code, requested, available), ...])`, sorted by code.

Complexity: `O(n log n)` for `n` reservations overlapping the window (sort dominates); `O(I * n log n)` for `I` distinct items in the request (`I <= 100`).

Semantics worth stating: back-to-back events are allowed only if the gap is `>= buffer`, so with the 2-hour default "back-to-back" means a 2-hour gap; with `buffer = 0` they may touch exactly. Multi-day events are plain long intervals. Existing data that already violates the buffer is counted conservatively (peak may overcount; never undercounts). Pending bookings block stock (conservative); cancelled ones do not.

### D9. SQL strategy: coarse overlap filter in SQL, exact computation in the domain
The adapter returns candidates with an indexed range predicate; the sweep runs in Python.
```sql
SELECT i.code, bi.quantity, b.starts_at, b.ends_at
FROM booking_items bi
JOIN bookings b        ON b.id = bi.booking_id
JOIN equipment_items i ON i.id = bi.equipment_item_id
WHERE i.code = ANY(:codes)
  AND b.status IN ('pending', 'confirmed')
  AND b.starts_at < :window_end AND b.ends_at > :window_start
```
The use case passes `window = [start - buffer, end + buffer)`. Why not SQL-only:
- `SUM(quantity)` over overlapping rows counts reservations that overlap the window but not each other, so it overstates demand (two sequential 1-unit bookings inside a long request would look like 2 concurrent). Computing true peak concurrency in SQL needs a window-function sweep over event rows, which is harder to read and to test.
- A Postgres `tstzrange` + GiST `EXCLUDE` constraint is perfect for "one resource, no overlap" but cannot express stock `> 1`.
- Keeping the algorithm in the domain gives one implementation shared by the API, the P2 agent tool and the Hypothesis oracle test, with zero database in the property tests.
Cost: the number of rows fetched equals the bookings near the window (tens at MVP volume). Index: `ix_bookings_starts_at` on `(starts_at, ends_at)` plus `ix_booking_items_equipment_item_id` (section 7). A GiST range index is premature.

## 7. Database schema

Conventions applied: plural snake_case tables, singular columns, `id` PK, `<entity>_id` FKs, `*_at` timezone-aware, constraint and index names generated by `NAMING_CONVENTION` (check constraints carry a short `name=`), models subclass `Base` and live only in `adapters/db/`.

### D10. Five tables, not four
The proposal names `equipment_items, service_packages, package_items, bookings`. With only a `bookings` table each row would have to carry one `equipment_item_id` and `quantity`, so one real-world booking becomes N unrelated rows, and the P2+ "pending booking from a quote" change would need an expand/contract migration to introduce the header. Decision: add `booking_items` now (booking header + lines, mirroring `service_packages` + `package_items`). Cost: one small table and ~30 lines in PR B1. Flagged in Risks. If the developer rejects it, the fallback is a single flat `bookings` table with `(equipment_item_id, quantity, starts_at, ends_at, status)`; the repository port and the domain are unaffected.

| Table | Columns | Constraints and indexes |
| ----- | ------- | ----------------------- |
| `equipment_items` | `id` BIGINT identity PK; `code` VARCHAR(64) NOT NULL; `name` VARCHAR(120) NOT NULL; `category` VARCHAR(16) NOT NULL; `stock_quantity` INTEGER NOT NULL; `unit_price_cop` BIGINT NOT NULL; `created_at`, `updated_at` TIMESTAMPTZ NOT NULL DEFAULT now() | UNIQUE `code`; CHECK `category_valid` (`category IN (...)`); CHECK `stock_nonnegative`; CHECK `unit_price_nonnegative` |
| `service_packages` | `id` PK; `code` VARCHAR(64) NOT NULL; `name` VARCHAR(120) NOT NULL; `discount_bps` INTEGER NOT NULL DEFAULT 0; `created_at`, `updated_at` | UNIQUE `code`; CHECK `discount_range` (`0..10000`) |
| `package_items` | `id` PK; `package_id` BIGINT NOT NULL; `equipment_item_id` BIGINT NOT NULL; `quantity` INTEGER NOT NULL | UNIQUE (`package_id`, `equipment_item_id`); FK `package_id` -> `service_packages.id` ON DELETE CASCADE; FK `equipment_item_id` -> `equipment_items.id` ON DELETE RESTRICT; CHECK `quantity_positive`; index on `equipment_item_id` (reverse lookup; `package_id` is covered by the unique constraint) |
| `bookings` | `id` PK; `starts_at`, `ends_at` TIMESTAMPTZ NOT NULL; `status` VARCHAR(16) NOT NULL DEFAULT `'pending'`; `created_at`, `updated_at` | CHECK `ends_after_starts` (`ends_at > starts_at`); CHECK `status_valid`; index on (`starts_at`, `ends_at`) |
| `booking_items` | `id` PK; `booking_id` BIGINT NOT NULL; `equipment_item_id` BIGINT NOT NULL; `quantity` INTEGER NOT NULL | UNIQUE (`booking_id`, `equipment_item_id`); FK `booking_id` -> `bookings.id` ON DELETE CASCADE; FK `equipment_item_id` -> `equipment_items.id` ON DELETE RESTRICT; CHECK `quantity_positive`; index on `equipment_item_id` |

Money columns are `*_cop` BIGINT (decision 1); `_bps` is basis points. `category` and `status` are `VARCHAR + CHECK`, not native PG ENUM types: adding a value to an ENUM and dropping the type on downgrade are the painful parts of migrations; the CHECK is dropped and recreated in a normal revision. ON DELETE policy: children owned by a parent (`package_items`, `booking_items`) cascade; references to catalog items are `RESTRICT` so an item with history cannot be deleted by accident (catalog rows are retired by a later `is_active` column, not deleted; not needed in P1, so not added). `updated_at` is set by `onupdate=func.now()` in the model and explicitly in the seed upsert.

### D11. Migrations: two reversible, hand-written revisions, schema only
- `0002_catalog_tables`: `equipment_items`, `service_packages`, `package_items` (+ their indexes). `down_revision = "0001"`. `downgrade()` drops `package_items`, `service_packages`, `equipment_items` in FK order.
- `0003_booking_tables`: `bookings`, `booking_items`. `downgrade()` drops `booking_items` then `bookings`.
One concern per revision (catalog vs reservations), one head. Written by hand after `alembic revision --autogenerate` for a draft (skill: review autogenerate by hand), with explicit `sa.CheckConstraint(..., name="...")`. Alembic builds `op.create_table` constraint names from `target_metadata.naming_convention`, which `migrations/env.py` already passes, so the names in the database equal the model names. The migrations hardcode literal category/status strings (revisions are frozen history and must not import from application code).
`migrations/env.py` gets `import eventssound.adapters.db.models  # noqa: F401`. Without it `Base.metadata` is empty in the Alembic process and autogenerate would propose dropping the tables.
Tests (all under `DATABASE_URL_TEST`): upgrade to head creates exactly the five tables; downgrade to `0002`, to `0001` and to base each leave the expected set; upgrade/downgrade/upgrade round trip; named constraints exist (`uq_equipment_items_code`, `ck_equipment_items_stock_nonnegative`, `fk_package_items_equipment_item_id_equipment_items`); and a drift test using `alembic.autogenerate.compare_metadata` that asserts an empty diff between the migrated database and `Base.metadata` (guards model/migration divergence).
`start.sh` runs `alembic upgrade head` on every deploy, so merging B1 creates empty tables in Neon automatically; harmless (schema only). The seed never runs automatically (D14).

## 8. Application layer

```python
# application/ports.py (additions; small, role-specific ports)
class CatalogRepository(Protocol):
    def get_catalog(self) -> Catalog:
        """Return the whole catalog. Raises RepositoryUnavailable on storage failure."""

class BookingRepository(Protocol):
    def find_reservations(
        self, item_codes: Collection[str], window_start: datetime, window_end: datetime
    ) -> Sequence[Reservation]:
        """Reservations of blocking bookings whose [start, end) intersects the window.
        Unknown codes yield no rows. Raises RepositoryUnavailable on storage failure."""
```
### D12. `get_catalog()` returns the whole `Catalog`; two ports, not one
Items and packages are always used together (a package must resolve its items), the catalog is tens of rows, and a single method gives pricing, listing and availability the same consistent snapshot. Rejected: `list_items()` / `list_packages()` / `get_item(code)` (three queries, possible inconsistency, a chatty 15-method port). `BookingRepository` is a separate port (ISP): the catalog read side and the reservation read side change for different reasons and P2 tools use them independently. No `EquipmentRepository` (the design-patterns skill mentions that name as "planned"; the skill reference should be updated in PR C2 docs).
`RepositoryUnavailable` (in `application/errors.py`) is raised by adapters wrapping `SQLAlchemyError`, with a generic message (no URL, host or SQL, per the coding skill). Routes map it to 503.

Use cases: `list_catalog(catalog_repo) -> Catalog`; `price_quote(request, catalog_repo, rules) -> Quote` (loads the catalog, calls `calculate_price`); `check_event_availability(request, catalog_repo, booking_repo, rules: AvailabilityRules) -> AvailabilityReport` (loads catalog, `required_units`, queries reservations for those codes in `[start - buffer, end + buffer)`, calls `check_request_availability`). Data flow for availability:

```
use case ──get_catalog()──────────────> CatalogRepository ──> Catalog
use case ──required_units(req, cat)──> {code: qty}
use case ──find_reservations(codes, start-buffer, end+buffer)──> BookingRepository ──> [Reservation]
use case ──check_request_availability(...)──> AvailabilityReport (domain, pure)
```
Neither `price_quote` nor `check_event_availability` is exposed over HTTP in P1 (decision 5); they are covered by unit tests with fakes and become the bodies of the P2 tools.

## 9. Adapters

- `models.py`: `EquipmentItemModel`, `ServicePackageModel`, `PackageItemModel`, `BookingModel`, `BookingItemModel` (SQLAlchemy 2.0 `Mapped[...]` / `mapped_column`, `DateTime(timezone=True)`, `BigInteger`, `relationship` only where the repository needs it: `ServicePackageModel.lines` with `selectinload`). Class names do not collide with domain names.
- `SqlAlchemyCatalogRepository(session_factory)`: `with factory() as session`, two `select` statements ordered by `code`, mapped to domain entities in private `_to_domain` functions (a bad row, for example an unknown category, raises the domain validation error and surfaces as a 500, never silently skipped).
- `SqlAlchemyBookingRepository(session_factory)`: the SQL in D9 via SQLAlchemy Core expressions, `status` filter from `BookingStatus.blocking()`, returns `Reservation`s. Read-only; no commit.
- Both wrap `SQLAlchemyError` into `RepositoryUnavailable` (`raise ... from None` to avoid leaking the driver message).

### D13. Seed: idempotent upsert keyed on `code`, guarded, never part of a migration
`seed_catalog(session_factory, items, packages) -> SeedResult(items, packages)` runs in one transaction (commit explicitly, roll back on error):
- Items: `INSERT ... ON CONFLICT (code) DO UPDATE SET name, category, stock_quantity, unit_price_cop, updated_at = now()` (`sqlalchemy.dialects.postgresql.insert`; the stack is Postgres-only, so a dialect-specific upsert is atomic and shorter than select-then-update).
- Packages: upsert on `code`; resolve item ids by code; upsert `package_items` on (`package_id`, `equipment_item_id`); delete `package_items` of that package whose item is not in the seed definition (so editing a package definition converges).
- Never deletes rows absent from the seed data (it cannot destroy data a developer added by hand).
- Running it twice yields identical row counts and identical content (tested).

Seed data (`seed_data.py`, compact helper `_item(code, name, category, stock, price)`; prices multiples of 1000, stock 1-24, Spanish `name`, English snake_case `code` with a category prefix):
| Category | Count | Outline |
| -------- | ----- | ------- |
| sound | 10 | active speakers 12"/15", subwoofer 18", line-array module, stage monitor, 16-ch mixer, wired mic, wireless mic, speaker stand, cable snake |
| lighting | 8 | LED par, moving head spot, moving head wash, beam, laser, strobe, DMX controller, light truss tower |
| dj | 4 | DJ controller, CDJ pair, DJ mixer, DJ booth/table |
| stage | 3 | 2x1 m stage module, skirting set, access stairs |
| effects | 3 | fog machine, haze machine, cold-spark fountain |
| video | 2 | LED screen module 3x2 m, projector with screen |
| **Total** | **30** | |

Five packages, each 4-8 lines (so each references real items), `discount_bps` between 500 and 1500: `pkg_basic_party` (Fiesta Basica), `pkg_wedding` (Boda), `pkg_corporate` (Evento corporativo), `pkg_dj_night` (Noche DJ), `pkg_concert` (Concierto). The module-level tuples are plain domain entities; a unit test builds `Catalog(SEED_ITEMS, SEED_PACKAGES)` (validates references and uniqueness), asserts 30 / 5 and prices multiple of 1000, and runs `calculate_price` on a sample request so the data and the oracle are tested together.

### D14. Seed guard (`entrypoints/cli/seed_catalog.py`)
`main(argv, settings=None, session_factory=None) -> int` (injectable, so tests never touch a real database or the environment):
1. No `--confirm`: print `dry run: would upsert 30 items and 5 packages`, exit 2, no connection opened.
2. Target classification uses `sqlalchemy.engine.make_url(url).host`: local = `{"localhost", "127.0.0.1", "::1", "db"}` or no host (unix socket). `"db"` mirrors `LOCAL_HOSTS` in `test_env_example.py` (compose service name).
3. Non-local host, or `APP_ENV == "production"`, requires `settings.allow_remote_seed` (env `ALLOW_REMOTE_SEED=1`); otherwise exit 3 with `refusing to seed a non-local target; set ALLOW_REMOTE_SEED=1 to override`.
4. Output never contains the URL, the host, the user or exception text from the driver; only counts and the local/remote classification.
5. Only `DATABASE_URL` from `Settings` is used; `.env*` files are never opened by this code (Settings' own optional root `.env` loading is unchanged and not read by tooling).
`ALLOW_REMOTE_SEED` is a `Settings` field (`allow_remote_seed: bool = False`, alias `ALLOW_REMOTE_SEED`) because the coding skill forbids `os.environ` outside `Settings`. Consequence: `test_every_setting_is_documented_in_env_example` requires a placeholder line `ALLOW_REMOTE_SEED=0` in `.env.example` in the same commit (apply agent must be allowed to edit that committed, placeholders-only file; it must never open `.env`, `.env.local` or `.neon`). Rejected: a `--allow-remote` CLI flag (the proposal fixed the env var, and a flag in shell history is easier to paste into the wrong terminal than an explicit env var).

## 10. Entrypoint: catalog API

### D15. Contract
No authentication, GET only, public synthetic data. `/catalog/availability` is NOT implemented (decision 5). Routes are sync `def` (sync SQLAlchemy runs in FastAPI's threadpool, same as P0).

`GET /catalog/items` -> `200`
```json
{"items": [{"code": "sound_speaker_active_15", "name": "Parlante activo 15 pulgadas",
            "category": "sound", "stock_quantity": 8, "unit_price_cop": 120000}]}
```
`GET /catalog/packages` -> `200`
```json
{"packages": [{"code": "pkg_basic_party", "name": "Fiesta Basica", "discount_bps": 1000,
               "base_price_cop": 540000,
               "items": [{"item_code": "sound_speaker_active_15", "quantity": 2}]}]}
```
`base_price_cop` is per rental day before discount (derived by the domain); `discount_bps` is the package's raw value. Both lists are ordered by `code`. Errors: `503 {"detail": "catalog_unavailable"}` on `RepositoryUnavailable`; no hosts, SQL or driver text. Unknown paths and methods use FastAPI defaults.

Schemas (`entrypoints/api/schemas.py`, Pydantic v2, `frozen=True`): `CatalogItemOut`, `PackageLineOut`, `ServicePackageOut`, `ItemsResponse`, `PackagesResponse`, each with a `from_domain` classmethod. Pydantic never enters `domain` or `application`. The API names the unit in the field (`unit_price_cop`) instead of a nested `{amount, currency}` object: P1 is single-currency and the explicit field name matches the column.

### D16. No pagination
The catalog is bounded by the business (tens of items; seed 30 + 5, and the success criterion caps it at 40/6). The two payloads are about 6 KB and 2 KB. Pagination would add `limit/offset/total` semantics, a stable-sort requirement and client loops for no benefit, and the P2 RAG indexer and frontend both want the whole list. Escape hatch: if the catalog ever exceeds ~200 rows, add keyset pagination (`?after=<code>&limit=`) as a backward-compatible change (the response is already wrapped in an object, so adding `next` is non-breaking). Also no `?category=` filter yet (YAGNI; clients filter 30 rows).

### D17. Wiring
`container.py` gains `make_catalog_repository(factory)`, `make_booking_repository(factory)`, `make_pricing_rules()`, `make_availability_rules()`. `create_app(...)` gains optional `catalog_repository` and `booking_repository` overrides (same seam as `database_health`), stores them plus the two rule objects on `app.state` (the rules are not read by any P1 route; they are the documented extension point for the P2 tools), and includes `routes/catalog.router`. Routes read `request.app.state.catalog_repository` like `health.py` does; FastAPI `Depends` is not introduced (consistency with P0, no second DI mechanism). Only `container.py` imports concrete adapters. `cors` already allows `GET`.

## 11. Architecture and test infrastructure changes

### D18. `test_architecture.py`: tighten, never weaken
Required for the new code to be checked, all in the same commit as the code they protect:
1. `FRAMEWORKS` adds `pydantic`, `starlette`, `psycopg` (today only `pydantic_settings` is listed, so `domain` importing `pydantic` would pass).
2. New test `test_domain_imports_only_stdlib_and_itself` (PR A1): for every domain file, each imported module's top-level name must be in `sys.stdlib_module_names` or equal `eventssound` followed by `domain` (allowlist, not denylist; this is stronger than listing frameworks and turns "stdlib only" from convention into a check). Includes a scanner self-test (`import numpy` in a tmp file is flagged; `from datetime import datetime` and `from . import money` are not). Reuses `imported_modules`.
3. `FORBIDDEN["application"]` adds `FRAMEWORKS` and `eventssound.config` (use cases must not see Settings or a framework; current application code already complies).
4. PR C2: new test that no module under `entrypoints/api/routes/` imports `eventssound.adapters` (routes stay thin; only `container.py` wires adapters).
The allowed-set for `adapters` and `entrypoints` is unchanged. `test_layout.py` needs no change.

### D19. Test infrastructure
- `tests/integration/test_migrations.py::alembic_config` currently drops only `alembic_version`. With real tables, `test_upgrade_to_head_records_baseline` would leave them behind and the next test's `upgrade` fails with "relation already exists". The reset moves to `tests/conftest.py` as `reset_schema(url)`: `Base.metadata.drop_all` (importing `models`) plus `DROP TABLE IF EXISTS alembic_version`. Rejected: `DROP SCHEMA public CASCADE` (broader blast radius if `DATABASE_URL_TEST` is mis-set; it would also destroy extensions P2 adds).
- New fixtures in `tests/conftest.py`: `migrated_database` (session scope: reset, `upgrade head`), `session_factory(migrated_database)` (function scope: `TRUNCATE ... RESTART IDENTITY CASCADE` on the five tables, then yields a `sessionmaker`). All depend on `database_url`, so the skip-unset / fail-unreachable rule is inherited. Because migration tests also reset the schema, `migrated_database` must re-run `upgrade head` when the schema is absent: it checks for `equipment_items` per test (cheap) instead of trusting session order.
- `tests/fakes.py`: `InMemoryCatalogRepository`, `InMemoryBookingRepository` (implement the Protocols, filter by window), `BrokenCatalogRepository` (raises `RepositoryUnavailable`). `tests/strategies.py`: Hypothesis strategies (D20). Both are importable by name (tests are collected in prepend mode with `tests/` on `sys.path`, as `conftest.py` already is); no `__init__.py` is added.
- Hypothesis profile registered in `conftest.py`: `settings.register_profile("ci", max_examples=100, deadline=None, derandomize=True)` selected when `CI` is set, a `dev` profile (`max_examples=50`, `deadline=None`) otherwise. `derandomize` keeps CI deterministic; failures reproduce locally with the printed `@reproduce_failure`/seed.
- Dependencies: `hypothesis>=6.100` in the `dev` group; `tzdata>=2024.1` runtime (D6).

### Test layout
```
tests/unit/   (no DB, no I/O)
  test_money.py, test_catalog.py, test_event_request.py, test_pricing_rules.py
  test_pricing.py              table-driven examples + worked example
  test_pricing_properties.py   Hypothesis
  test_quote_contract.py       golden to_dict() snapshot, schema_version
  test_availability.py         table-driven edge cases
  test_availability_properties.py   Hypothesis + brute-force oracle
  test_use_cases.py            application layer with tests/fakes.py
  test_seed_data.py            seed data validity + oracle smoke
  test_seed_guard.py           CLI guard matrix (no DB)
tests/integration/
  test_catalog_schema.py       (DB) tables, named constraints, drift
  test_catalog_repository.py, test_booking_repository.py   (DB)
  test_seed.py                 (DB) twice-run idempotence, counts, convergence of edited package
  test_catalog_api.py          (no DB) create_app(catalog_repository=fake) through TestClient
  test_catalog_api_db.py       (DB) seeded database through the real wiring
```
Table-driven cases use `pytest.mark.parametrize` with `id=` labels. Availability table: back-to-back with buffer 0 (allowed), gap exactly buffer (allowed), gap buffer minus 1 minute (rejected), overlap, contained, containing, multi-day, same-day turnaround, stock 1 vs 3 with partial overlap, two sequential reservations inside one long request (peak 1, the case SUM gets wrong), cancelled excluded (repository), quantity above stock, package components consuming stock, other item's reservations ignored.

### D20. Hypothesis strategies (`tests/strategies.py`)
- `money_pesos = st.integers(0, 10**9)`; `unit_prices = st.integers(1, 2_000).map(lambda n: n * 1000)` (realistic, rounding-friendly) plus a separate `odd_unit_prices = st.integers(1, 2_000_000)` to exercise rounding.
- `catalogs()`: 1-8 items with unique codes (`st.lists(..., unique_by=lambda i: i.code)`), stock `1..50`, 0-3 packages built from sampled existing codes with `discount_bps` in `0..3000`.
- `rule_sets()`: starts from `default_pricing_rules()` and varies tier bps (sorted), band rates, rounding step in `{1, 100, 1000}`, weekend bps, night bps, holidays set drawn from a small date range.
- `bogota_datetimes = st.datetimes(min_value=datetime(2026, 1, 1), max_value=datetime(2028, 12, 31), timezones=st.just(ZoneInfo("America/Bogota")))`; `durations = st.timedelta(minutes=30 .. 10 days)`; requests built from a catalog (`st.data()` samples codes from it).
- Availability: `reservation_lists` on a 30-minute grid inside a small window so intervals collide often.
Pricing properties: determinism and invariance under shuffling/duplicate-splitting of requested lines; `total >= 0`; `total % rounding_step == 0`; `sum(lines) == total`; each line reproducible from its fields; `abs(total - subtotal) <= step/2`; total non-decreasing in item quantity, `distance_km`, `guest_count`, `end`; weekend and night flags never decrease the total; adding an unrelated item never decreases it; package discount `<=` package amount; no `float` anywhere (`all(type(v) is int)` over `to_dict()` amounts).
Availability properties: agreement with a brute-force oracle (discretise the window into 30-minute slots, expand intervals by `buffer/2`, count per slot, take the max; independent code path from the sweep, so an off-by-one in either shows up); adding a reservation never increases available units; increasing stock never decreases them; reservations farther than `buffer` from the window are irrelevant; order invariance; request larger than stock is never available.

## 12. Documentation and skill note
- `documentacion/decisions.md`: ADR 12 "Money is whole COP pesos" (BIGINT `*_cop`, final rounding to 1000 half-up, why not cents) in PR B1, per the proposal; ADR 13 "Availability computed in the domain" (D8/D9 summary) in PR C2.
- `documentacion/architecture.md` (PR C2): domain module list, the two ports, the `quote-domain-core` spec/design links.
- One-line note in `.claude/skills/database-conventions/SKILL.md` under "Naming" (PR B1): "Money: `*_cents` is the generic example; COP has no practical minor unit, so this project stores whole pesos in `*_cop` BIGINT columns (ADR 12). Never float."
- `.claude/skills/design-patterns/SKILL.md` reference to the planned `EquipmentRepository` is updated to `CatalogRepository` / `BookingRepository` (PR C2, one line).

## 13. PR slicing plan (stacked to main; each PR states start, end, dependencies, follow-up, out-of-scope)

Honest forecast: the proposal's 3 PRs of about 400 lines under-count. Strict TDD (tests in the same commit) and the property tests roughly double the source size. Realistic total is about 2,600-3,000 changed lines excluding lockfiles, so the three proposal groups become 9 slices. Line counts are additions plus deletions, rough.

| Slice | Branch | Content (files) | Est. lines | Over 400? |
| ----- | ------ | --------------- | ---------- | --------- |
| A1 | `feat/quote-domain-pricing` (existing worktree branch) | `domain/{errors,money,catalog}.py`; tests `test_money`, `test_catalog`; `test_architecture.py` (D18 items 1-3 + stdlib allowlist test) | ~330 | No |
| A2 | `feat/quote-domain-rules` | `domain/{event_request,pricing_rules}.py`; tests `test_event_request`, `test_pricing_rules`; `pyproject.toml` (`tzdata`) | ~340 | No |
| A3 | `feat/quote-domain-calculate-price` | `domain/pricing.py`; `pyproject.toml` (`hypothesis`); `tests/strategies.py`, conftest profiles; tests `test_pricing`, `test_pricing_properties`, `test_quote_contract` | ~420-450 | Borderline. Cut: land `test_pricing_properties.py` and the Hypothesis dependency in an A3b follow-up (~170 lines); A3 keeps table-driven + golden tests |
| A4 | `feat/quote-domain-availability` | `domain/availability.py`; tests `test_availability`, `test_availability_properties` | ~270 | No |
| B1 | `feat/quote-persistence-schema` | `adapters/db/models.py`; `0002`, `0003`; `migrations/env.py` import; `conftest` reset + fixtures; `test_migrations.py` fixture change; `test_catalog_schema.py`; ADR 12; skill note | ~370 | No |
| B2 | `feat/quote-persistence-repositories` | `application/{ports,errors}.py`; `adapters/db/{catalog,booking}_repository.py`; `tests/fakes.py`; `test_catalog_repository.py`, `test_booking_repository.py` | ~320 | No |
| B3 | `feat/quote-seed` | `adapters/db/{seed_data,seed}.py`; `entrypoints/cli/{__init__,seed_catalog}.py`; `config.py` (+`allow_remote_seed`), `.env.example` line; `test_seed_data`, `test_seed_guard`, `test_seed` | ~420-450 | Yes. Cut: B3a = seed data + upsert + `test_seed_data` + `test_seed` (~280); B3b = CLI, guard, Settings flag, `.env.example`, `test_seed_guard` (~170) |
| C1 | `feat/quote-use-cases` | `application/{catalog,pricing,availability}.py`; `test_use_cases.py` | ~220 | No |
| C2 | `feat/catalog-api` | `entrypoints/api/{schemas,routes/catalog,container,app}.py`; routes-do-not-import-adapters test; `test_catalog_api`, `test_catalog_api_db`; docs (ADR 13, `architecture.md`, skill line) | ~380 | Borderline. Cut: move the docs edits to a trailing `docs:` commit/PR (~70 lines) |

Dependencies and merge order: A1 -> A2 -> A3 (-> A3b) -> A4; B1 needs A1 only for domain names used by the models' defaults (none), but is ordered after A4 to keep one chain; B2 needs A1-A4 and B1; B3 needs B1 and A1; C1 needs A4 and B2; C2 needs C1, B2, B3a. Per AGENTS.md, retarget each dependent PR to `main` BEFORE merging its parent.
Schedule risk: 9-11 reviewable PRs inside the 1.5-day P1 budget is aggressive. The only compliant ways to shorten are (a) accept fewer slices with `size:exception` for the pure-domain chain (A1-A3 are cohesive and have no I/O, so the reviewer risk is lower there), or (b) ship A and B1-B2 first and defer the seed CLI guard (B3b) behind the API. Needs a developer decision before `sdd-tasks`.

## 14. Risks and open points
1. Five tables instead of four (D10): small scope increase to avoid a later migration; needs confirmation.
2. Package discount placement (D4) deviates from the proposal's wording; reversible in A2 with no database impact.
3. Percentage lines are rounded to the peso (D3); the 1000 rounding is still applied once. Equivalent for the synthetic data, but it is an interpretation of "once at the end".
4. Rental-day billing, flat weekend/night surcharges and additive percentages (steps 2, 5, 7, 8) are modelling choices the proposal did not fix; they are cheap to change while no consumer exists but become the P3 oracle contract once the golden set is written.
5. `tzdata` becomes a runtime dependency and `hypothesis` a dev one; both touch `uv.lock` (excluded from the line budget).
6. `ALLOW_REMOTE_SEED` requires editing `.env.example`, which the "never read `.env*`" rule covers by glob; the apply phase needs explicit permission to edit that placeholders-only file, and still must not open real env files.
7. Slice count and schedule (section 13).
8. Pending bookings block stock and never expire in P1; expiry belongs with booking creation.
