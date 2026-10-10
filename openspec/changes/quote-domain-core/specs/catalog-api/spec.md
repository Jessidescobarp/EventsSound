# Delta Spec: catalog-api

Change: quote-domain-core. Read-only, unauthenticated, synthetic data, no LLM surface.

## ADDED Requirements

### Requirement: List items
`GET /catalog/items` MUST return HTTP 200 with a JSON array of items ordered by `code`. Each element MUST contain `code`, `display_name`, `category`, `stock_quantity` and `unit_price_cop` (integer). It MUST NOT expose database `id` values or any internal field. A Pydantic v2 response model MUST define the shape.

#### Scenario: Seeded catalog
- Given a database seeded with 30 items
- When `GET /catalog/items` is called
- Then the response is 200 with 30 items, ordered by `code`, each with integer `unit_price_cop`

#### Scenario: Empty database
- Given a migrated database with no rows
- When `GET /catalog/items` is called
- Then the response is 200 with `[]`

#### Scenario: No internal ids
- Given any non-empty response
- When keys are inspected
- Then no `id`, `*_id` or timestamp-internal key is present

### Requirement: List packages
`GET /catalog/packages` MUST return HTTP 200 with a JSON array of packages ordered by `code`. Each element MUST contain `code`, `display_name`, `description`, `discount_bps` and `items`, where each member has the item `code`, `display_name` and `quantity`. No internal ids may be exposed.

#### Scenario: Seeded packages
- Given 5 seeded packages
- When `GET /catalog/packages` is called
- Then 5 packages are returned, each with at least one member whose `code` appears in `/catalog/items`

#### Scenario: Empty database
- Given no package rows
- When `GET /catalog/packages` is called
- Then the response is 200 with `[]`

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
The routes MUST obtain their data through application use cases and ports wired in `container.py`; routes MUST NOT import SQLAlchemy or adapters. Tests MUST be able to override the catalog port with an in-memory fake. If the database is unavailable the API MUST return a generic 5xx error body without host, user, driver or connection string.

#### Scenario: Fake port
- Given an app built with a fake catalog reader
- When `GET /catalog/items` is called
- Then the response comes from the fake without any database

#### Scenario: Database down
- Given the database is unreachable
- When `GET /catalog/items` is called
- Then the response is 5xx and the body contains no connection details

### Requirement: OpenAPI exposure policy preserved
OpenAPI and docs MUST remain disabled in production (`docs_url` and `openapi_url` are `None` when the app is in production) and available otherwise; the new routes MUST appear in the generated schema outside production with their response models.

#### Scenario: Production
- Given `APP_ENV=production`
- When `/openapi.json` and `/docs` are requested
- Then both respond 404

#### Scenario: Local
- Given a non-production environment
- When `/openapi.json` is fetched
- Then it lists `/catalog/items` and `/catalog/packages` and no write operations for them
