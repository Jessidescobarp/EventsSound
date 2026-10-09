# Delta Spec: deployment

New capability. Verified by a post-deploy smoke check (curl or a small script) against the live URLs, plus manual checks of host configuration.

## ADDED Requirements

### Requirement: Hosting topology
The system MUST be deployed as: backend on a Render web service, frontend on a Render Static Site (workspace `EventsSoundDr`), database on Neon Postgres (free tier). Render Postgres MUST NOT be used.

#### Scenario: Three public/managed components exist
- GIVEN the deploy is complete
- WHEN the hosts are inspected
- THEN a backend URL, a frontend URL, and a Neon database are provisioned

### Requirement: Secrets and configuration
All secrets (e.g. `DATABASE_URL`) MUST be set as host environment variables only. Production MUST set the allowed CORS origin to the frontend's deployed origin and `VITE_API_BASE_URL` to the backend's deployed URL. The README MUST document the live URLs and required variables (names only).

#### Scenario: No secrets in the repo
- GIVEN the repository
- WHEN scanned for the production connection string
- THEN it is not found

### Requirement: Migrations on release
Deploying the backend MUST run `alembic upgrade head` against the Neon database before the new version serves traffic (release or pre-start step).

#### Scenario: Fresh database deploy
- GIVEN an empty Neon database
- WHEN the backend is deployed
- THEN `alembic_version` holds the baseline revision and the service starts

#### Scenario: Migration failure blocks release
- GIVEN a failing migration
- WHEN the deploy runs
- THEN the new version does not go live

### Requirement: Live backend health
The live backend MUST answer `GET <backend-url>/health` with 200 and `{"status":"ok"}` over HTTPS. A smoke check SHALL tolerate cold starts by retrying up to 90 seconds.

#### Scenario: Smoke check passes
- GIVEN the service was idle (cold)
- WHEN the smoke check requests `/health` with retries up to 90 s
- THEN it receives 200 `{"status":"ok"}` and exits 0

#### Scenario: Smoke check fails loudly
- GIVEN the backend never responds 200 within 90 s
- WHEN the smoke check runs
- THEN it exits non-zero and prints the last status or error

### Requirement: Live frontend and cross-origin integration
The live frontend URL MUST serve the shell over HTTPS and display `Servicio operativo`, proving the browser can call the backend across origins.

#### Scenario: End-to-end status
- GIVEN both services are live
- WHEN the frontend is loaded in a browser and the backend is warm
- THEN `Servicio operativo` is shown with no CORS errors in the console

#### Scenario: Cold backend
- GIVEN the backend is cold
- WHEN the frontend loads
- THEN `Cargando estado del servicio...` is shown until the backend responds, then the final status is displayed
