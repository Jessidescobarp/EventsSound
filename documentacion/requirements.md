# Requirements

## TFM deliverables

- README with stack, run steps and test credentials.
- Public GitHub repository.
- Live deployment URL.
- Slides.
- Screen-recorded video of the working product.
- AI must be the core of the product, not a decoration.

## Functional requirements

Quote agent (heart of the product):

- A visitor describes an event in natural language and receives a structured quote plus a proposal text.
- Prices are computed by deterministic code (`calcular_precio`), never by the LLM.
- Equipment is searched in a synthetic catalog; availability is checked against a small bookings table.
- Every quote answer is saved (validated fields only, no personal data). Creating a booking from the UI was not built; the `bookings` table only feeds availability. No payments, no calendar UI.

Public chat hardening (minimum):

- Input length cap.
- System prompt that treats user text as data, not instructions.
- Schema-validated model output.
- Per-IP rate limit.
- Daily token and cost cap.

Data:

- All data is synthetic (catalog, bookings, users). No real personal data.

Admin (built): saved quotes, bookings, catalog and portfolio edits, security events and agent configuration (tone, messages, model, caps) inside hard ceilings. Out of scope for the MVP: payments, users CRUD, image generation and uploads, voice, e2e browser tests.

## Non-functional requirements

- Free-tier hosting (Render web service, Render static site, Neon Postgres).
- Hard cost caps on LLM usage: environment defaults plus admin-adjustable caps that never exceed ceilings set in code; every selectable model has a known price (fail closed).
- Provider-agnostic LLM access through a port, with a replay adapter for deterministic tests.
- Cold starts on the free tier are accepted; documented in the README.
- No secrets in the repository.

Sources: [exploration](../openspec/changes/tfm-phased-mvp/exploration.md), [proposal](../openspec/changes/walking-skeleton-and-deploy/proposal.md), [specs](../openspec/changes/walking-skeleton-and-deploy/specs/).
