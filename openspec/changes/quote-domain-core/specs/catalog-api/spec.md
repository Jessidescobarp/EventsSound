# Delta Spec: catalog-api

Change: quote-domain-core. Read-only, unauthenticated, synthetic data, no LLM surface.

## ADDED Requirements

### Requirement: List items
`GET /catalog/items` MUST return HTTP 200 with a JSON object `{"items": [...]}` ordered by `code`. Each element MUST contain `code`, `name`, `category`, `stock_quantity` and `unit_price_cop` (integer). It MUST NOT expose database `id` values or any internal field. A Pydantic v2 response model MUST define the shape.

#### Scenario: Seeded catalog
- Given a database seeded with 30 items
- When `GET /catalog/items` is called
- Then the response is 200 with 30 items, ordered by `code`, each with integer `unit_price_cop`

#### Scenario: Empty database
- Given a migrated database with no rows
- When `GET /catalog/items` is called
- Then the response is 200 with `{"items": []}`

#### Scenario: No internal ids
- Given any non-empty response
- When keys are inspected
- Then no `id`, `*_id` or timestamp-internal key is present

### Requirement: List packages
`GET /catalog/packages` MUST return HTTP 200 with a JSON object `{"packages": [...]}` ordered by `code`. Each element MUST contain `code`, `name`, `discount_bps`, `base_price_cop` (derived per rental day before discount) and `items`, where each member has `item_code` and `quantity`. No internal ids may be exposed.

#### Scenario: Seeded packages
- Given 5 seeded packages
- When `GET /catalog/packages` is called
- Then 5 packages are returned, each with at least one member whose `item_code` appears in `/catalog/items`

#### Scenario: Empty database
- Given no package rows
- When `GET /catalog/packages` is called
- Then the response is 200 with `{"packages": []}`

### Requirement: Read-only and public surface
The catalog routes MUST accept only GET. No write endpoint (POST, PUT, PATCH, DELETE) for catalog or bookings MUST be added, no authentication is required, and there MUST be NO `/catalog/availability` or other availability route in this change. CORS configuration MUST remain unchanged unless a method is required for GET (already allowed).

#### Scenario: Write methods rejected
- Given the running app
- When POST, PUT, PATCH or DELETE is sent to `/catalog/items` or `/catalog/packages`
- Then the response is 405

#### Scenario: No availability route
- Given the running app
- When `GET /catalog/availability` is called
- Then the response is 404

### Requirement: Wiring and error behavior
The routes MUST obtain their data through application use cases and ports wired in `container.py`; routes MUST NOT import SQLAlchemy or adapters. Tests MUST be able to override the catalog port with an in-memory fake. If the database is unavailable the API MUST return 503 with body `{"detail": "catalog_unavailable"}`, without host, user, driver, SQL or connection string.

#### Scenario: Fake port
- Given an app built with a fake catalog reader
- When `GET /catalog/items` is called
- Then the response comes from the fake without any database

#### Scenario: Database down
- Given the database is unreachable
- When `GET /catalog/items` is called
- Then the response is 503 and the body contains no connection details

### Requirement: OpenAPI and Swagger UI are public in every environment
(Changed 2026-10-12, developer decision: supersedes the earlier "disabled in production" policy.) The app MUST always serve Swagger UI at `/docs` and the schema at `/openapi.json`, including `APP_ENV=production`. ReDoc stays off. The schema MUST be presentable to a business owner: tags, summaries, descriptions, response models and examples for both catalog routes. The API is read-only with synthetic data, so exposing it adds no sensitive surface.

#### Scenario: Production
- Given `APP_ENV=production`
- When `/openapi.json` and `/docs` are requested
- Then both respond 200

#### Scenario: Any environment
- Given any environment
- When `/openapi.json` is fetched
- Then it lists `/catalog/items` and `/catalog/packages` with tags, summaries, response models and examples, and no write operations for them
