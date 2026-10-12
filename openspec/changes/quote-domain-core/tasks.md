# Tasks: quote-domain-core (P1 Domain core)

Inputs: `proposal.md` (with Decisions), `design.md` (D1-D20, PR slicing section 13), `specs/*/spec.md` (same folder), `openspec/config.yaml`, `AGENTS.md`, skills `coding-best-practices`, `architecture-hexagonal`, `database-conventions`.

Delivery decision (developer): FULL design, chained PRs, each under ~400 changed lines (lockfiles and `openspec/` excluded). The design's cuts are applied where it flags a slice as over or near budget: A3 becomes A3 + A3b, B3 becomes B3a + B3b, C2 keeps its docs commit last and splits into a C3 docs PR only if the measured diff passes 400. Result: 11 PRs (9 design slices + 2 cuts). Schedule risk accepted by the developer: MVP deadline 2026-10-25, today 2026-10-12, P2 (agent), P3 (evals) and P4 (UI) still follow.

Legend:
- **[A]** agent-executable (sdd-apply).
- **[M]** manual action by the developer (GitHub settings, merges, retargeting, pushes, anything touching `.env*`). The agent stops and asks.
- **TDD**: strict TDD is ON. Every code task writes the failing test first, runs it red, then implements to green. "Test-first" notes below name that first test.
- Spec refs use `capability / Requirement name`. Design refs use `Dn` or section numbers.

## Spec/design conflicts (resolved in favor of the design)

The design (D2-D8, D10, D15) made deliberate decisions that contradict the older delta specs. Tasks follow the design. Task **A1.1** syncs the specs to the design as a docs-only commit (excluded from the line budget) so `sdd-verify` has a consistent target.

| # | Spec says | Design says (wins) |
| - | --------- | ------------------ |
| 1 | `Money`: negative amounts rejected; subtraction below zero raises | Any sign allowed (discount lines are negative); `round_to` is int-only |
| 2 | Multipliers compose multiplicatively; distance is a flat band surcharge; weekend uses the start date; `Quote` has `steps` + `rounding_adjustment` | Percentages additive on equipment subtotal E; distance is marginal per km; weekend/night over every touched local date; `Quote.lines` with an explicit `ROUNDING` line (D3, D5, D7, section 5) |
| 3 | Buffer and package discount live in `PricingRules` | Buffer in `AvailabilityRules`; package discount on `ServicePackage` with a cap in the rules (D4, section 6) |
| 4 | Availability sums overlapping bookings conservatively | Peak concurrency sweep with buffer/2 on each side (D8) |
| 5 | Four tables, `bookings.item_id` and `quantity`; `display_name`, `description`; `package_items.item_id` | Five tables with `booking_items`; column `name`, no `description`; `equipment_item_id` (D10) |
| 6 | Seed categories include "accessory" | Categories `sound, lighting, dj, stage, effects, video` (D13) |
| 7 | API returns bare arrays with `display_name`, `description` | Wrapped objects `{items}` / `{packages}` with `name`, `base_price_cop`; 503 `catalog_unavailable` (D15) |
| 8 | `ALLOW_REMOTE_SEED` via `Settings`/environment | Read only by the seed CLI via `os.environ`, exact value `"1"`; NOT a `Settings` field (developer rule, supersedes design D14) |

## Review Workload Forecast

| Metric | Value |
| ------ | ----- |
| Estimated changed lines (excl. lockfiles, `openspec/`) | ~2,700-3,100 total across 11 PRs |
| Chained PRs recommended | Yes (resolved: stacked chain, full design) |
| 400-line budget risk | Low-Medium per PR after the cuts. Watch B1 (~370), C2 (~380) and A1/A2 (~330-340). A3 and B3 are already cut |
| Decision needed before apply | No. The developer chose the full design, accepted the schedule risk and the ask-on-risk delivery strategy |

| PR | Branch | Base | Est. lines | Cumulative | Within 400? | Merge order |
| -- | ------ | ---- | ---------- | ---------- | ----------- | ----------- |
| A1 Money + catalog + architecture test | `feat/quote-domain-pricing` | `main` | ~330 | 330 | Yes | 1 |
| A2 Request + rules + tzdata | `feat/quote-domain-rules` | A1 | ~340 | 670 | Yes | 2 |
| A3 calculate_price + golden tests (cut) | `feat/quote-domain-calculate-price` | A2 | ~260 | 930 | Yes | 3 |
| A3b Pricing properties + hypothesis (cut) | `feat/quote-domain-pricing-properties` | A3 | ~170 | 1,100 | Yes | 4 |
| A4 Availability | `feat/quote-domain-availability` | A3b | ~270 | 1,370 | Yes | 5 |
| B1 Schema + migrations + DB fixtures | `feat/quote-domain-schema` | A4 | ~370 | 1,740 | Yes (near) | 6 |
| B2 Ports + repositories + fakes | `feat/quote-domain-repositories` | B1 | ~320 | 2,060 | Yes | 7 |
| B3a Seed data + upsert (cut) | `feat/quote-domain-seed-data` | B2 | ~280 | 2,340 | Yes | 8 |
| B3b Seed CLI + guard (cut) | `feat/quote-domain-seed-cli` | B3a | ~150 | 2,490 | Yes | 9 |
| C1 Use cases | `feat/quote-domain-use-cases` | B3b | ~220 | 2,710 | Yes | 10 |
| C2 Catalog API + docs | `feat/quote-domain-catalog-api` | C1 | ~380 | 3,090 | Yes (near); split docs into C3 if over 400 | 11 |

Measure each PR with: `git diff --shortstat <base-branch>...HEAD -- . ':!backend/uv.lock' ':!openspec'` (run by the agent before opening the PR; if a PR measures over 400, STOP and ask before proceeding).

Dependencies: strictly linear chain. A1 -> A2 -> A3 -> A3b -> A4 -> B1 -> B2 -> B3a -> B3b -> C1 -> C2. Real dependencies are weaker (B1 needs no domain code; B3b needs B3a; C1 needs A4 + B2; C2 needs C1 + B3a), but one chain keeps one merge order and one rebase path.

Each PR description states: start, end, dependencies, follow-up, out-of-scope, and a dependency diagram marking the current PR:

```
A1 -> A2 -> A3 -> A3b -> A4 -> B1 -> B2 -> B3a -> B3b -> C1 -> C2
```

## Merge order and MERGE PROCEDURE (avoids the earlier mistake)

Earlier incident: a stacked PR was merged into its parent branch instead of `main`, so the work never reached `main` (AGENTS.md, Conventions). For this 11-PR chain, follow this for EVERY merge. All steps are [M] (developer) except the verification commands, which the agent can run when asked.

0. One-time [M]: in GitHub repo settings enable "Automatically delete head branches" so GitHub retargets child PRs when a parent branch is deleted on merge. Use the "Create a merge commit" strategy for this chain (see assumption U1: squash and rebase merges rewrite SHAs, which breaks the ancestry check and makes children show duplicated parent commits).
1. Open PR N+1 with base = branch N (reviewable diff). Never merge a PR whose base is not `main`: check the base shown on the PR page before pressing merge.
2. Before merging PR N: retarget PR N+1 to `main` (`gh pr edit <N+1> --base main` or the web UI). Its diff will temporarily include N's commits; that is expected.
3. Merge PR N into `main` (CI green, review done).
4. Verify `main` contains the work, from a clean fetch:
   - `git fetch origin`
   - `git merge-base --is-ancestor <tip-sha-of-branch-N> origin/main && echo OK` must print `OK` (exit code 0). The tip SHA is the one recorded in the PR before merging. If it fails, STOP: the work did not reach `main`.
   - Cheap extra check: `git diff --stat origin/main origin/<branch-N> -- backend` is empty.
5. Rebase the child onto the updated `main` if its diff still shows parent commits: `git rebase origin/main` (merge-commit strategy: clean fast replay), then `git push --force-with-lease`. Re-check that CI is green on the child before merging it.
6. After the last PR: `git merge-base --is-ancestor feat/quote-domain-catalog-api origin/main`, then on `main` run `uv run --project backend pytest backend/tests` (with `DATABASE_URL_TEST` set) and `ruff check` / `ruff format --check`. Then run `sdd-verify`.
7. Never delete a branch before step 4 passes for it.

## Commit boundaries

Conventional commits, one per work unit, tests in the same commit as the behavior they verify. NO `Co-Authored-By`, NO AI attribution. Each commit leaves the repo green (ruff + pytest).

| PR | Commit (in order) | Tasks |
| -- | ----------------- | ----- |
| A1 | `docs(sdd): add quote-domain-core artifacts and align specs with design` (if proposal/design/specs/tasks are not yet committed; orchestrator) | A1.1 |
| A1 | `test(backend): enforce stdlib-only domain and tighten layer rules` | A1.2 |
| A1 | `feat(domain): add money value object and domain errors` | A1.3 |
| A1 | `feat(domain): add equipment catalog entities` | A1.4 |
| A2 | `build(backend): add tzdata runtime dependency` | A2.1 |
| A2 | `feat(domain): add event request validation` | A2.2 |
| A2 | `feat(domain): add pricing rules with synthetic defaults` | A2.3 |
| A3 | `feat(domain): add quote types and calculate_price` | A3.1, A3.2 |
| A3 | `test(domain): pin quote contract with a golden snapshot` | A3.3 |
| A3b | `build(backend): add hypothesis dev dependency and test profiles` | A3b.1 |
| A3b | `test(domain): add pricing and money property tests` | A3b.2, A3b.3 |
| A4 | `feat(domain): add availability algorithm` | A4.1, A4.2 |
| A4 | `test(domain): add availability property tests with brute-force oracle` | A4.3 |
| B1 | `test(backend): move schema reset to conftest` | B1.1 |
| B1 | `feat(db): add catalog and booking schema with reversible migrations` | B1.2-B1.5 |
| B1 | `docs: record whole-peso money decision` | B1.6 |
| B2 | `feat(application): add catalog and booking ports` | B2.1 |
| B2 | `feat(db): add sqlalchemy catalog and booking repositories` | B2.2, B2.3 |
| B3a | `feat(db): add synthetic catalog seed data and idempotent upsert` | B3a.1, B3a.2 |
| B3b | `feat(cli): add guarded seed catalog command` | B3b.1, B3b.2 |
| C1 | `feat(application): add catalog, pricing and availability use cases` | C1.1 |
| C2 | `feat(api): add read-only catalog routes` | C2.1-C2.3 |
| C2 | `test(backend): forbid adapter imports in routes` | C2.4 |
| C2 | `docs: document availability design, ports and domain modules` (move to C3 if over budget) | C2.5 |

---

## PR A1: Money, catalog, architecture test (`feat/quote-domain-pricing`, base `main`, ~330 lines)

- [ ] **A1.1 [A]** Spec sync. Edit `openspec/changes/quote-domain-core/specs/{money,pricing,availability,catalog-persistence,synthetic-seed,catalog-api}/spec.md` to match the design (conflict table above). Docs only, excluded from the budget. Satisfies: consistency for sdd-verify. Test-first: none. If the developer prefers the specs to win on any row, STOP and ask before A1.2.
- [ ] **A1.2 [A]** Architecture test hardening (D18 items 1-3). Files: `backend/tests/unit/test_architecture.py`. Add `pydantic`, `starlette`, `psycopg` to `FRAMEWORKS`; add `FRAMEWORKS` and `eventssound.config` to `FORBIDDEN["application"]`; add `test_domain_imports_only_stdlib_and_itself` (allowlist: top-level name in `sys.stdlib_module_names`, or `eventssound.domain` incl. relative imports resolved by the existing scanner) plus scanner self-tests (`import numpy` in a tmp file flagged; `from datetime import datetime` and `from . import money` not flagged). Satisfies: catalog-persistence / Repository ports (dependency rule); design D18, domain stdlib-only rule. Test-first: the self-test and allowlist test are written first and fail (helper missing); then implement; confirm existing application code passes the tightened rule.
- [ ] **A1.3 [A]** `Money` and domain errors. Files: `backend/src/eventssound/domain/{errors,money}.py`, `backend/tests/unit/test_money.py`. `DomainError`, `InvalidMoney`, `CurrencyMismatch`, `InvalidRules`, `InvalidEventRequest`, `UnknownCatalogEntry`. `Money(amount:int, currency="COP")` frozen/slots; `type(amount) is int` (rejects bool/float); currency `^[A-Z]{3}$`; `__add__/__sub__/__neg__`, `__mul__/__rmul__` int only, `total_ordering` raising on mismatch, `zero()`, `sum()`, `percent(bps)` half-up `(2*amount*bps + 10_000)//20_000`, `round_to(step)` half-up `(2*amount+step)//(2*step)*step`, `step >= 1`. Satisfies: money / immutable integer value object, exact and currency-safe arithmetic, half-up rounding (D2, D3). Test-first: table-driven `parametrize(id=...)` first: construct, float and bool rejected, immutability, add/mul (3500, 3000), currency mismatch, rounding table 0,499,500,1499,1500,1999,2500 -> 0,0,1000,1000,2000,2000,3000, negative half-up behaviour, invalid step 0/-1, `percent` table. Hypothesis-based rounding properties land in A3b (dependency not yet added).
- [ ] **A1.4 [A]** Catalog entities. Files: `backend/src/eventssound/domain/catalog.py`, `backend/tests/unit/test_catalog.py`. `EquipmentCategory` (StrEnum: sound, lighting, dj, stage, effects, video), `EquipmentItem` (code `^[a-z0-9_]{3,64}$`, name non-empty, stock >= 0, price 0..1e9), `PackageLine`, `ServicePackage` (>= 1 line, unique item codes, `0 <= discount_bps <= 10000`), `Catalog` (duplicate codes and unknown package references rejected; `item(code)`, `package(code)` raise `UnknownCatalogEntry`), `ServicePackage.base_unit_price(catalog)`. Satisfies: pricing / Base price and quantity (inputs), synthetic-seed / Seed content (validation reuse); D4, section 4. Test-first: invalid code, negative stock, duplicate code, unknown reference, package price derivation, immutability.
- [ ] **A1.5 [A]** PR A1 verification (checklist below); measure lines; prepare PR description.

## PR A2: Event request, pricing rules, tzdata (`feat/quote-domain-rules`, base A1, ~340 lines)

- [ ] **A2.1 [A]** Add `tzdata>=2024.1` as a RUNTIME dependency: `backend/pyproject.toml`, `backend/uv.lock` (`uv add tzdata` from `backend/`; lockfile excluded from the budget). Satisfies: pricing / Rule set (IANA timezone `America/Bogota`); D6. Test-first: A2.3's default-rules test (`ZoneInfo("America/Bogota")`) is the red test on a machine without system tzdata (Windows); write it first, see it fail, then add the dependency.
- [ ] **A2.2 [A]** `EventRequest`. Files: `backend/src/eventssound/domain/event_request.py`, `backend/tests/unit/test_event_request.py`. `EventType`, `VenueType`, `RequestedLine`, `EventRequest` with bounds (tz-aware, `end > start`, duration <= 31 days, guests 1..100000, distance 0..5000, >= 1 line, quantities 1..10000, <= 100 lines), `normalized()` merging duplicate codes. Satisfies: pricing / pure function (Invalid request scenario), Base price (duplicate merge); availability / Half-open tz-aware intervals (naive rejected); D6 section 4. Test-first: parametrized invalid-request table (quantity 0, guests 0, negative distance, end <= start, naive datetime, no lines, over bounds), duplicate merge and order independence.
- [ ] **A2.3 [A]** `PricingRules`. Files: `backend/src/eventssound/domain/pricing_rules.py`, `backend/tests/unit/test_pricing_rules.py`. `GuestTier`, `DistanceBand`, `NightWindow`, `PricingRules` with `__post_init__` validation (InvalidRules), `default_pricing_rules()` version `synthetic-v1` (D5 table: tiers 1/101/301/601 at 0/10/25/40%, weekend 15%, night 22:00-06:00 20%, bands 20 km free / 60 km 3000 / beyond 4500, cap 20%, step 1000, holidays empty). Satisfies: pricing / Rule set is validated data, Guest tiers, Weekend multiplier, Distance tiers (data); decision 4 (weekends only); D5. Test-first: overlapping/unordered bands and tiers rejected, first tier must start at 1, decreasing surcharge rejected, equal night start/end rejected, step <= 0, default night window wraps midnight and zone is Bogota, swapping rounding step needs no code change.
- [ ] **A2.4 [A]** PR A2 verification and measurement.

## PR A3: calculate_price and golden tests (`feat/quote-domain-calculate-price`, base A2, ~260 lines) [cut applied: properties and hypothesis moved to A3b]

- [ ] **A3.1 [A]** Quote types. File: `backend/src/eventssound/domain/pricing.py` (`LineKind`, `QuoteLine`, `Quote`, `QUOTE_SCHEMA_VERSION = 1`, `Quote.to_dict()` JSON primitives only). Satisfies: pricing / Quote value object and explainable breakdown (D7). Test-first: `test_pricing.py` first asserts structure of the worked example and that `to_dict()` contains only int/str/None/list/dict.
- [ ] **A3.2 [A]** `calculate_price(request, catalog, rules) -> Quote` in the exact order of design section 5 (normalize/resolve, rental days by ceil(24h), item lines, package + discount lines with cap, equipment subtotal E, guest-size line, weekend/holiday line over touched local dates with end exclusive, night line incl. previous-evening window instance, marginal distance lines, raw total, single `ROUNDING` line). Files: `domain/pricing.py`, `backend/tests/unit/test_pricing.py`. Satisfies: pricing / pure deterministic function, Base price and quantity, Order of application, Guest tiers, Weekend multiplier, Night surcharge, Distance tiers, Quote reconciliation; D3, D5. Test-first, table-driven with `id=`: worked example (2 speakers 120000 + mixer 79900, 150 guests, Saturday 20:00-23:30 Bogota, 45 km: E 319900, guest 31990, weekend 47985, night 63980, distance 75000, raw 538855, total 539000, rounding +145); UTC-instant-on-Saturday-night (2026-10-11T03:00Z is Saturday local); weekday neutral; night boundaries (14-20 none, 16-22 none, 18-23 yes, 05-08 yes); tier boundaries (guests 100/101); distance 19/20/21 km; package discount and cap; duplicate merge; unknown code names the code; catalog/rules currency mismatch; rental days (22:00-03:00 is 1 day); inputs not mutated; rounding step swap.
- [ ] **A3.3 [A]** Contract snapshot. File: `backend/tests/unit/test_quote_contract.py` pinning the worked-example `to_dict()` and `schema_version == 1`. Satisfies: proposal Success criteria (oracle contract versioned by tests); D7. Test-first: write the golden dict from the design numbers first, red until A3.2 is complete (commit it after green).
- [ ] **A3.4 [A]** PR A3 verification and measurement (if > 400, STOP and ask).

## PR A3b: Pricing properties and Hypothesis (`feat/quote-domain-pricing-properties`, base A3, ~170 lines)

- [ ] **A3b.1 [A]** Add `hypothesis>=6.100` to the `dev` dependency group (`backend/pyproject.toml`, `backend/uv.lock`); register Hypothesis profiles in `backend/tests/conftest.py` (`ci`: `max_examples=100, deadline=None, derandomize=True` when `CI` is set; `dev`: `max_examples=50, deadline=None`). Satisfies: pricing / property-based invariants (reproducible in CI); D19. Test-first: A3b.2 imports hypothesis and fails until installed.
- [ ] **A3b.2 [A]** `backend/tests/strategies.py` (`unit_prices`, `odd_unit_prices`, `catalogs()`, `rule_sets()`, `bogota_datetimes`, `durations`, request builder with `st.data()`; D20) and `backend/tests/unit/test_pricing_properties.py`: determinism; shuffle and duplicate-split invariance; `total >= 0`; `total % step == 0`; `sum(lines) == total`; each non-rounding line reproducible from its fields; `abs(total - subtotal) <= step/2`; monotonic in quantity, distance, guests, end; weekend/night never decrease; unrelated item never decreases; discount <= package amount; all amounts `type(v) is int`; neutral rules yield sum of `unit_price * quantity`. Satisfies: pricing / Pricing property-based invariants. Test-first: properties are the tests; if one fails, fix the domain in this PR and note it.
- [ ] **A3b.3 [A]** `backend/tests/unit/test_money_properties.py`: rounding multiple-of-step, `|result - x| <= s/2`, idempotence, monotonic. Satisfies: money / Rounding invariants (property). Test-first: as above.
- [ ] **A3b.4 [A]** PR A3b verification and measurement.

## PR A4: Availability (`feat/quote-domain-availability`, base A3b, ~270 lines)

- [ ] **A4.1 [A]** Types and algorithm. File: `backend/src/eventssound/domain/availability.py`: `BookingStatus` (+ `blocking()`), `Reservation`, `AvailabilityRules` + `default_availability_rules()` (2 h, whole minutes), `Availability`, `Shortage`, `AvailabilityReport`, `available_units` (buffer/2 expansion, sweep, releases before acquisitions at equal timestamps), `check_availability(..., quantity=1)`, `required_units`, `check_request_availability`. Satisfies: availability / Half-open tz-aware intervals, Stock consumed by overlapping bookings, Buffer, Multi-day, Package availability; decision 2; D8. Test-first (`backend/tests/unit/test_availability.py`, table-driven, `id=`): back-to-back with buffer 0 (available), gap exactly buffer (available), buffer minus 1 minute (unavailable), default buffer back-to-back (unavailable), overlap, contained, containing, multi-day clear and overlapping, same-day turnaround (14:00 ok, 13:00 not), stock 1 vs 3 with partial overlap, two sequential reservations inside one long request (peak 1), other item ignored, quantity above stock, zero stock, naive datetime and quantity <= 0 rejected, equivalent instants in different offsets, package components consume stock, shared member aggregation (4 needed, 3 in stock), limiting items reported.
- [ ] **A4.2 [A]** Cancelled bookings are excluded at the repository (B2); the domain `Reservation` carries no status. Record this in the PR description. Test-first: none (documentation task).
- [ ] **A4.3 [A]** `backend/tests/unit/test_availability_properties.py` plus availability strategies in `backend/tests/strategies.py` (30-minute grid): agreement with an independent brute-force slot-count oracle; adding a reservation never increases available units; more stock never decreases them; larger buffer never turns unavailable into available; reservations farther than the buffer are irrelevant; order invariance; shift invariance; request above stock never available; remaining never exceeds stock. Satisfies: availability / Property-based invariants. Test-first: oracle first, then run against A4.1 (fix algorithm here if it fails).
- [ ] **A4.4 [A]** PR A4 verification and measurement.

## PR B1: Schema, migrations, DB fixtures (`feat/quote-domain-schema`, base A4, ~370 lines)

- [ ] **B1.1 [A]** Move schema reset to conftest. Files: `backend/tests/conftest.py` (`reset_schema(url)`: import models if present, `Base.metadata.drop_all`, `DROP TABLE IF EXISTS alembic_version`; NOT `DROP SCHEMA public CASCADE`), `backend/tests/integration/test_migrations.py` (use it). Satisfies: catalog-persistence / DB test policy; D19. Test-first: existing P0 migration tests must stay green (run with `DATABASE_URL_TEST`) before and after; refactor-only commit.
- [ ] **B1.2 [A]** Tests first for the schema: `backend/tests/integration/test_catalog_schema.py` (DB): upgrade head creates exactly the five tables; downgrade to `0002`, to `0001`, to base leaves the expected sets; upgrade/downgrade/upgrade round trip; repeat upgrade is a no-op; named constraints exist (`uq_equipment_items_code`, `ck_equipment_items_stock_nonnegative`, `fk_package_items_equipment_item_id_equipment_items`); integrity errors for negative stock, `ends_at <= starts_at`, duplicate code, package item quantity 0; tables empty after migration; tz-aware round trip of a UTC-5 booking; drift test with `alembic.autogenerate.compare_metadata` (empty diff vs `Base.metadata`); one head test (DB-free). New fixtures in `tests/conftest.py`: `migrated_database` (re-runs `upgrade head` when `equipment_items` is absent), `session_factory` (`TRUNCATE ... RESTART IDENTITY CASCADE` on the five tables). Satisfies: catalog-persistence / Schema, Reversible migrations, DB test policy; D10, D11, D19. Test-first: red because models/migrations do not exist.
- [ ] **B1.3 [A]** `backend/src/eventssound/adapters/db/models.py`: five models on `Base` per the D10 table (BIGINT `*_cop`, `*_bps`, `DateTime(timezone=True)`, named `CheckConstraint`s, `category`/`status` as VARCHAR + CHECK, FKs with CASCADE/RESTRICT, indexes), `ServicePackageModel.lines` relationship. Satisfies: catalog-persistence / Schema; database-conventions.
- [ ] **B1.4 [A]** `backend/migrations/versions/0002_catalog_tables.py` (`equipment_items`, `service_packages`, `package_items`) and `0003_booking_tables.py` (`bookings`, `booking_items`): draft with `alembic revision --autogenerate`, then hand-edit (explicit constraint names, literal category/status strings, working `downgrade()` in FK order, schema only, no seed). Satisfies: catalog-persistence / Reversible migrations (no data in migrations).
- [ ] **B1.5 [A]** `backend/migrations/env.py`: add `import eventssound.adapters.db.models  # noqa: F401` so `Base.metadata` is populated (otherwise autogenerate proposes dropping tables). Satisfies: D11. Covered by the drift test in B1.2.
- [ ] **B1.6 [A]** Docs. `documentacion/decisions.md`: ADR 12 "Money is whole COP pesos" (BIGINT `*_cop`, rounding to 1000 half-up, why not cents). `.claude/skills/database-conventions/SKILL.md`, under "Naming", ONE line: "Money: `*_cents` is the generic example; COP has no practical minor unit, so this project stores whole pesos in `*_cop` BIGINT columns (ADR 12). Never float." Satisfies: proposal Decision 1; D12 docs. Test-first: none (docs).
- [ ] **B1.7 [A]** PR B1 verification, including migration round trip and drift test against a throwaway local Postgres; measurement (near budget: if > 400 move B1.6 docs to a trailing docs commit in B2).
- [ ] **B1.8 [M]** Note for the developer: merging B1 makes `start.sh` run `alembic upgrade head` on the next deploy and creates EMPTY tables in Neon (harmless, schema only). Confirm acceptance before merging.

## PR B2: Ports, repositories, fakes (`feat/quote-domain-repositories`, base B1, ~320 lines)

- [ ] **B2.1 [A]** `backend/src/eventssound/application/{ports.py (add CatalogRepository, BookingRepository), errors.py (RepositoryUnavailable)}`. `get_catalog() -> Catalog`; `find_reservations(item_codes, window_start, window_end) -> Sequence[Reservation]`. Satisfies: catalog-persistence / Repository ports in the application layer; availability / use case and port; D12. Test-first: `backend/tests/fakes.py` first (`InMemoryCatalogRepository`, `InMemoryBookingRepository` filtering by window, `BrokenCatalogRepository`) with a small unit test that the fakes satisfy the Protocols and filter windows; architecture test must stay green.
- [ ] **B2.2 [A]** `backend/src/eventssound/adapters/db/catalog_repository.py` (`SqlAlchemyCatalogRepository`: two selects ordered by `code`, `selectinload`, private `_to_domain`, `SQLAlchemyError` -> `RepositoryUnavailable` via `raise ... from None`) and `backend/tests/integration/test_catalog_repository.py` (DB): round trip with integer `Money`, package members with quantities, ordering, empty catalog, bad category row raises a domain error, DB failure maps to `RepositoryUnavailable` with no URL/host in the message. Satisfies: catalog-persistence / SQLAlchemy adapters (Round trip). Test-first: tests written first, red.
- [ ] **B2.3 [A]** `backend/src/eventssound/adapters/db/booking_repository.py` (`SqlAlchemyBookingRepository`, D9 query, `status IN blocking()`, read-only) and `backend/tests/integration/test_booking_repository.py` (DB): inside/outside window, cancelled excluded, pending and confirmed included, unknown codes yield nothing, half-open window edges. Satisfies: catalog-persistence / Bookings by interval; availability / cancelled ignored (repository side); D9. Test-first: red first.
- [ ] **B2.4 [A]** PR B2 verification and measurement.

## PR B3a: Seed data and idempotent upsert (`feat/quote-domain-seed-data`, base B2, ~280 lines)

- [ ] **B3a.1 [A]** `backend/src/eventssound/adapters/db/seed_data.py` (`SEED_ITEMS` 30, `SEED_PACKAGES` 5, helper `_item(...)`, Spanish names, English codes, prices multiples of 1000, stock 1-24, at least one item with stock > 1, packages with 4-8 lines and `discount_bps` 500-1500) and `backend/tests/unit/test_seed_data.py` (no DB): `Catalog(SEED_ITEMS, SEED_PACKAGES)` builds, counts 30/5, slug regex, all categories covered, prices multiples of 1000, `calculate_price` on each package with default rules returns a positive `Quote`. Satisfies: synthetic-seed / Seed content (Counts and shape, Pricing works on the seed); decision 3. Test-first: test written first, red.
- [ ] **B3a.2 [A]** `backend/src/eventssound/adapters/db/seed.py` (`seed_catalog(session_factory, items, packages) -> SeedResult`; one transaction, explicit commit, rollback on error; `ON CONFLICT (code) DO UPDATE` for items and packages via `sqlalchemy.dialects.postgresql.insert`; upsert `package_items` on (`package_id`, `equipment_item_id`); delete only the package's stale `package_items`; never delete other rows, never touch bookings) and `backend/tests/integration/test_seed.py` (DB): two runs give 30/5 with identical content, drifted price restored, edited package converges, extra hand-made row survives, bookings untouched. Satisfies: synthetic-seed / Idempotency (Run twice, Drifted row restored); D13. Test-first: red first.
- [ ] **B3a.3 [A]** PR B3a verification and measurement.

## PR B3b: Seed CLI and guard (`feat/quote-domain-seed-cli`, base B3a, ~150 lines)

- [ ] **B3b.1 [A]** Tests first: `backend/tests/unit/test_seed_guard.py` (no DB, no network): without `--confirm` prints the dry-run line, exits 2, never builds an engine or session; local hosts `localhost`, `127.0.0.1`, `::1`, `db`, and no-host (socket) proceed; non-local host refused (exit 3) unless the environment mapping has `ALLOW_REMOTE_SEED == "1"`; `"true"`, `"0"`, `""` still refuse; `APP_ENV=production` also requires `"1"`; the check runs before any connection; stdout/stderr/exception text never contain the URL, host, user or password (assert with a URL containing a sentinel host and password). Satisfies: synthetic-seed / Explicit confirmation, Remote host guard, No secret leakage; D14.
- [ ] **B3b.2 [A]** `backend/src/eventssound/entrypoints/cli/{__init__.py,seed_catalog.py}`: `main(argv, settings=None, session_factory=None, environ=None) -> int` (injectable; `environ` defaults to `os.environ`), host classification via `sqlalchemy.engine.make_url(url).host`, `python -m eventssound.entrypoints.cli.seed_catalog --confirm`. **`ALLOW_REMOTE_SEED` is read ONLY here via `os.environ` (injected as `environ` in tests). It is NOT added to `Settings`, so `config.py` and `.env.example` do not change** and `test_env_example.py` stays green. Document this deliberate bend of the "no `os.environ` outside Settings" coding rule in the module docstring and PR description. Do not open `.env*`. Satisfies: synthetic-seed / Remote host guard; proposal Risks (seed on production Neon).
- [ ] **B3b.3 [M]** Contingency only: if any task would still force an edit to `.env.example` or any `.env*` path (the developer's permission rules deny agent writes there), the agent STOPS and the developer applies the edit by hand. Expected: no such edit is needed in this change. Do NOT add an `ALLOW_REMOTE_SEED` line to `.env.example` unless `test_env_example.py` is first confirmed to tolerate keys that are not `Settings` fields (assumption U3).
- [ ] **B3b.4 [A]** PR B3b verification: `git diff --name-only <base>...HEAD | rg "^\.env"` returns nothing; `git diff <base>...HEAD -- backend/src/eventssound/config.py` is empty; measurement.

## PR C1: Use cases (`feat/quote-domain-use-cases`, base B3b, ~220 lines)

- [ ] **C1.1 [A]** `backend/src/eventssound/application/{catalog,pricing,availability}.py` (`list_catalog`, `price_quote`, `check_event_availability` as plain functions taking ports; availability queries reservations for `required_units` codes in `[start - buffer, end + buffer)`) and `backend/tests/unit/test_use_cases.py` with `tests/fakes.py`: `price_quote` equals `calculate_price` on the fake catalog; availability use case equals the pure function over the fake's reservations (spec scenario "Use case with fake repository"); package components and shared aggregation through the use case; `BrokenCatalogRepository` propagates `RepositoryUnavailable`. Satisfies: availability / Availability use case and port; catalog-persistence / Repository ports; D2, D12. Neither use case is exposed over HTTP (decision 5). Test-first: tests first, red.
- [ ] **C1.2 [A]** PR C1 verification and measurement.

## PR C2: Catalog API and docs (`feat/quote-domain-catalog-api`, base C1, ~380 lines)

- [ ] **C2.1 [A]** Tests first: `backend/tests/integration/test_catalog_api.py` (no DB, `create_app(catalog_repository=fake)` via TestClient): items and packages ordered by `code`, empty catalog returns `{"items": []}` / `{"packages": []}`, no `id`/`*_id`/timestamp keys, `base_price_cop` derived, POST/PUT/PATCH/DELETE give 405, `GET /catalog/availability` gives 404, broken repository gives 503 `{"detail": "catalog_unavailable"}` with no host/SQL/driver text, OpenAPI lists both routes with no write operations outside production and `/docs` and `/openapi.json` are 404 in production. Satisfies: catalog-api / List items, List packages, Read-only and public surface, Wiring and error behavior, OpenAPI exposure; D15, D16.
- [ ] **C2.2 [A]** `backend/src/eventssound/entrypoints/api/{schemas.py,routes/catalog.py}`: frozen Pydantic v2 `CatalogItemOut`, `PackageLineOut`, `ServicePackageOut`, `ItemsResponse`, `PackagesResponse` with `from_domain`; sync `def` routes reading `request.app.state.catalog_repository`; map `RepositoryUnavailable` to 503. No pagination (D16). Satisfies: catalog-api requirements above.
- [ ] **C2.3 [A]** `container.py` (`make_catalog_repository`, `make_booking_repository`, `make_pricing_rules`, `make_availability_rules`) and `app.py` (optional `catalog_repository` and `booking_repository` overrides, rules stored on `app.state`, router included; CORS unchanged). Add `backend/tests/integration/test_catalog_api_db.py` (DB): seeded database through the real wiring returns 30 items and 5 packages with integer prices. Satisfies: catalog-api / Wiring; D17; Success criteria "GET /catalog/* returns the seed".
- [ ] **C2.4 [A]** Architecture test (D18 item 4): no module under `entrypoints/api/routes/` imports `eventssound.adapters`, with a scanner self-test. File: `backend/tests/unit/test_architecture.py`. Test-first: red against a synthetic offending module, green on the real routes.
- [ ] **C2.5 [A]** Docs: `documentacion/decisions.md` ADR 13 "Availability computed in the domain" (D8/D9 summary); `documentacion/architecture.md` (domain modules, the two ports, links to this change); `.claude/skills/design-patterns/SKILL.md` one line replacing the planned `EquipmentRepository` with `CatalogRepository` / `BookingRepository`; document `ALLOW_REMOTE_SEED` usage (exact value `1`, CLI only) in `documentacion/` (not in `.env.example`). If the PR measures over 400, move C2.5 to a separate PR `feat/quote-domain-docs` (C3, base C2, `docs:` only).
- [ ] **C2.6 [A]** PR C2 verification and measurement.

---

## Verification checklists

Common to EVERY PR (run from `backend/` unless noted; DB variables point to a throwaway local container on `127.0.0.1`, NEVER Neon):
- [ ] `uv run ruff check .` and `uv run ruff format --check .` clean
- [ ] `uv run pytest` green WITHOUT `DATABASE_URL_TEST`: DB tests reported as skipped, unit tests run
- [ ] `uv run pytest` green WITH `DATABASE_URL_TEST` set to the local container
- [ ] DB tests FAIL (not skip) when `DATABASE_URL_TEST` is set but unreachable (spot-check once with a wrong port, in the PRs that add DB tests: B1, B2, B3a, C2)
- [ ] From the repo root: `uv run --project backend pytest backend/tests` green (the `openspec/config.yaml` command)
- [ ] Architecture test (`backend/tests/unit/test_architecture.py`) green, including the stdlib-only domain allowlist
- [ ] Every new test was seen red before its implementation (strict TDD); tests live in the same commit as the behavior
- [ ] No `.env*`, secrets or real connection strings in the diff; `git diff --name-only <base>...HEAD | rg "^\.env"` empty
- [ ] Diff under ~400 lines excluding `uv.lock` and `openspec/`
- [ ] No `Co-Authored-By` or AI attribution in any commit (`git log <base>..HEAD --format=%B | rg -i "co-authored|claude"` empty)
- [ ] PR description states start, end, dependencies, follow-up, out-of-scope, chain diagram; base branch is correct

Per-PR additions:
- [ ] **A1** stdlib allowlist test fails when a `domain` file imports `numpy`/`pydantic` (self-test) and passes on the real domain; money rounding table matches the spec table
- [ ] **A2** `uv lock` updated, `tzdata` is under runtime dependencies (not dev); default rules build under `ZoneInfo("America/Bogota")` on Windows and in CI
- [ ] **A3** worked example gives 539,000 with a `+145` rounding line; golden snapshot test passes; `sum(line.amount) == total`
- [ ] **A3b** `hypothesis` is under the dev group only; `CI=1 uv run pytest` uses the derandomized profile and is reproducible
- [ ] **A4** property suite agrees with the brute-force oracle; back-to-back, overlap, multi-day, buffer, stock > 1 cases pass
- [ ] **B1** migration round trip: `alembic upgrade head`, repeat upgrade (no-op), `downgrade base` leaves no application tables, `alembic heads` single head, drift test empty; migrations contain no `INSERT`; `migrations/env.py` imports the models module
- [ ] **B2** repositories raise `RepositoryUnavailable` with a generic message (no URL/host/SQL); cancelled bookings excluded
- [ ] **B3a** seed run twice: 30 items and 5 packages, no duplicates, identical content; seed data validated without a DB
- [ ] **B3b** dry run exits 2 with no connection; remote host refused without `ALLOW_REMOTE_SEED=1`; output never contains URL, host or credentials; `Settings` and `.env.example` untouched
- [ ] **C1** use cases run entirely on fakes; no SQLAlchemy/FastAPI imports in `application/`
- [ ] **C2** `GET /catalog/items` and `/catalog/packages` return the seed through the real wiring; `/catalog/availability` is 404; write methods 405; production has no `/docs` or `/openapi.json`

## Dependency summary

| Task group | Parallel with | Sequential after |
| ---------- | ------------- | ---------------- |
| A1-A4 | none (strict chain) | previous PR opened; merges follow the MERGE PROCEDURE |
| B1-B3b | none | A4 (chain order); B3b after B3a |
| C1-C2 | none | B3b |
| Merge actions (retarget, merge, ancestry check) | n/a | After CI green and review of each PR |

Parallelism note: coding can run ahead of merges (branch N+1 is cut from branch N's tip), but only one writer thread at a time; rebases after each merge are the bottleneck. Realistic cadence is about 2 PRs per day to fit the 2026-10-25 deadline; each merge costs a retarget, a merge, an ancestry check and a CI re-run on the child.

Developer manual actions (summary): GitHub "delete head branches" setting and merge-commit strategy (procedure step 0), every retarget/merge/push (procedure), B1.8 Neon empty-tables acknowledgement, B3b.3 contingency for any `.env*` edit, decision on spec-vs-design rows if any should be reversed (A1.1).

## Unverified assumptions to check during apply

| # | Assumption | Check at | Fallback |
| - | ---------- | -------- | -------- |
| U1 | The repo allows the "Create a merge commit" strategy; with squash/rebase merges the `merge-base --is-ancestor` check cannot work | Procedure step 0 | With squash: verify with `git diff --stat origin/main <branch-tip>` empty for the PR's files, and rebase each child with `git rebase --onto origin/main <old-parent-tip> <child>` |
| U2 | GitHub "automatically delete head branches" retargets child PRs; it is still safer to retarget manually first | Procedure step 0 and 2 | Manual retarget always |
| U3 | `test_env_example.py` fails if `.env.example` has keys that are not `Settings` fields (or only checks the reverse direction) | B3b.3 (read the test, not `.env*`) | Leave `.env.example` untouched (default plan) |
| U4 | `test_architecture.py` has no rule forbidding `os.environ` in `entrypoints/`; the coding skill rule is convention only | B3b.2 | Allow-list the CLI module in the test with a comment, or move the read into a tiny `entrypoints/cli/env.py` helper |
| U5 | The next ADR number in `documentacion/decisions.md` is 12 (then 13) | B1.6, C2.5 | Use the next free numbers and update the cross references |
| U6 | The throwaway local Postgres (`pgvector/pgvector:pg16` on 127.0.0.1) is available for `DATABASE_URL_TEST` | Before B1 | CI is the authority for DB tests; DB tasks cannot be verified locally |
| U7 | `uv add tzdata` / `uv add --dev hypothesis` work behind the corporate proxy/TLS interception | A2.1, A3b.1 | Ask the developer to run them; lockfile excluded from the budget |
| U8 | `compare_metadata` drift test is stable across Postgres versions (server defaults, CHECK text) | B1.2 | Compare table/column/constraint names only, not defaults |
| U9 | A3, A3b, B3a, B3b, C2 estimates hold; B1 and C2 are the likely overruns | Each PR measurement step | Move docs to a trailing commit/PR; ask before exceeding 400 |
| U10 | Developer accepts the design over the specs in the conflict table (including five tables, wrapped API objects, additive percentages) | A1.1 | Stop and ask; reversible before any consumer exists, but the `Quote` shape becomes the P3 oracle contract |
| U11 | Hypothesis `derandomize=True` in CI is enough for reproducibility and does not hide failures | A3b.1 | Keep a `dev` profile with random seeds locally |
