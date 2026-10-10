# Tasks: local-dev-workflow

- [x] `scripts/dev.ps1` with start, `-Down`, `-Reset`, `-Smoke`, `-AllowRemoteDb`
- [x] `scripts/smoke.ps1` with parametrized URLs, retries and exit code
- [x] `.gitignore` `.dev/`, compose project pinned, README section, AGENTS.md commands, ADR 11
- [x] Bash equivalent: skipped (out of scope)

## Verification (settings via process environment, POSTGRES_PORT=55433, Windows PowerShell 5.1)

- [x] `dev.ps1 -Smoke` with the pinned project `eventssound-dev`: all six smoke checks PASS (health, db, frontend, CORS simple, preflight, negative origin)
- [x] Re-run reports both processes already running, no duplicates
- [x] Stale PID (live unrelated process, wrong start time): `-Down` kills nothing and removes the file
- [x] Empty or garbage PID files: ignored, `-Down` still stops the db
- [x] Fake non-local `DATABASE_URL`: refused before docker and alembic, no URL parts printed
- [x] Busy port 8000: clear failure naming port and owner; busy POSTGRES_PORT: docker error line shown
- [x] Hot reload (backend): touching a source file logs `StatReload detected changes`
- [x] `-Down` and `-Reset`: no processes, containers, volumes or listeners left
- [x] backend ruff + pytest; frontend tsc, lint, vitest, build
- [ ] UNVERIFIED: `.env` auto-copy branch and settings read from a real root `.env`
- [ ] UNVERIFIED: PowerShell 7, `-AllowRemoteDb` path, Vite HMR in a browser, smoke against a deployed stack
