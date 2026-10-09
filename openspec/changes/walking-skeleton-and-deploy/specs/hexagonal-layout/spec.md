# Delta Spec: hexagonal-layout

New capability. Verified by a pytest architecture test (import scanning via `ast`) plus repo-structure assertions.

## ADDED Requirements

### Requirement: Monorepo structure
The repository MUST contain `backend/`, `frontend/`, root `docker-compose.yml`, `.env.example`, `.gitignore`, and `.gitattributes` (LF line endings). `.env` MUST be git-ignored.

#### Scenario: Required paths exist
- GIVEN a fresh checkout
- WHEN the paths above are checked
- THEN all exist and `.gitignore` contains an `.env` rule

### Requirement: Backend layer packages
The backend MUST define four packages under its source root: `domain`, `application`, `adapters`, `entrypoints`. Each MUST be an importable package.

#### Scenario: Packages importable
- GIVEN the backend is installed
- WHEN each of the four packages is imported
- THEN no ImportError occurs

### Requirement: Dependency rule
`domain` MUST NOT import from `application`, `adapters`, `entrypoints`, or any framework (FastAPI, SQLAlchemy, Pydantic settings, Alembic). `application` MUST NOT import from `adapters` or `entrypoints`. `adapters` MUST NOT import from `entrypoints`.

#### Scenario: Domain purity
- GIVEN all modules under `domain`
- WHEN their imports are statically scanned
- THEN none reference forbidden packages and the test passes

#### Scenario: Violation is detected
- GIVEN a module in `domain` importing `sqlalchemy`
- WHEN the architecture test runs
- THEN it fails naming the offending module and import

### Requirement: Composition root
Wiring of concrete adapters to ports MUST occur only in `entrypoints` (composition root). A single documented DI point SHALL exist where later phases register the `LlmProvider` port; no LLM code is added by this change.

#### Scenario: No adapter construction outside the root
- GIVEN modules under `application`
- WHEN scanned for imports from `adapters`
- THEN none are found
