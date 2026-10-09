# Delta Spec: backend-health-api

New capability. Verified with pytest + FastAPI TestClient.

## ADDED Requirements

### Requirement: Application factory
The backend MUST expose a `create_app(...)` factory returning a FastAPI instance. The factory SHALL accept dependency overrides (settings, DB session provider) so tests build isolated apps.

#### Scenario: Factory builds independent apps
- GIVEN two calls to `create_app` with different settings
- WHEN each app is inspected
- THEN each holds its own settings and no module-level global app state is shared

### Requirement: Health endpoint
The backend MUST serve `GET /health` returning HTTP 200 with JSON `{"status": "ok"}`. The endpoint MUST NOT require authentication.

#### Scenario: Healthy service
- GIVEN the app is running
- WHEN a client sends `GET /health`
- THEN the response status is 200 and the body is `{"status": "ok"}`

#### Scenario: Health does not depend on a live database
- GIVEN the database is unreachable
- WHEN a client sends `GET /health`
- THEN the response status is still 200 (liveness only)

### Requirement: Environment-driven settings
Settings MUST be loaded from environment variables (database URL, allowed CORS origins, environment name). The app MUST fail fast at startup with a clear error if `DATABASE_URL` is missing. Every variable MUST appear in `.env.example`.

#### Scenario: Missing required variable
- GIVEN `DATABASE_URL` is unset
- WHEN settings are loaded
- THEN a validation error naming `DATABASE_URL` is raised

#### Scenario: .env.example completeness
- GIVEN the Settings model fields
- WHEN compared to keys in `.env.example`
- THEN every setting has a matching key and no real secret value is present

### Requirement: CORS restriction
The backend MUST allow cross-origin requests only from origins listed in the configured allowed-origins setting. It MUST NOT use a wildcard origin outside local development. Debug mode MUST be disabled when the environment name is `production`.

#### Scenario: Allowed origin
- GIVEN allowed origins is `https://frontend.example`
- WHEN a request with `Origin: https://frontend.example` hits `/health`
- THEN the response includes `Access-Control-Allow-Origin: https://frontend.example`

#### Scenario: Disallowed origin
- GIVEN the same configuration
- WHEN a request with `Origin: https://evil.example` hits `/health`
- THEN the response has no `Access-Control-Allow-Origin` header

#### Scenario: Production disables debug
- GIVEN environment name `production`
- WHEN the app is created
- THEN `app.debug` is false
