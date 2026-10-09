# Delta Spec: ci-pipeline

New capability. Verified by inspecting `.github/workflows/ci.yml` and observing a green run on GitHub Actions.

## ADDED Requirements

### Requirement: Triggers
The workflow MUST run on pull requests and on pushes to `main`.

#### Scenario: PR triggers CI
- GIVEN a pull request targeting `main`
- WHEN it is opened or updated
- THEN the backend and frontend jobs start

### Requirement: Backend job
The backend job MUST use a Postgres service container and run, in order: dependency install, `ruff check`, `ruff format --check`, `alembic upgrade head`, `pytest`. Any failing step MUST fail the job.

#### Scenario: Lint violation fails CI
- GIVEN a commit with a ruff violation
- WHEN the backend job runs
- THEN it fails at `ruff check` and later steps are skipped

#### Scenario: Green backend
- GIVEN a clean commit
- WHEN the backend job runs
- THEN all steps pass, including migrations against the service container

### Requirement: Frontend job
The frontend job MUST run install, lint, `vitest run`, and build. Any failing step MUST fail the job.

#### Scenario: Build break fails CI
- GIVEN a TypeScript error in the frontend
- WHEN the frontend job runs
- THEN the build step fails the job

### Requirement: No secrets in CI config
Workflow files MUST NOT contain secret values; CI database credentials MAY be throwaway literals for the ephemeral service container only.

#### Scenario: Secret scan
- GIVEN the repository at `main`
- WHEN tracked files are scanned for `.env` files and key patterns
- THEN no real secrets are found and only `.env.example` is tracked

### Requirement: Strict TDD config flip
After pytest passes in CI, `openspec/config.yaml` MUST set `strict_tdd: true`, `testing.runner.command: pytest`, `apply.tdd: true`, and non-empty `apply.test_command` and `verify.test_command` that run successfully.

#### Scenario: Config commands work
- GIVEN the updated config
- WHEN `verify.test_command` is executed from the repo
- THEN it exits 0
