---
name: test-summary
description: "Trigger: run tests, check tests, verify a change, test failure, token cost of test output. Run the compact test runner and report only its summary."
metadata:
  author: Jessid Alberto Escobar Palacio
  version: "1.0"
---

## When to use
Any time you would run Pytest, Vitest, Ruff, `tsc` or the frontend build to check a change. Use the runner instead of the raw commands so only a short summary reaches the conversation.

## Command
`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test-summary.ps1 -Suite backend|frontend|all -Mode focused|full [-Filter <test name or path>] [-MaxFail1]`

It prints `STATUS`, `SUITE`, `MODE`, `DURATION`, `TESTS`, and for a failure the first failing test with file, line and message. The exit code is the real one of the suite (0 pass, 5 no tests selected, 2 frontend dependencies missing, 124 timeout). Write its output to a file or run it without a pipe when you need the exit code.

## How to choose
1. While editing: `-Mode focused -Filter <nearest test file or name>` with `-MaxFail1`.
2. End of a work unit: `-Suite backend -Mode full` (and `frontend` if frontend files changed).
3. Documentation-only changes: no test run needed.
4. Frontend needs `npm ci` inside `frontend/` once; the runner says so when it is missing.
5. Lint and types are separate commands (`ruff check`, `ruff format --check`, `npm run lint`, `npx tsc --noEmit`): run them once before finishing, not after every edit.

## Rules
- Report only the compact summary. Open the saved log (path printed as `LOG:`) only when the summary cannot explain the failure, and read just the relevant lines.
- Strict TDD stays on: write the failing test first. Never edit a test just to make it pass; if the test expresses the contract, fix the implementation.
- Keep the test count lean (see "Testing and review budget" in `AGENTS.md`): one parametrized table per class of input, not one row per variation.
- DB tests need `DATABASE_URL_TEST` on a throwaway local Postgres; never point tests at Neon.
