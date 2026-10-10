# Tasks: local-dev-workflow

- [x] `scripts/dev.ps1` with start, `-Down`, `-Reset`, `-Smoke`
- [x] `scripts/smoke.ps1` with parametrized URLs and exit code
- [x] `.gitignore` `.dev/`, README section, AGENTS.md commands, ADR 11
- [x] Bash equivalent: skipped (out of scope)

## Verification (run with settings passed via process environment, POSTGRES_PORT=55433)

- [x] `dev.ps1 -Smoke`: db healthy, migrations, backend and frontend up, all smoke checks PASS
- [x] Re-run does not start duplicates
- [x] Smoke exits 1 with a FAIL table when the backend is unreachable
- [x] Hot reload: touching a backend source file logs `StatReload detected changes`
- [x] `-Down` then `-Reset`: no processes, containers or volumes left
- [x] backend ruff + pytest; frontend tsc, lint, vitest, build
- [ ] UNVERIFIED: `.env` auto-copy branch and reading settings from a real root `.env`
- [ ] UNVERIFIED: PowerShell 5.1 (run on `powershell.exe` 5.1 only; pwsh 7 not tested)
