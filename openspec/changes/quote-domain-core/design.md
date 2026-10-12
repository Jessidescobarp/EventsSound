# Design: quote-domain-core (P1 Domain core)

> **Scope cuts (2026-10-12):** this design was written for the full 11-PR plan. Where it conflicts with `tasks.md` section "Scope cuts and decisions (2026-10-12)", `tasks.md` wins. Affected: Hypothesis/property tests (D19, D20) replaced by table-driven tests; `booking_items` table (D10) dropped for a flat `bookings` table; seed 20 items / 4 packages (D13); seed CLI keeps only `--confirm` and the remote guard (D14); `Quote` versioning is a single `version` field (D7); OpenAPI/Swagger is public in production (D15/D17); use cases ship inside the API PR. The design body below is intentionally not rewritten, EXCEPT the persistence parts (layout, D9-D11, section 9 with D13-D14, the fixtures in D19), which were rewritten on 2026-10-12 to match the delivered persistence PR (B1+B2+B3 consolidated).

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
    availability.py    BookingStatus, Booking, AvailabilityRules, default_availability_rules(),
                       Availability, AvailabilityReport,
                       available_units, check_availability, check_request_availability, required_units
  application/
    ports.py           (existing) + CatalogRepository, BookingRepository
    errors.py          RepositoryUnavailable, InvalidStoredData
    booking_query.py   ReservationQuery (validated input of find_reservations, shared by every implementation)
    catalog.py         list_catalog(catalog_repo) -> Catalog
    pricing.py         price_quote(request, catalog_repo, rules) -> Quote
    availability.py    check_event_availability(request, catalog_repo, booking_repo, rules) -> AvailabilityReport
  adapters/db/
    models.py          4 SQLAlchemy models on Base (flat bookings)
    catalog_repository.py   SqlAlchemyCatalogRepository
    booking_repository.py   SqlAlchemyBookingRepository
    seed_data.py       SEED_ITEMS (20), SEED_PACKAGES (4), SEED_BOOKINGS (demo, domain values, pure data)
    seed.py            seed_catalog(session_factory, items, packages, bookings=()) -> SeedResult
  entrypoints/
    cli/__init__.py, cli/seed_catalog.py   python -m eventssound.entrypoints.cli.seed_catalog
    api/schemas.py, api/routes/catalog.py, api/container.py (extended), api/app.py (extended)
backend/migrations/versions/0002_catalog_and_bookings.py
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

Types: `BookingStatus(StrEnum)`: `PENDING, CONFIRMED, CANCELLED`, with `BookingStatus.blocking() -> {PENDING, CONFIRMED}`. `Booking(code, item_code, quantity >= 1, start, end, status)`: one reserved item of one booking, tz-aware, `end > start`, `code` matching `[A-Za-z0-9_-]{1,64}`, `item_code` matching the catalog code pattern; `(code, item_code)` is unique per booking (a duplicated row counts twice, which errs toward unavailable). The domain, not the repository, ignores `CANCELLED` bookings. `AvailabilityRules(buffer: timedelta)` with `default_availability_rules()` = 2 hours (decision 2); validated `>= 0` and a whole number of minutes. Kept apart from `PricingRules`: the buffer is not a pricing datum, and `calculate_price` should not receive fields it never reads.

Naming: the pure function receives item-level `Booking` values (one per booked item). The repository may pre-filter by status in SQL as defence in depth, but correctness does not depend on it. The buffer is passed as `rules: AvailabilityRules` (`0 <= buffer <= 7 days`, whole minutes).

### D8. Algorithm: interval-graph peak concurrency with buffers split in half
Two uses of one unit are compatible iff the gap between them is `>= buffer` (half-open intervals, so a gap of exactly `buffer` is allowed). Expanding every interval by `buffer/2` on each side turns that into plain half-open overlap, and units are interchangeable, so the minimum units needed is the maximum clique of an interval graph = peak concurrency (exact, no heuristics).

`available_units(item, start, end, bookings, rules)` (all instants converted with `.astimezone(UTC)`):
1. Ignore bookings of other items and non-blocking statuses (`CANCELLED`).
2. Keep bookings whose expanded interval `[b.start - buffer/2, b.end + buffer/2)` overlaps the expanded request, tested on the raw UTC bounds as `b.start < end + buffer and b.end > start - buffer`, so a booking far from the window is never shifted (a far-future booking cannot break unrelated queries). A booking that does overlap but cannot be expanded within the datetime range fails closed with `InvalidAvailability`.
3. Sweep line: events `(b.start - buffer/2, +quantity)` and `(b.end + buffer/2, -quantity)`; sort by `(time, delta)` so releases (negative) precede acquisitions at equal timestamps regardless of input order (half-open: touching intervals do not overlap); track the running sum, `peak = max`. No clamping to the window is needed: bookings that overlap the window are convex, so any clique of them also meets the window.
4. Return `max(0, stock - peak)`.

`check_availability(item, start, end, bookings, rules, quantity=1)` returns `Availability(item_code, requested, stock, remaining)` with properties `is_available` (`remaining >= requested`) and `shortfall` (`max(0, requested - remaining)`), using `item.stock_quantity` (bookings for other item codes are ignored). `Availability` and `AvailabilityReport` validate themselves (types, `0 <= remaining <= stock`, non-empty report sorted by distinct code). `check_request_availability(request, catalog, bookings, rules)` first computes `required_units`: the sum over loose items plus `package.quantity * line.quantity` for package components, per item code (a package consumes stock like its parts), then checks each item and returns `AvailabilityReport(items)` sorted by code, with `is_available` and `shortages` (the limiting items, each carrying `requested`, `remaining` and `shortfall` for the Spanish explanation). Malformed bookings and queries raise `InvalidAvailability`; unknown codes raise `UnknownCatalogEntry`.

Complexity: `O(n log n)` for `n` bookings overlapping the window (sort dominates); `O(I * n log n)` for `I` distinct items in the request (`I <= 100`).

Semantics worth stating: back-to-back events are allowed only if the gap is `>= buffer`, so with the 2-hour default "back-to-back" means a 2-hour gap; with `buffer = 0` they may touch exactly. Multi-day events are plain long intervals. Existing data that already violates the buffer is counted conservatively (peak may overcount; never undercounts). Pending bookings block stock (conservative); cancelled ones do not.

### D9. SQL strategy: coarse overlap filter in SQL, exact computation in the domain
The adapter returns candidates with an indexed range predicate; the sweep runs in Python.
```sql
SELECT booking_code, item_code, quantity, starts_at, ends_at, status
FROM bookings
WHERE item_code = ANY(:codes)
  AND status IN ('pending', 'confirmed')
  AND starts_at < :window_end AND ends_at > :window_start
ORDER BY starts_at, booking_code, item_code
```
The flat table keeps this a single-table select (no join).
The use case passes `window = [start - buffer, end + buffer)`. Why not SQL-only:
- `SUM(quantity)` over overlapping rows counts reservations that overlap the window but not each other, so it overstates demand (two sequential 1-unit bookings inside a long request would look like 2 concurrent). Computing true peak concurrency in SQL needs a window-function sweep over event rows, which is harder to read and to test.
- A Postgres `tstzrange` + GiST `EXCLUDE` constraint is perfect for "one resource, no overlap" but cannot express stock `> 1`.
- Keeping the algorithm in the domain gives one implementation shared by the API, the P2 agent tool and the Hypothesis oracle test, with zero database in the property tests.
Cost: the number of rows fetched equals the bookings near the window (tens at MVP volume). Index: `ix_bookings_item_code` on `(item_code, starts_at, ends_at)` (section 7). A GiST range index is premature.

## 7. Database schema

Conventions applied: plural snake_case tables, singular columns, `id` PK, `<entity>_id` FKs, `*_at` timezone-aware, constraint and index names generated by `NAMING_CONVENTION` (check constraints carry a short `name=`), models subclass `Base` and live only in `adapters/db/`.

### D10. Four tables with a FLAT `bookings` (supersedes the five-table proposal)
The earlier draft added a `booking_items` child table. Scope cut 3 (2026-10-12) replaced it with a flat `bookings` table: one row per equipment item per booking, `(booking_code, item_code)` unique. It mirrors the domain `Booking(code, item_code, quantity, start, end, status)` one to one, keeps the availability query a single-table select and needs no header row. Cost: a booking header (customer, totals) is not modelled; when the P2+ "pending booking from a quote" change needs one, it adds a header table with an expand/contract migration. `bookings.item_code` references `equipment_items.code` (unique), not the surrogate id, so the availability query needs no join; package lines still reference ids.

| Table | Columns | Constraints and indexes |
| ----- | ------- | ----------------------- |
| `equipment_items` | `id` BIGINT identity PK; `code` VARCHAR(64) NOT NULL; `name` VARCHAR(120) NOT NULL; `category` VARCHAR(16) NOT NULL; `stock_quantity` INTEGER NOT NULL; `unit_price_cop` BIGINT NOT NULL; `created_at`, `updated_at` TIMESTAMPTZ NOT NULL DEFAULT now() | UNIQUE `code`; CHECK `category_valid` (`category IN (...)`); CHECK `stock_nonnegative`; CHECK `unit_price_nonnegative` |
| `service_packages` | `id` PK; `code` VARCHAR(64) NOT NULL; `name` VARCHAR(120) NOT NULL; `discount_bps` INTEGER NOT NULL DEFAULT 0; `created_at`, `updated_at` | UNIQUE `code`; CHECK `discount_range` (`0..10000`) |
| `package_items` | `id` PK; `package_id` BIGINT NOT NULL; `equipment_item_id` BIGINT NOT NULL; `quantity` INTEGER NOT NULL | UNIQUE (`package_id`, `equipment_item_id`); FK `package_id` -> `service_packages.id` ON DELETE CASCADE; FK `equipment_item_id` -> `equipment_items.id` ON DELETE RESTRICT; CHECK `quantity_positive`; index on `equipment_item_id` (reverse lookup; `package_id` is covered by the unique constraint) |
| `bookings` | `id` BIGINT identity PK; `booking_code` VARCHAR(64) NOT NULL; `item_code` VARCHAR(64) NOT NULL; `quantity` INTEGER NOT NULL; `starts_at`, `ends_at` TIMESTAMPTZ NOT NULL; `status` VARCHAR(16) NOT NULL DEFAULT `'pending'`; `created_at`, `updated_at` | UNIQUE (`booking_code`, `item_code`); FK `item_code` -> `equipment_items.code` ON DELETE RESTRICT; CHECK `quantity_positive`; CHECK `ends_after_starts` (`ends_at > starts_at`); CHECK `status_valid` (`pending`, `confirmed`, `cancelled`); index `ix_bookings_item_code` on (`item_code`, `starts_at`, `ends_at`) |

Money columns are `*_cop` BIGINT (decision 1); `_bps` is basis points. `category` and `status` are `VARCHAR + CHECK`, not native PG ENUM types: adding a value to an ENUM and dropping the type on downgrade are the painful parts of migrations; the CHECK is dropped and recreated in a normal revision. ON DELETE policy: children owned by a parent (`package_items`) cascade; references to catalog items are `RESTRICT` so an item with history cannot be deleted by accident (catalog rows are retired by a later `is_active` column, not deleted; not needed in P1, so not added). `updated_at` is set by `onupdate=func.now()` in the model and explicitly in the seed upsert.

### D11. Migration: one reversible, hand-written revision, schema only
- `0002_catalog_and_bookings` (`down_revision = "0001"`): `equipment_items`, `service_packages`, `package_items`, `bookings` and their indexes. `downgrade()` drops `bookings`, `package_items`, `service_packages`, `equipment_items` in FK order. One revision because the four tables are one deployable unit and one head keeps the history simple.
Drafted from `alembic revision --autogenerate` and then written by hand (skill: review autogenerate by hand). Every constraint and index name is literal, wrapped in `op.f(...)` so Alembic never re-applies the naming convention: the revision stays frozen history even if the convention or the models change later, and the names equal the model names (pinned by the drift test and the naming test). The category/status value lists are literal strings for the same reason (revisions must not import application code).
`migrations/env.py` gets `import eventssound.adapters.db.models  # noqa: F401`. Without it `Base.metadata` is empty in the Alembic process and autogenerate would propose dropping the tables.
Tests (all under `DATABASE_URL_TEST`, `tests/integration/test_catalog_schema.py`): upgrade to head creates exactly the four tables and they are empty; downgrade to `0001` and to base leave none; upgrade/downgrade/upgrade round trip; repeat upgrade is a no-op; the expected constraint and index names exist and all follow the `pk_/fk_/uq_/ck_/ix_` prefixes; every CHECK, UNIQUE, FK (RESTRICT and CASCADE) is exercised with an invalid row; a UTC-5 timestamp round-trips as the same instant; a drift test using `alembic.autogenerate.compare_metadata` asserts an empty diff between the migrated database and `Base.metadata`; and a DB-free test asserts that `migrations/env.py` imports the models module.
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
    ) -> Sequence[Booking]:
        """Item-level bookings (any status; blocking ones at least) whose [start, end) intersects the window.
        Unknown codes yield no rows. Raises RepositoryUnavailable on storage failure."""
```
### D12. `get_catalog()` returns the whole `Catalog`; two ports, not one
Items and packages are always used together (a package must resolve its items), the catalog is tens of rows, and a single method gives pricing, listing and availability the same consistent snapshot. Rejected: `list_items()` / `list_packages()` / `get_item(code)` (three queries, possible inconsistency, a chatty 15-method port). `BookingRepository` is a separate port (ISP): the catalog read side and the reservation read side change for different reasons and P2 tools use them independently. No `EquipmentRepository` (the design-patterns skill mentions that name as "planned"; the skill reference should be updated in PR C2 docs).
`RepositoryUnavailable` (in `application/errors.py`) is raised by adapters wrapping `SQLAlchemyError`, with a generic message (no URL, host or SQL, per the coding skill). Routes map it to 503.

Use cases: `list_catalog(catalog_repo) -> Catalog`; `price_quote(request, catalog_repo, rules) -> Quote` (loads the catalog, calls `calculate_price`); `check_event_availability(request, catalog_repo, booking_repo, rules: AvailabilityRules) -> AvailabilityReport` (loads catalog, `required_units`, queries bookings for those codes in `[start - buffer, end + buffer)`, calls `check_request_availability`). Data flow for availability:

```
use case ──get_catalog()──────────────> CatalogRepository ──> Catalog
use case ──required_units(req, cat)──> {code: qty}
use case ──find_reservations(codes, start-buffer, end+buffer)──> BookingRepository ──> [Booking]
use case ──check_request_availability(...)──> AvailabilityReport (domain, pure)
```
Neither `price_quote` nor `check_event_availability` is exposed over HTTP in P1 (decision 5); they are covered by unit tests with fakes and become the bodies of the P2 tools.

## 9. Adapters

- `models.py`: `EquipmentItemModel`, `ServicePackageModel`, `PackageItemModel`, `BookingModel` (SQLAlchemy 2.0 `Mapped[...]` / `mapped_column`, `DateTime(timezone=True)`, `BigInteger`, `relationship` only where needed: `ServicePackageModel.lines` loaded with `selectinload`). Class names do not collide with domain names.
- `SqlAlchemyCatalogRepository(session_factory)`: `with factory() as session`, one `REPEATABLE READ` snapshot for two `select` statements ordered by `code` (items, then packages with their lines), mapped to domain entities in a private `_to_domain` (lines sorted by item code). A bad row (unknown category, malformed code, absurd price, dangling line) raises `InvalidStoredData` carrying only the generic domain message, never a raw `ValueError`/`KeyError`; it is never skipped silently.
- `SqlAlchemyBookingRepository(session_factory)`: validates the input through `ReservationQuery` first (`InvalidAvailability` before any storage access; an empty code set returns `()` without a query), then the SQL in D9 via SQLAlchemy Core expressions (selecting columns, so ORM objects never leave the adapter), `status` filter from `BookingStatus.blocking()`, deterministic order. `booking_from_row` maps one row to a `Booking`: the booking `code` must match `[A-Za-z0-9_-]{1,64}`, the item code the catalog pattern, quantity is a real `int`, instants are tz-aware and the status is a `BookingStatus`; anything else raises `InvalidStoredData`. Read-only; no commit.
- Both wrap `SQLAlchemyError` into `RepositoryUnavailable("... storage unavailable")` with `raise ... from None`; tests assert that neither the message nor the formatted traceback contains the user, password, host or database name of an unreachable URL.

### D13. Seed: idempotent upsert keyed on `code`, guarded, never part of a migration
`seed_catalog(session_factory, items, packages, bookings=()) -> SeedResult(items, packages, bookings)` (counts of definitions upserted) validates its input first (collections of the right types, never a bare string; `Catalog(items, packages)` for duplicate codes and dangling references; every booking references a seeded item and `(code, item_code)` is unique; failures raise a domain error and write nothing), then runs in one transaction via `session_factory.begin()` (commit on success, roll back on error; `SQLAlchemyError` becomes `RepositoryUnavailable`):
- Items: `INSERT ... ON CONFLICT (code) DO UPDATE SET name, category, stock_quantity, unit_price_cop, updated_at = now()` (`sqlalchemy.dialects.postgresql.insert`; the stack is Postgres-only, so a dialect-specific upsert is atomic and shorter than select-then-update).
- Packages: upsert on `code`; resolve item ids by code; upsert `package_items` on (`package_id`, `equipment_item_id`); delete `package_items` of that package whose item is not in the seed definition (so editing a package definition converges).
- Demo bookings: upsert on (`booking_code`, `item_code`), restoring quantity, interval and status. Only the bookings in the definition are ever written.
- Never deletes rows absent from the seed data (it cannot destroy data a developer added by hand) and never touches other bookings.
- Running it twice yields identical row counts and identical content, `created_at` included (tested).

Seed data (`adapters/db/seed_data.py`, compact helper `_item(code, name, category, stock, price)`; prices multiples of 1000, stock 2-24 except a few scarce items, Spanish `name`, English snake_case `code` with a category prefix):
| Category | Count | Outline |
| -------- | ----- | ------- |
| sound | 7 | active speakers 12"/15", subwoofer 18", line-array module, stage monitor, 16-channel console, wireless mic |
| lighting | 5 | LED par, moving head spot, moving head wash, strobe, DMX controller |
| dj | 3 | DJ controller, CDJ pair, DJ mixer |
| stage | 2 | 2x1 m stage module, access stairs |
| effects | 2 | fog machine, cold-spark fountain |
| video | 1 | LED screen 3x2 m |
| **Total** | **20** | |

Four packages, each 5-6 lines (so each references real items), `discount_bps` between 500 and 1500: `pkg_basic_party` (Fiesta Basica), `pkg_wedding` (Boda), `pkg_corporate` (Evento corporativo), `pkg_dj_night` (Noche DJ). Five demo bookings (`DEMO-001`..`DEMO-004`, Saturday 2026-11-14 and 2026-11-21 in Bogota time) mix confirmed, pending and cancelled statuses, so the availability demo shows reduced stock where bookings block and full stock where one is cancelled. The module-level tuples are plain domain entities; a unit test builds `Catalog(SEED_ITEMS, SEED_PACKAGES)` (validates references and uniqueness), asserts 20 / 4, price multiples of 1000 and slug codes, runs `calculate_price` on a sample request per package so the data and the oracle are tested together, and checks `check_availability` against the demo bookings.

### D14. Seed guard (`entrypoints/cli/seed_catalog.py`)
`main(argv=None, settings=None, session_factory=None, environ=None) -> int` (injectable, so tests never touch a real database or the real environment). `ALLOW_REMOTE_SEED` is read ONLY here, from `environ` (default `os.environ`), compared with exactly `"1"`; it is NOT a `Settings` field, so `config.py` and `.env.example` are unchanged (developer rule, supersedes the earlier draft that added `Settings.allow_remote_seed`). This is the one documented exception to "no `os.environ` outside Settings": it is an operator override of a script, not application configuration.
1. No `--confirm`: print `dry run: would upsert 20 items, 4 packages and 5 demo bookings. Pass --confirm to write.`, exit 2, before loading `Settings` or building any engine. `--confirm` is the only option (argparse rejects others with exit 2).
2. Target classification (`is_local_target`) uses `sqlalchemy.engine.make_url(url)`: local = host in `{"localhost", "127.0.0.1", "::1", "db"}` (case-insensitive), a unix-socket directory, or no host. libpq lets the query string override the URL host, so `?host=` values (comma-separated lists too) must all be local, and `?hostaddr=` or `?service=` are always non-local. `"db"` mirrors `LOCAL_HOSTS` in `test_env_example.py` (compose service name).
3. A non-local target, or `APP_ENV` equal to `production` (trimmed, case-insensitive), requires `environ["ALLOW_REMOTE_SEED"] == "1"` (`"true"`, `"0"`, `""`, `" 1"` all refuse); otherwise exit 3 with `refusing to seed a non-local or production target; set ALLOW_REMOTE_SEED=1 to override`. The check precedes any connection.
4. Output never contains the URL, the host, the user or exception text from the driver; only counts and the local/remote classification. A missing `DATABASE_URL`, an unparsable or non-PostgreSQL URL, an unavailable database and invalid definitions each give a fixed generic message and exit 1.
5. Only `DATABASE_URL` and `APP_ENV` from `Settings` are used; `.env*` files are never opened by this code (Settings' own optional root `.env` loading is unchanged and not read by tooling).
Rejected: a `--allow-remote` CLI flag (a flag in shell history is easier to paste into the wrong terminal than an explicit env var).

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
- `tests/integration/test_migrations.py::alembic_config` used to drop only `alembic_version`. With real tables, `test_upgrade_to_head_records_baseline` would leave them behind and the next test's `upgrade` fails with "relation already exists". The reset moved to `tests/conftest.py` as `reset_schema(url)`: `Base.metadata.drop_all` (importing `models`) plus `DROP TABLE IF EXISTS alembic_version`. Rejected: `DROP SCHEMA public CASCADE` (broader blast radius if `DATABASE_URL_TEST` is mis-set; it would also destroy extensions P2 adds).
- Fixtures in `tests/conftest.py` (all function scoped and built on `database_url`, so skip-unset / fail-unreachable is inherited): `alembic_config` (reset schema, config bound to the test database), `migrated_database` (`upgrade head`, schema dropped afterwards) and `session_factory` (a `sessionmaker` on `migrated_database`). A fresh migration per test (about 0.3 s) replaced the planned session-scoped fixture with `TRUNCATE`: migration tests reset the schema, so a shared migrated database would depend on test order. `unreachable_session_factory` (connection to a closed port with sentinel credentials, 1 s timeout) backs the "no secrets in errors" tests.
- `tests/fakes.py`: `InMemoryCatalogRepository`, `InMemoryBookingRepository` (implement the Protocols, validate the query with `ReservationQuery`, filter by item code and half-open window, return every status), `BrokenCatalogRepository` and `BrokenBookingRepository` (raise `RepositoryUnavailable`). `tests/strategies.py`: Hypothesis strategies (D20). Both are importable by name (tests are collected in prepend mode with `tests/` on `sys.path`, as `conftest.py` already is); no `__init__.py` is added.
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
Table-driven cases use `pytest.mark.parametrize` with `id=` labels. Availability table: back-to-back with buffer 0 (allowed), gap exactly buffer (allowed), gap buffer minus 1 minute (rejected), overlap, contained, containing, multi-day, same-day turnaround, stock 1 vs 3 with partial overlap, two sequential reservations inside one long request (peak 1, the case SUM gets wrong), cancelled excluded (domain, by status), quantity above stock, package components consuming stock, other item's bookings ignored; input order irrelevant (tie ordering pinned in both orders).

### D20. Hypothesis strategies (`tests/strategies.py`)
- `money_pesos = st.integers(0, 10**9)`; `unit_prices = st.integers(1, 2_000).map(lambda n: n * 1000)` (realistic, rounding-friendly) plus a separate `odd_unit_prices = st.integers(1, 2_000_000)` to exercise rounding.
- `catalogs()`: 1-8 items with unique codes (`st.lists(..., unique_by=lambda i: i.code)`), stock `1..50`, 0-3 packages built from sampled existing codes with `discount_bps` in `0..3000`.
- `rule_sets()`: starts from `default_pricing_rules()` and varies tier bps (sorted), band rates, rounding step in `{1, 100, 1000}`, weekend bps, night bps, holidays set drawn from a small date range.
- `bogota_datetimes = st.datetimes(min_value=datetime(2026, 1, 1), max_value=datetime(2028, 12, 31), timezones=st.just(ZoneInfo("America/Bogota")))`; `durations = st.timedelta(minutes=30 .. 10 days)`; requests built from a catalog (`st.data()` samples codes from it).
- Availability: `reservation_lists` on a 30-minute grid inside a small window so intervals collide often.
Pricing properties: determinism and invariance under shuffling/duplicate-splitting of requested lines; `total >= 0`; `total % rounding_step == 0`; `sum(lines) == total`; each line reproducible from its fields; `abs(total - subtotal) <= step/2`; total non-decreasing in item quantity, `distance_km`, `guest_count`, `end`; weekend and night flags never decrease the total; adding an unrelated item never decreases it; package discount `<=` package amount; no `float` anywhere (`all(type(v) is int)` over `to_dict()` amounts).
Availability properties: agreement with a brute-force oracle (discretise the window into 30-minute slots, expand intervals by `buffer/2`, count per slot, take the max; independent code path from the sweep, so an off-by-one in either shows up); adding a reservation never increases available units; increasing stock never decreases them; reservations farther than `buffer` from the window are irrelevant; order invariance; request larger than stock is never available.

## 12. Documentation and skill note
- `documentacion/decisions.md`: ADR 12 "Money is whole COP pesos" (BIGINT `*_cop`, final rounding to 1000 half-up, why not cents), per the proposal (NOT yet written: the persistence PR did not touch `documentacion/`; open item in tasks.md B1.5); ADR 13 "Availability computed in the domain" (D8/D9 summary) in PR C2.
- `documentacion/architecture.md` (PR C2): domain module list, the two ports, the `quote-domain-core` spec/design links.
- One-line note in `.claude/skills/database-conventions/SKILL.md` under "Naming" (PR B1): "Money: `*_cents` is the generic example; COP has no practical minor unit, so this project stores whole pesos in `*_cop` BIGINT columns (see the quote-domain-core design). Never float." Delivered; the reference points at the design until ADR 12 exists.
- `.claude/skills/design-patterns/SKILL.md` reference to the planned `EquipmentRepository` is updated to `CatalogRepository` / `BookingRepository` (PR C2, one line).

## 13. PR slicing plan (stacked to main; each PR states start, end, dependencies, follow-up, out-of-scope)

Honest forecast: the proposal's 3 PRs of about 400 lines under-count. Strict TDD (tests in the same commit) and the property tests roughly double the source size. Realistic total is about 2,600-3,000 changed lines excluding lockfiles, so the three proposal groups become 9 slices. Line counts are additions plus deletions, rough.

| Slice | Branch | Content (files) | Est. lines | Over 400? |
| ----- | ------ | --------------- | ---------- | --------- |
| A1 | `feat/quote-domain-pricing` (existing worktree branch) | `domain/{errors,money,catalog}.py`; tests `test_money`, `test_catalog`; `test_architecture.py` (D18 items 1-3 + stdlib allowlist test) | ~330 | No |
| A2 | `feat/quote-domain-rules` | `domain/{event_request,pricing_rules}.py`; tests `test_event_request`, `test_pricing_rules`; `pyproject.toml` (`tzdata`) | ~340 | No |
| A3 | `feat/quote-domain-calculate-price` | `domain/pricing.py`; `pyproject.toml` (`hypothesis`); `tests/strategies.py`, conftest profiles; tests `test_pricing`, `test_pricing_properties`, `test_quote_contract` | ~420-450 | Borderline. Cut: land `test_pricing_properties.py` and the Hypothesis dependency in an A3b follow-up (~170 lines); A3 keeps table-driven + golden tests |
| A4 | `feat/quote-domain-availability` | `domain/availability.py`; tests `test_availability`, `test_availability_properties` | ~270 | No |
| B1 | `feat/quote-persistence-schema` (delivered together with B2 and B3 as `feat/quote-persistence`, see tasks.md) | `adapters/db/models.py`; `0002_catalog_and_bookings`; `migrations/env.py` import; `conftest` reset + fixtures; `test_migrations.py` fixture change; `test_catalog_schema.py`; ADR 12; skill note | ~370 | No |
| B2 | `feat/quote-persistence-repositories` | `application/{ports,errors}.py`; `adapters/db/{catalog,booking}_repository.py`; `tests/fakes.py`; `test_catalog_repository.py`, `test_booking_repository.py` | ~320 | No |
| B3 | `feat/quote-seed` | `adapters/db/{seed_data,seed}.py`; `entrypoints/cli/{__init__,seed_catalog}.py` (no `config.py` or `.env.example` change); `test_seed_data`, `test_seed_guard`, `test_seed` | ~420-450 | Yes. Cut: B3a = seed data + upsert + `test_seed_data` + `test_seed` (~280); B3b = CLI, guard, `test_seed_guard` (~170) |
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
