# Proposal: quote-domain-core (P1 Domain core)

## Intent
The quote agent (P2) needs deterministic ground truth before any LLM code exists: a synthetic catalog, a pure pricing function that will be the eval oracle (decision 9: prices come from code, never the LLM), and an availability check. P1 delivers those plus persistence and a read-only catalog API. Why now: P1 is scheduled Oct 12-14; P2 (agent) and P3 (evals) depend on it, and the MVP deadline is 2026-10-25.

## Scope

### In
1. **Pure domain** (`domain/`, no framework imports, stdlib only):
   - Catalog: `EquipmentItem` (category, stock quantity, unit price), `ServicePackage` (bundles items with quantities, optional discount).
   - `EventRequest`: event type, start/end datetimes, guest count, venue distance (km), indoor/outdoor, requested items/packages.
   - `Money`: frozen integer value object with currency code (default `COP`).
   - `PricingRules`: frozen data object (guest tiers, weekend/holiday multiplier, night window + surcharge, distance bands/rate, package discount, rounding step). Synthetic defaults in code; owner-supplied rules replace the data later with no code change.
   - `calculate_price(request, catalog, rules) -> Quote` (line items + breakdown + total). `calcular_precio` is only the agent-facing alias, added in P2.
   - `check_availability(item, start, end, bookings, buffer)` using half-open `[start, end)` intervals: back-to-back is allowed, multi-day and same-day turnaround buffer are covered.
2. **Persistence**: tables `equipment_items`, `service_packages`, `package_items`, `bookings`; two reversible Alembic revisions (schema only; seed is not a migration); repository ports in `application/` and SQLAlchemy adapters in `adapters/db/`; idempotent synthetic seed script (25-40 items, 4-6 packages, Spanish display names, English identifiers) that refuses to run unless explicitly targeted (see Risks).
3. **Read-only API**: `GET /catalog/items`, `GET /catalog/packages`, optional `GET /catalog/availability`; Pydantic response models; wiring in `container.py`.
4. Tests: table-driven plus property-based (Hypothesis, dev dependency) for pricing/availability; DB tests follow the skip-unset / fail-unreachable rule.

### Out (deferred to the next change, P2+)
Agent/LangGraph, `LlmProvider`, `buscar_equipamiento` and RAG, pgvector/embeddings (P2), evals and golden set (P3), auth/JWT/RBAC, write endpoints, booking creation (including "pending booking from a quote"), any UI/frontend, the `calcular_precio`/`consultar_disponibilidad` tool wrappers.

## Approach
Hexagonal, inside-out and TDD: domain first (pure, fast tests), then ports and adapters, then the entrypoint.
- **Money: integer whole pesos, not cents.** COP has no practical minor unit; storing centavos would carry two dead digits and invite float/format bugs. The database-conventions rule is "integer cents or Numeric, never float"; whole-peso BIGINT satisfies the intent (exact integers) but deviates from the `*_cents` naming example, so columns are named `unit_price_cop`. Money carries a currency code so a minor-unit exponent can be added later. Documented as an ADR in `decisions.md`; the skill gets a one-line note in PR B.
- **Rounding** is a rule datum: final total rounded to a configurable step (default 1000 COP, half-up on integers; no floats anywhere, multipliers as `Fraction`/basis points).
- **Rules as data**: `PricingRules` is a frozen dataclass; the repository/loader can later hydrate it from JSON or DB without touching `calculate_price`.
- **Holidays**: a `HolidayCalendar` is an injected set of dates (default empty, weekends only) so Colombian holidays are data, not code.
- Availability is a pure function over bookings supplied by a repository port; the use case lives in `application/`.

## Affected areas
`backend/src/eventssound/{domain,application,adapters/db,entrypoints/api}`, `backend/migrations/versions/0002-0003`, `backend/scripts/seed_catalog.py` (or `python -m` module), `backend/tests/{unit,integration}`, `backend/pyproject.toml` (Hypothesis dev dep), `documentacion/{architecture,decisions}.md`. The architecture test (`test_architecture.py`) must keep passing; it may need to allow the new `domain` modules (stdlib only).
Agent/security impact: none now. This change fixes the oracle contract (`Quote` shape and `calculate_price` signature) that P2 tools and P3 evals consume; the API is read-only, unauthenticated, synthetic data, no LLM surface.

## Rollback
Additive only. Revert the PR chain in reverse order; `alembic downgrade` drops the four tables (tested via the existing upgrade/downgrade test). Routes are new, so nothing existing breaks. The seed is a manual script, so no production data exists to clean unless it was run deliberately.

## Success criteria
- `calculate_price` is deterministic: same input gives identical `Quote`; property tests pass (non-negative, monotonic in quantity, total equals sum of lines after rounding).
- Availability edge cases pass: back-to-back, overlap, multi-day, buffer, stock > 1.
- Migrations upgrade, repeat, downgrade to base; single head.
- Seed loads twice with no duplicates; counts within 25-40 items / 4-6 packages.
- `GET /catalog/*` returns the seed; `uv run --project backend pytest backend/tests`, ruff check and format all green in CI; each PR <= 400 changed lines.

## Risks
- Time: 1.5 days budget; pricing rule breadth could balloon. Mitigate by cutting rules to the listed set; no new rule types.
- Seed run against production Neon by accident: require an explicit `--confirm` flag plus refuse when the URL host is not local unless `ALLOW_REMOTE_SEED=1`; never read `.env*`.
- Oracle contract churn in P2: keep `Quote` minimal and versioned by tests.
- Hypothesis adds a dependency and CI time (small).
- Timezone bugs: store timezone-aware UTC, interpret night/weekend rules in `America/Bogota` (domain takes a `tzinfo` from rules).

## Decisions (resolved by the developer, 2026-10-10)
1. Money: whole COP pesos (BIGINT, columns named `*_cop`); final price rounded to the nearest 1000 pesos (half up). Add a one-line note about the deviation from the `*_cents` example in the database-conventions skill (PR B).
2. Availability buffer: 2 hours of setup/teardown between events for the same equipment, stored as rule-set data (configurable).
3. Seed: 30 catalog items and 5 packages (synthetic, Spanish display names, English identifiers).
4. Holidays: weekends only for now. A Colombian holiday calendar can be added later as rule-set data once the owner defines it.
5. `GET /catalog/availability` is NOT public in this change (the P2 agent calls availability internally).
6. Accepted additions: Hypothesis as a dev dependency for property-based tests; a seed guard (requires `--confirm`; refuses non-local hosts unless `ALLOW_REMOTE_SEED=1`); pricing rules interpreted in the `America/Bogota` timezone.

## Review Workload Forecast
| Metric | Value |
| ------ | ----- |
| Estimated changed lines (excl. lockfiles) | ~1000-1150 total across 3 PRs |
| Chained PRs recommended | Yes (stacked-to-main, delivery strategy resolved) |
| 400-line budget risk | Medium for PR A and PR B (tests heavy); Low for PR C |
| Decision needed before apply | Yes: answer open questions 1, 2 and 4 (they shape PR A rules/tests) |

| PR | Branch | Content | Est. lines | Merge order |
| -- | ------ | ------- | ---------- | ----------- |
| A | `feat/quote-domain-pricing` | `Money`, catalog/request entities, `PricingRules`, `calculate_price`, availability logic, unit + property tests | 380-420 (watch budget; if over, move availability logic to B0 or trim tests) | 1 |
| B | `feat/quote-persistence` | models, 2 migrations, repository ports + adapters, seed script, DB tests, ADR note | 380-430 | 2 |
| C | `feat/catalog-api` | availability use case, catalog routes + schemas, `container.py` wiring, API tests, docs updates | 250-320 | 3 |

Dependencies: B needs A (domain types); C needs A and B. Per AGENTS.md, retarget each dependent PR to `main` BEFORE merging its parent. Each PR description states start, end, dependencies, follow-up and out-of-scope.
