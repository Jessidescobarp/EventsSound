# Tasks: quote-domain-core (P1 Domain core)

Replanned 2026-10-12 after PR A1 measured 649 changed lines against a 330 estimate. Supersedes the 11-PR plan of 2026-10-10.

Inputs: `proposal.md` (Decisions + Scope cuts), `design.md` (D1-D20; read the pointer note at its top), `specs/*/spec.md`, `openspec/config.yaml`, `AGENTS.md`, skills `coding-best-practices`, `architecture-hexagonal`, `database-conventions`.

Legend:
- **[A]** agent-executable (sdd-apply).
- **[M]** manual action by the developer (GitHub settings, merges, retargeting, pushes, anything touching `.env*`). The agent stops and asks.
- **TDD**: strict TDD is ON. Every code task writes the failing test first, runs it red, then implements to green.
- Spec refs use `capability / Requirement name`. Design refs use `Dn` or section numbers.

## Scope cuts and decisions (2026-10-12)

Why: A1 was estimated at 330 lines and measured 649; tests were about 62% of the diff, so earlier estimates under-counted tests by about 2x. With the MVP deadline on 2026-10-25 and P2 (agent), P3 (evals), P4 (full UI), slides and video still ahead, the developer's review time is the bottleneck. A1 is ACCEPTED as-is (~650 lines). The developer approved:

| # | Cut / decision | Replaces | Why |
| - | -------------- | -------- | --- |
| 1 | No Hypothesis, no `hypothesis` dependency, no A3b PR. Pricing uses table-driven tests plus a few hand-written invariants (monotonic in quantity, non-negative totals, rounding idempotence) | A3b, D19, D20 | Biggest single saver (~170 lines plus strategies) and no CI-time or dependency cost |
| 2 | No brute-force oracle property test for availability. Table-driven boundary cases (back-to-back, buffer edges, multi-day, same-day, zero stock, package availability) | A4.3 | Explicit cases are cheaper to review and still pin the contract |
| 3 | Flat `bookings` table: one row per equipment item per booking (booking code, item code, quantity, start, end, status). NO `booking_items` | D10 | Four tables, one migration, simpler repository query |
| 4 | Seed: 20 catalog items and 4 packages, extendable by editing a data module | 30 / 5 (Decision 3) | Less data to review; same behavior |
| 5 | Seed CLI keeps `--confirm` and the non-local host refusal unless `ALLOW_REMOTE_SEED=1`, read only via `os.environ` in the script (NOT in `Settings`). No other options | D14 extras | Safety kept, surface cut |
| 6 | Use-cases layer (old C1) merged into the API PR | C1 | A 150-line PR is not worth a merge cycle |
| 7 | Per-PR docs commits folded into the last PR of each block | B1.6, C2.5 | Fewer commits and no docs-only PRs |
| 9 | `Quote` versioning is a single `version` field (int, 1); no separate schema-version constant or contract-versioning ceremony | A3.1, A3.3, D7 | Less ceremony; the golden test still pins the shape |

KEPT: night surcharge, guest tiers, weekend multiplier, distance tiers, package discount, explicit `ROUNDING` line, additive percentages in basis points, integer COP pesos with half-up rounding to the nearest 1000 once, 2-hour availability buffer as rule data, `tzdata` dependency, reversible migrations, read-only catalog API.

Extra requirements from the developer:
- (a) Swagger UI (`/docs`) and `/openapi.json` are PUBLIC in production too. Supersedes D15/D17 and the catalog-api spec statement that OpenAPI is disabled in production (spec already updated). ReDoc stays off. The schema must be presentable to a business owner (tags, summaries, response models, examples). Done in PR C.
- (b) FRONTEND scope is NOT reduced. P4 stays fully in scope in its own change: chat page, proposal view, static pages, minimal JWT login and admin quotes list. The old "drop auth/admin" fallback is WITHDRAWN. Nothing in this change touches `frontend/`.

Spec/design conflicts resolved earlier in favor of the design (A1.1, done) still hold, except rows changed by the cuts above: five tables becomes four (flat `bookings`), `Quote` has `version` only, seed counts are 20/4, and OpenAPI is public in production.

## Review Workload Forecast

LESSON applied: estimates below INCLUDE tests and use the measured A1 ratio (tests ~55-60% of each PR). A1 real: 649 lines. Each PR aims at <= ~450 real lines (lockfiles and `openspec/` excluded).

| Metric | Value |
| ------ | ----- |
| Estimated changed lines, remaining chain (excl. lockfiles, `openspec/`) | ~2,600 (A2..C) plus 649 already in A1 = ~3,250 for the change |
| Gap vs the ~1,800 target | The 1,800 target is NOT reachable with the approved cuts and calibrated tests. Each block (rules, pricing, availability, schema, repositories, seed, API) costs 300-450 lines once tests are counted. Reaching ~1,800 needs more cuts (see "Further cut options") |
| Chained PRs recommended | Yes (7 PRs after A1: each reviewable on its own) |
| 400-line budget risk | Medium-High for A3, B3 and C (estimates 380-450). Cut lines are listed per PR |
| Decision needed before apply | No for A2-B2. For C, the developer should confirm the cut line if C measures over 450 |
| Delivery strategy | `ask-on-risk`: STOP and ask when a PR measures over 450 |

| PR | Branch | Base | Est. lines (incl. tests) | Cumulative (after A1 649) | <= 450? | Merge order |
| -- | ------ | ---- | ------------------------ | ------------------------- | ------- | ----------- |
| A1 Architecture test, errors, Money, catalog (DONE) | `feat/quote-domain-pricing` | `main` | 649 (measured) | 649 | No (accepted by developer) | 1 |
| A2 EventRequest + PricingRules + tzdata | `feat/quote-domain-rules` | A1 | ~330 | 979 | Yes | 2 |
| A3 calculate_price + Quote + golden + invariants | `feat/quote-domain-calculate-price` | A2 | ~430 | 1,409 | Yes (near) | 3 |
| A4 Availability | `feat/quote-domain-availability` | A3 | ~290 | 1,699 | Yes | 4 |
| B1 Schema + one migration + DB fixtures + flat bookings | `feat/quote-domain-schema` | A4 | ~360 | 2,059 | Yes | 5 |
| B2 Ports + repositories + fakes | `feat/quote-domain-repositories` | B1 | ~380 | 2,439 | Yes | 6 |
| B3 Seed data 20/4 + upsert + guarded CLI | `feat/quote-domain-seed` | B2 | ~380 | 2,819 | Yes | 7 |
| C Use cases + catalog API + public Swagger + docs | `feat/quote-domain-catalog-api` | B3 | ~450 | 3,269 | Borderline | 8 |

Remaining after A1: ~2,620 lines in 7 PRs (average ~375).

Why B2 and B3 are split instead of one B2 (suggested chain): ports + repositories + fakes (~380) plus seed data + upsert + CLI (~380) in a single PR would be ~760 real lines, far above any reviewable size. Why A3 and A4 are not merged: ~720 lines.

Likely overruns and cut lines:
- **A3 (~430)**: pricing has the most rule combinations. Cut line: move the hand-written invariants (A3.3) to the start of A4 as a commit; the golden snapshot stays.
- **B3 (~380)**: seed data module for 20/4 is data-heavy (~110 lines). Cut line: keep 4 packages and reduce to 16 items only with developer consent (the 20/4 number is a developer decision).
- **C (~450)**: five concerns in one PR (use cases, routes/schemas with examples, wiring, public Swagger, docs). Cut line, in order: (1) docs commit (README/deploy/architecture/ADR 13) becomes `feat/quote-domain-docs` (C2, `docs:` only, ~60 lines); (2) OpenAPI examples reduced to the minimum (one example per response model); (3) the DB-backed API test (C.5) stays, it is the only end-to-end proof.

Further cut options if the developer wants to approach ~1,800 (NOT applied; each needs an explicit decision): drop the `compare_metadata` drift test (~-40); drop seed update-path tests, keep the idempotence test (~-50); drop `GET /catalog/packages` (not recommended: the agent needs packages) (~-90); defer the cancelled/pending repository tests (~-40); drop the DB-backed API test (~-40).

Measure each PR with: `git diff --shortstat <base-branch>...HEAD -- . ':!backend/uv.lock' ':!openspec'` (run by the agent before opening the PR; if a PR measures over 450, STOP and ask before proceeding).

Dependencies: strictly linear chain A1 -> A2 -> A3 -> A4 -> B1 -> B2 -> B3 -> C. Real dependencies are weaker (B1 needs no domain code), but one chain keeps one merge order and one rebase path.

Each PR description states: start, end, dependencies, follow-up, out-of-scope, and a dependency diagram marking the current PR:

```
A1 -> A2 -> A3 -> A4 -> B1 -> B2 -> B3 -> C
```

Roadmap note: after this change comes P2 (AI agent), P3 (evals), P4 (full UI, fully in scope: chat page, proposal view, static pages, minimal JWT login, admin quotes list), then slides and video. The "drop auth/admin" fallback is withdrawn. If time pressure appears, the lever is the number of catalog/pricing refinements and the P3 golden-set size, NOT the P4 scope.

## Merge order and MERGE PROCEDURE (avoids the earlier mistake)

Earlier incident: a stacked PR was merged into its parent branch instead of `main`, so the work never reached `main` (AGENTS.md, Conventions). For this chain, follow this for EVERY merge. All steps are [M] (developer) except the verification commands, which the agent can run when asked.

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

## Special rules (apply in the PR named)

1. **ALLOW_REMOTE_SEED (B3)**: read ONLY in the seed CLI via `os.environ` (injected as `environ` in tests), exact value `"1"`. NOT a `Settings` field; `config.py` and `.env.example` unchanged. Document the deliberate bend of "no `os.environ` outside Settings" in the module docstring and PR description.
2. **tzdata (A2)**: runtime dependency (not dev). On Windows there is no system tzdata, so `ZoneInfo("America/Bogota")` fails without it.
3. **Stdlib-only domain (all PRs touching `domain/`)**: the allowlist test from A1 must stay green; no third-party import in `domain/`.
4. **conftest reset and models import (B1)**: schema reset lives in `tests/conftest.py` (`reset_schema(url)`: import models, `Base.metadata.drop_all`, `DROP TABLE IF EXISTS alembic_version`; NOT `DROP SCHEMA public CASCADE`); `migrations/env.py` imports `eventssound.adapters.db.models  # noqa: F401`.
5. **COP vs cents note (B1)**: ONE line in `.claude/skills/database-conventions/SKILL.md` under "Naming": "Money: `*_cents` is the generic example; COP has no practical minor unit, so this project stores whole pesos in `*_cop` BIGINT columns (ADR 12). Never float." Plus ADR 12 in `documentacion/decisions.md`.

## Commit boundaries

Conventional commits, one per work unit, tests in the same commit as the behavior they verify. NO `Co-Authored-By`, NO AI attribution. Each commit leaves the repo green (ruff + pytest). Docs ride in the last commit of the last PR of each block (cut 7).

| PR | Commit (in order) | Tasks |
| -- | ----------------- | ----- |
| A1 | DONE: commits `cae8daa..` (spec sync, architecture test, money + errors, catalog entities) | A1.1-A1.4 |
| A2 | `build(backend): add tzdata runtime dependency` | A2.1 |
| A2 | `feat(domain): add event request validation` | A2.2 |
| A2 | `feat(domain): add pricing rules with synthetic defaults` | A2.3 |
| A3 | `feat(domain): add quote types and calculate_price` | A3.1, A3.2 |
| A3 | `test(domain): pin quote contract and pricing invariants` | A3.3 |
| A4 | `feat(domain): add availability algorithm` | A4.1, A4.2 |
| B1 | `test(backend): move schema reset to conftest` | B1.1 |
| B1 | `feat(db): add catalog and flat bookings schema with reversible migration` | B1.2-B1.4 |
| B1 | `docs: record whole-peso money decision` (ADR 12 + skill line) | B1.5 |
| B2 | `feat(application): add catalog and booking ports with fakes` | B2.1 |
| B2 | `feat(db): add sqlalchemy catalog and booking repositories` | B2.2, B2.3 |
| B3 | `feat(db): add synthetic seed data and idempotent upsert` | B3.1, B3.2 |
| B3 | `feat(cli): add guarded seed catalog command` | B3.3, B3.4 |
| C | `feat(application): add catalog, pricing and availability use cases` | C.1 |
| C | `feat(api): add read-only catalog routes with public OpenAPI` | C.2-C.5 |
| C | `test(backend): forbid adapter imports in routes` | C.6 |
| C | `docs: document public swagger, availability design and seed guard` | C.7 |

---

## PR A1: Architecture test, errors, Money, catalog (`feat/quote-domain-pricing`, base `main`) - DONE, PR NOT YET OPENED

Real size: **649 changed lines** (estimate was 330; tests ~62%). Accepted by the developer as-is. Commits start at `cae8daa`.

- [x] **A1.1 [A]** Spec sync to the design (docs only).
- [x] **A1.2 [A]** Architecture test hardening: stdlib-only domain allowlist, tightened `FRAMEWORKS`/`FORBIDDEN["application"]`, scanner self-tests.
- [x] **A1.3 [A]** `Money` and domain errors, table-driven tests (half-up rounding table, `percent(bps)`).
- [x] **A1.4 [A]** Catalog entities (`EquipmentCategory`, `EquipmentItem`, `PackageLine`, `ServicePackage`, `Catalog`).
- [ ] **A1.5 [A]** Run a FRESH-CONTEXT review of the A1 diff (orchestrator rule: fresh review before PR), fix findings, rerun the common checklist, record the tip SHA, prepare the PR description (state real size 649 and why), and open the PR with base `main`. PENDING.
- [ ] **A1.6 [M]** Developer reviews and merges A1 following the MERGE PROCEDURE once A2 is open.

## PR A2: EventRequest, PricingRules, tzdata (`feat/quote-domain-rules`, base A1, ~330 lines)

- [ ] **A2.0 [M]** One-time: enable "Automatically delete head branches" in GitHub settings and confirm the merge-commit strategy (procedure step 0). Before A1 merges.
- [x] **A2.1 [A]** Add `tzdata>=2024.1` as a RUNTIME dependency (`backend/pyproject.toml`, `backend/uv.lock`; `uv add tzdata` from `backend/`; lockfile excluded). Satisfies: pricing / Rule set (IANA zone); D6. Test-first: A2.3's default-rules test (`ZoneInfo("America/Bogota")`) is the red test on Windows; write it first, then add the dependency.
- [x] **A2.2 [A]** `EventRequest`. Files: `domain/event_request.py`, `tests/unit/test_event_request.py`. `EventType`, `VenueType`, `RequestedLine`, `EventRequest` bounds (tz-aware, `end > start`, duration <= 31 days, guests 1..100000, distance 0..5000, >= 1 line, quantities 1..10000, <= 100 lines), `normalized()` merging duplicate codes. Satisfies: pricing / invalid request, duplicate merge; availability / tz-aware intervals. Test-first: one parametrized invalid-request table, duplicate merge, order independence. (~150 lines incl. tests)
- [x] **A2.3 [A]** `PricingRules`. Files: `domain/pricing_rules.py`, `tests/unit/test_pricing_rules.py`. `GuestTier`, `DistanceBand`, `NightWindow`, `PricingRules` with `__post_init__` validation, `default_pricing_rules()` version `synthetic-v1` (tiers 1/101/301/601 at 0/10/25/40%, weekend 15%, night 22:00-06:00 20%, bands 20 km free / 60 km 3000 / beyond 4500, cap 20%, step 1000, holidays empty; percentages in bps). Test-first: invalid tiers/bands/night/step table, default wraps midnight with zone Bogota, step swap needs no code change. (~180 lines incl. tests)
- [x] **A2.4 [A]** PR A2 verification and measurement (if > 450 STOP). Measured 523 real lines (253 src, 270 tests; estimate was ~330). Tests/parametrized invalid-input tables are ~52%. Fresh-context review before opening the PR still pending.

## PR A3: calculate_price, Quote, golden test, invariants (`feat/quote-domain-calculate-price`, base A2, ~430 lines) [near budget]

- [ ] **A3.1 [A]** Quote types in `domain/pricing.py`: `LineKind`, `QuoteLine`, `Quote` with a single `version: int = 1` field and `to_dict()` (JSON primitives only). No separate schema-version constant (cut 9). Test-first: structure of the worked example and primitives-only `to_dict()`.
- [ ] **A3.2 [A]** `calculate_price(request, catalog, rules) -> Quote` in the order of design section 5 (normalize, rental days by ceil(24h), item lines, package + discount lines with cap, equipment subtotal E, guest-size line, weekend/holiday over touched local dates end-exclusive, night line incl. previous-evening window, marginal distance lines, raw total, single `ROUNDING` line). Files: `domain/pricing.py`, `tests/unit/test_pricing.py`. Test-first, table-driven with `id=`: worked example (E 319900, guest 31990, weekend 47985, night 63980, distance 75000, raw 538855, total 539000, rounding +145); UTC instant that is Saturday night in Bogota; weekday neutral; night boundaries (14-20 none, 16-22 none, 18-23 yes, 05-08 yes); tier boundaries 100/101; distance 19/20/21 km; package discount and cap; duplicate merge; unknown code names the code; currency mismatch; rental days (22:00-03:00 is 1 day); inputs not mutated; step swap.
- [ ] **A3.3 [A]** Golden contract test `tests/unit/test_quote_contract.py` (worked-example `to_dict()` with `version == 1`) plus a small hand-written invariants block in `test_pricing.py` over a fixed grid of inputs (NO Hypothesis): `total >= 0`; `total % step == 0`; `sum(lines) == total`; total monotonic non-decreasing in quantity, distance and guests; rounding idempotent (rounding an already rounded total changes nothing); `type(v) is int` for all amounts. Cut line: if A3 exceeds 450, move this invariants block to the first commit of A4.
- [ ] **A3.4 [A]** PR A3 verification and measurement.

## PR A4: Availability (`feat/quote-domain-availability`, base A3, ~290 lines)

- [ ] **A4.1 [A]** `domain/availability.py`: `BookingStatus` (+ `blocking()`), `Reservation`, `AvailabilityRules` + `default_availability_rules()` (2 h, whole minutes, rule data), `Availability`, `Shortage`, `AvailabilityReport`, `available_units` (buffer/2 expansion, sweep, releases before acquisitions at equal timestamps), `check_availability(..., quantity=1)`, `required_units`, `check_request_availability`. Test-first (`tests/unit/test_availability.py`, table-driven, `id=`, NO oracle, NO Hypothesis): back-to-back with buffer 0 (available); gap exactly buffer (available); buffer minus 1 minute (unavailable); default buffer back-to-back (unavailable); overlap, contained, containing; multi-day clear and overlapping; same-day turnaround (14:00 ok, 13:00 not); stock 1 vs 3 with partial overlap; two sequential reservations inside one long request (peak 1); other item ignored; zero stock; quantity above stock; naive datetime and quantity <= 0 rejected; equivalent instants in different offsets; package components consume stock; shared member aggregation (4 needed, 3 in stock); limiting items reported.
- [ ] **A4.2 [A]** Cancelled bookings are excluded at the repository (B2); the domain `Reservation` carries no status. Record in the PR description. Docs only.
- [ ] **A4.3 [A]** PR A4 verification and measurement.

## PR B1: Schema, one migration, DB fixtures, flat bookings (`feat/quote-domain-schema`, base A4, ~360 lines)

- [ ] **B1.1 [A]** Move schema reset to `tests/conftest.py` (`reset_schema(url)`, special rule 4) and use it in `tests/integration/test_migrations.py`. Refactor-only; P0 migration tests stay green with `DATABASE_URL_TEST`.
- [ ] **B1.2 [A]** Tests first, `tests/integration/test_catalog_schema.py` (DB): upgrade head creates exactly four tables (`equipment_items`, `service_packages`, `package_items`, `bookings`); downgrade to `0001` and to base leaves the expected sets; upgrade/downgrade/upgrade round trip; repeat upgrade is a no-op; named constraints exist; integrity errors for negative stock, `ends_at <= starts_at`, quantity <= 0, duplicate code, package item quantity 0; tables empty after migration; tz-aware round trip of a UTC-5 booking; `compare_metadata` drift test (empty diff vs `Base.metadata`); one-head test (DB-free). Fixtures: `migrated_database`, `session_factory` (`TRUNCATE ... RESTART IDENTITY CASCADE`).
- [ ] **B1.3 [A]** `adapters/db/models.py`: four models on `Base` (BIGINT `*_cop`, `*_bps`, `DateTime(timezone=True)`, named `CheckConstraint`s, `category`/`status` as VARCHAR + CHECK, indexes). Flat `bookings`: `booking_code`, `item_code` (FK to `equipment_items.code`, RESTRICT), `quantity`, `starts_at`, `ends_at`, `status`; index on (`item_code`, `starts_at`, `ends_at`). No `booking_items`.
- [ ] **B1.4 [A]** ONE migration `migrations/versions/0002_catalog_and_bookings.py` (drafted with autogenerate, hand-edited: explicit constraint names, literal strings, `downgrade()` in FK order, schema only, no seed) and `migrations/env.py` models import (special rule 4).
- [ ] **B1.5 [A]** Docs (special rule 5): ADR 12 in `documentacion/decisions.md` and the one-line skill note. Last commit of the block.
- [ ] **B1.6 [A]** PR B1 verification, migration round trip and drift test against a throwaway local Postgres; measurement.
- [ ] **B1.7 [M]** Acknowledge before merging B1: on the next deploy `start.sh` runs `alembic upgrade head` and creates EMPTY tables in Neon (schema only, harmless).

## PR B2: Ports, repositories, fakes (`feat/quote-domain-repositories`, base B1, ~380 lines)

- [ ] **B2.1 [A]** `application/ports.py` (`CatalogRepository.get_catalog() -> Catalog`, `BookingRepository.find_reservations(item_codes, window_start, window_end) -> Sequence[Reservation]`), `application/errors.py` (`RepositoryUnavailable`), `tests/fakes.py` (`InMemoryCatalogRepository`, `InMemoryBookingRepository` filtering by window, `BrokenCatalogRepository`) with a small test that fakes satisfy the Protocols. Architecture test stays green.
- [ ] **B2.2 [A]** `adapters/db/catalog_repository.py` + `tests/integration/test_catalog_repository.py` (DB): two ordered selects with `selectinload`, private `_to_domain`, `SQLAlchemyError` -> `RepositoryUnavailable` via `raise ... from None`; tests: integer `Money` round trip, package members, ordering, empty catalog, bad category row, DB failure without URL/host in the message. Tests red first.
- [ ] **B2.3 [A]** `adapters/db/booking_repository.py` + `tests/integration/test_booking_repository.py` (DB): one row = one `Reservation` (flat table, no join), `status IN blocking()`, read-only; tests: inside/outside window, cancelled excluded, pending and confirmed included, unknown codes yield nothing, half-open edges. Red first.
- [ ] **B2.4 [A]** PR B2 verification and measurement.

## PR B3: Seed data 20/4, idempotent upsert, guarded CLI (`feat/quote-domain-seed`, base B2, ~380 lines)

- [ ] **B3.1 [A]** `adapters/db/seed_data.py` (`SEED_ITEMS` 20, `SEED_PACKAGES` 4; Spanish names, English codes; prices multiples of 1000; stock 1-24 with at least one item with stock > 1; packages with 4-6 lines and `discount_bps` 500-1500; categories `sound, lighting, dj, stage, effects, video` all covered; extend by editing this module only) and `tests/unit/test_seed_data.py` (no DB): `Catalog(...)` builds, counts 20/4, slug regex, categories covered, price multiples, `calculate_price` on each package with default rules gives a positive `Quote`. Red first.
- [ ] **B3.2 [A]** `adapters/db/seed.py` (`seed_catalog(session_factory, items, packages) -> SeedResult`; one transaction, rollback on error; `ON CONFLICT (code) DO UPDATE` via `sqlalchemy.dialects.postgresql.insert`; upsert `package_items`; delete only the package's stale `package_items`; never touch bookings or other rows) and `tests/integration/test_seed.py` (DB): two runs give 20/4 identical, drifted price restored, extra hand-made row survives, bookings untouched. Red first.
- [ ] **B3.3 [A]** Tests first `tests/unit/test_seed_guard.py` (no DB, no network): without `--confirm` prints the dry-run line, exits 2, never builds an engine; local hosts (`localhost`, `127.0.0.1`, `::1`, `db`, no host) proceed; non-local host refused (exit 3) unless `environ["ALLOW_REMOTE_SEED"] == "1"`; `"true"`, `"0"`, `""` refuse; `APP_ENV=production` also requires `"1"`; check runs before any connection; output never contains the URL, host, user or password (sentinel values).
- [ ] **B3.4 [A]** `entrypoints/cli/{__init__.py,seed_catalog.py}`: `main(argv, settings=None, session_factory=None, environ=None) -> int`, host classification via `sqlalchemy.engine.make_url(url).host`, only the `--confirm` option. Special rule 1. Do not open `.env*`.
- [ ] **B3.5 [M]** Contingency: if any task would force an edit to `.env.example` or any `.env*` path, the agent STOPS and the developer applies it. Expected: none. Do NOT add `ALLOW_REMOTE_SEED` to `.env.example` unless `test_env_example.py` is confirmed to tolerate non-`Settings` keys (U3).
- [ ] **B3.6 [A]** PR B3 verification: `git diff --name-only <base>...HEAD | rg "^\.env"` empty; `git diff <base>...HEAD -- backend/src/eventssound/config.py` empty; measurement.

## PR C: Use cases, catalog API, public Swagger, docs (`feat/quote-domain-catalog-api`, base B3, ~450 lines) [borderline]

- [ ] **C.1 [A]** `application/{catalog,pricing,availability}.py` (`list_catalog`, `price_quote`, `check_event_availability` as plain functions over ports; availability queries reservations for `required_units` codes in `[start - buffer, end + buffer)`) and `tests/unit/test_use_cases.py` on fakes: `price_quote` equals `calculate_price`; availability use case equals the pure function over the fake's reservations; package components and shared aggregation; `BrokenCatalogRepository` propagates `RepositoryUnavailable`. Not exposed over HTTP (decision 5). Red first.
- [ ] **C.2 [A]** Tests first `tests/integration/test_catalog_api.py` (no DB, `create_app(catalog_repository=fake)`): items and packages ordered by `code`; empty catalog returns `{"items": []}` / `{"packages": []}`; no `id`/`*_id`/timestamp keys; `base_price_cop` derived; POST/PUT/PATCH/DELETE give 405; `GET /catalog/availability` gives 404; broken repository gives 503 `{"detail": "catalog_unavailable"}` with no host/SQL text; **in production mode (`APP_ENV=production`) `/docs` returns 200 and `/openapi.json` returns 200 and lists both routes, no write operations; `/redoc` is 404**; schema has tags, summaries and response models (assert `tags`, `summary`, and `examples` present on both operations). Check existing P0 tests/`config.py` for any assertion that production hides docs and update it.
- [ ] **C.3 [A]** `entrypoints/api/{schemas.py,routes/catalog.py}`: frozen Pydantic v2 `CatalogItemOut`, `PackageLineOut`, `ServicePackageOut`, `ItemsResponse`, `PackagesResponse` with `from_domain`, `model_config` `json_schema_extra` examples (one per response model, Spanish catalog names, plain business-readable `description` fields); sync routes with `tags=["Catalog"]`, `summary`, `description`, `responses={503: ...}`; reads `request.app.state.catalog_repository`; `RepositoryUnavailable` -> 503. No pagination (D16).
- [ ] **C.4 [A]** `container.py` (`make_catalog_repository`, `make_booking_repository`, `make_pricing_rules`, `make_availability_rules`) and `entrypoints/api/app.py`: `docs_url="/docs"`, `openapi_url="/openapi.json"` ALWAYS enabled (remove the `None if production` logic), `redoc_url=None`, app-level `title`, `description` and `openapi_tags` for business owners; optional repository overrides; router included; CORS unchanged. Satisfies developer requirement (a).
- [ ] **C.5 [A]** `tests/integration/test_catalog_api_db.py` (DB): seeded database through the real wiring returns 20 items and 4 packages with integer prices. If `scripts/smoke.ps1` is cheap to extend, add `/docs` (200) to its expectations; otherwise note it as follow-up in the PR description.
- [ ] **C.6 [A]** Architecture test (D18 item 4): no module under `entrypoints/api/routes/` imports `eventssound.adapters`, with a scanner self-test. Red against a synthetic offending module, green on the real routes.
- [ ] **C.7 [A]** Docs (last commit): `README.md` and `documentacion/deploy.md` state that Swagger UI is public at `/docs` and the schema at `/openapi.json` in production (synthetic data, read-only); `documentacion/decisions.md` ADR 13 "Availability computed in the domain" (D8/D9 summary) plus a short note on public OpenAPI; `documentacion/architecture.md` (domain modules, two ports, link to this change); `documentacion/roadmap.md` note that P4 stays fully in scope; `.claude/skills/design-patterns/SKILL.md` one line replacing the planned `EquipmentRepository` with `CatalogRepository` / `BookingRepository`; document `ALLOW_REMOTE_SEED` usage (exact value `1`, CLI only) in `documentacion/` (not `.env.example`). If the PR measures over 450, move C.7 to `feat/quote-domain-docs` (`docs:` only).
- [ ] **C.8 [A]** PR C verification, including OpenAPI served in production mode; measurement. Then final steps: procedure step 6 and `sdd-verify`.

---

## Verification checklists

Common to EVERY PR (run from `backend/` unless noted; DB variables point to a throwaway local container on `127.0.0.1`, NEVER Neon):
- [ ] `uv run ruff check .` and `uv run ruff format --check .` clean
- [ ] `uv run pytest` green WITHOUT `DATABASE_URL_TEST`: DB tests reported as skipped, unit tests run
- [ ] `uv run pytest` green WITH `DATABASE_URL_TEST` set to the local container
- [ ] DB tests FAIL (not skip) when `DATABASE_URL_TEST` is set but unreachable (spot-check once with a wrong port in B1, B2, B3 and C)
- [ ] From the repo root: `uv run --project backend pytest backend/tests` green
- [ ] Architecture test (`tests/unit/test_architecture.py`) green, including the stdlib-only domain allowlist
- [ ] Every new test was seen red before its implementation (strict TDD); tests live in the same commit as the behavior
- [ ] No `.env*`, secrets or real connection strings in the diff; `git diff --name-only <base>...HEAD | rg "^\.env"` empty
- [ ] Diff <= ~450 lines excluding `uv.lock` and `openspec/`
- [ ] No `Co-Authored-By` or AI attribution in any commit (`git log <base>..HEAD --format=%B | rg -i "co-authored|claude"` empty)
- [ ] PR description states start, end, dependencies, follow-up, out-of-scope, chain diagram; base branch is correct
- [ ] Fresh-context review done before opening the PR (orchestrator PR rule)

Per-PR additions:
- [ ] **A1** allowlist test fails when a `domain` file imports `numpy`/`pydantic` (self-test) and passes on the real domain; rounding table matches the spec
- [ ] **A2** `uv.lock` updated, `tzdata` under runtime dependencies; default rules build under `ZoneInfo("America/Bogota")` on Windows and in CI
- [ ] **A3** worked example gives 539,000 with a `+145` rounding line; golden test passes; `sum(line.amount) == total`; invariants block passes; no `hypothesis` in `pyproject.toml`
- [ ] **A4** boundary table passes: back-to-back, buffer edges, overlap, multi-day, same-day, zero stock, stock > 1, package availability
- [ ] **B1** `alembic upgrade head`, repeat (no-op), `downgrade base` leaves no application tables, `alembic heads` single head, drift test empty; migration has no `INSERT`; exactly four tables, no `booking_items`; `migrations/env.py` imports models; ADR 12 and the one skill line present
- [ ] **B2** repositories raise `RepositoryUnavailable` with a generic message; cancelled bookings excluded; fakes satisfy the Protocols
- [ ] **B3** seed run twice gives 20 items and 4 packages, no duplicates, identical content; dry run exits 2 with no connection; remote host refused without `ALLOW_REMOTE_SEED=1`; output never contains URL, host or credentials; `Settings` and `.env.example` untouched
- [ ] **C** use cases run on fakes; no SQLAlchemy/FastAPI imports in `application/`; `GET /catalog/items` and `/catalog/packages` return the seed through the real wiring; `/catalog/availability` 404; write methods 405; with `APP_ENV=production` `/docs` and `/openapi.json` return 200 and `/redoc` 404; OpenAPI has tags, summaries, response models, examples; README/deploy docs updated

## Dependency summary

| Task group | Parallel with | Sequential after |
| ---------- | ------------- | ---------------- |
| A2-A4 | none (strict chain) | previous PR opened; merges follow the MERGE PROCEDURE |
| B1-B3 | none | A4 (chain order) |
| C | none | B3 |
| Merge actions (retarget, merge, ancestry check) | n/a | After CI green and review of each PR |

Parallelism note: coding can run ahead of merges (branch N+1 is cut from branch N's tip), but only one writer thread at a time. The developer's review is the bottleneck: 7 PRs at ~375 real lines each is roughly one review per half day to land by 2026-10-25 while leaving P2-P4 time. Each merge costs a retarget, a merge, an ancestry check and a CI re-run on the child.

Developer manual actions (summary): GitHub "delete head branches" setting and merge-commit strategy (A2.0), A1 review and merge (A1.6), every retarget/merge/push (procedure), B1.7 Neon empty-tables acknowledgement, B3.5 contingency for any `.env*` edit, decision on the C cut line if C measures over 450.

## Unverified assumptions to check during apply

| # | Assumption | Check at | Fallback |
| - | ---------- | -------- | -------- |
| U1 | The repo allows "Create a merge commit"; with squash/rebase the `merge-base --is-ancestor` check cannot work | A2.0 | With squash: verify with `git diff --stat origin/main <branch-tip>` empty and rebase each child with `git rebase --onto origin/main <old-parent-tip> <child>` |
| U2 | GitHub "automatically delete head branches" retargets child PRs; manual retarget first is still safer | A2.0, procedure step 2 | Manual retarget always |
| U3 | `test_env_example.py` fails if `.env.example` has keys that are not `Settings` fields (or checks only the reverse) | B3.5 (read the test, not `.env*`) | Leave `.env.example` untouched (default plan) |
| U4 | `test_architecture.py` has no rule forbidding `os.environ` in `entrypoints/` | B3.4 | Allow-list the CLI module with a comment, or a tiny `entrypoints/cli/env.py` helper |
| U5 | The next ADR number in `documentacion/decisions.md` is 12 (then 13) | B1.5, C.7 | Use the next free numbers and fix cross references |
| U6 | The throwaway local Postgres (`pgvector/pgvector:pg16` on 127.0.0.1) is available for `DATABASE_URL_TEST` | Before B1 | CI is the authority for DB tests |
| U7 | `uv add tzdata` works behind corporate proxy/TLS interception | A2.1 | Ask the developer to run it; lockfile excluded |
| U8 | `compare_metadata` drift test is stable across Postgres versions | B1.2 | Compare table/column/constraint names only |
| U9 | Calibrated estimates hold (tests ~55-60% of each PR). A3, B3 and C are the likely overruns; ~2,620 remaining lines is the honest number, not 1,800 | Each PR measurement step | Apply the per-PR cut lines; ask before exceeding 450 |
| U10 | Developer accepts the design over the specs (conflict table in A1.1) and the new cuts | Already confirmed for cuts 1-9 | n/a |
| U11 | No existing P0 test or `config.py` logic asserts that docs are hidden in production (grep of `docs_url` found only `app.py`) | C.2 | Update the assertion in the same commit |
| U12 | `scripts/smoke.ps1` can take a `/docs` expectation cheaply | C.5 | Defer to a follow-up note in the PR description |
| U13 | Flat `bookings.item_code` as FK to `equipment_items.code` keeps the availability query a single-table select | B1.3, B2.3 | Use `equipment_item_id` FK and join once in the repository |
| U14 | `documentacion/deploy.md`, `documentacion/roadmap.md` and a root `README.md` exist to carry the Swagger and P4 notes | C.7 | Create the minimal section in the nearest existing doc |
