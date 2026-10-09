# Delta Spec: frontend-shell

New capability. Verified with Vitest + Testing Library (fetch mocked) and the CI build. UI copy is Spanish; code and identifiers are English.

## ADDED Requirements

### Requirement: Stack and build
The frontend MUST be a Vite + React + TypeScript app that builds with no type errors. It MUST NOT include shadcn/ui, routing for real pages, or auth.

#### Scenario: Production build
- GIVEN installed dependencies
- WHEN `npm run build` runs
- THEN it exits 0 and emits a static bundle

### Requirement: Single-page shell
The app MUST render one page with a header showing the text `EventsSound`, a main area, and an `<html lang="es">` document.

#### Scenario: Shell renders
- GIVEN the app is mounted
- WHEN the DOM is queried
- THEN a heading `EventsSound` is present and `document.documentElement.lang` is `es`

### Requirement: Env-driven API URL
The API base URL MUST come from `VITE_API_BASE_URL`, documented in `.env.example`. The code MUST NOT hardcode a backend host.

#### Scenario: URL used for health call
- GIVEN `VITE_API_BASE_URL=https://api.example`
- WHEN the shell mounts
- THEN it requests `https://api.example/health`

### Requirement: Health status display
The shell MUST call `GET /health` on mount and show a status line in Spanish: `Cargando estado del servicio...` while pending, `Servicio operativo` on a 200 `{"status":"ok"}`, and `Servicio no disponible` on a network error or non-2xx response.

#### Scenario: Backend healthy
- GIVEN fetch resolves 200 with `{"status":"ok"}`
- WHEN the shell settles
- THEN `Servicio operativo` is shown

#### Scenario: Backend down
- GIVEN fetch rejects or returns 503
- WHEN the shell settles
- THEN `Servicio no disponible` is shown and the app does not crash

#### Scenario: Pending state
- GIVEN fetch has not resolved
- WHEN the shell first renders
- THEN `Cargando estado del servicio...` is shown

### Requirement: Smoke test
The frontend MUST have Vitest configured with at least one passing smoke test covering shell render.

#### Scenario: Vitest runs
- GIVEN installed dependencies
- WHEN `vitest run` executes
- THEN it exits 0
