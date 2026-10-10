# Apply progress: PR 4 (`feat/deploy-config`)

Facts verified on 2026-10-10 from official docs. Anything not confirmed is labelled UNVERIFIED.

## T4.3 Render facts

Sources: https://render.com/docs/blueprint-spec, https://render.com/schema/render.yaml.json, https://render.com/docs/free, https://render.com/docs/deploys, https://render.com/docs/rollbacks, https://render.com/docs/node-version, https://render.com/docs/redirects-rewrites (all accessed 2026-10-10).

| Item | Result |
| ---- | ------ |
| `runtime` vs `env` | `runtime` required; `env` is deprecated. Values: `docker`, `image`, `static`, native runtimes. A static site is `type: web` + `runtime: static`. |
| Web fields | `plan` (`free` valid), `region` (`oregon` default, `ohio`, `virginia`, `frankfurt`, `singapore`; immutable after creation), `rootDir`, `dockerfilePath` (default `./Dockerfile`), `dockerContext`, `healthCheckPath`, `autoDeployTrigger`. |
| Docker paths | Docs say `dockerfilePath` and `dockerContext` are relative to the REPO ROOT. How they combine with `rootDir` is UNVERIFIED, so the Blueprint omits `rootDir` for the API and uses `./backend/Dockerfile` + `./backend`. |
| `autoDeployTrigger` | Enum `off`, `commit` (default), `checksPass`. `checksPass` = "deploys only after all CI checks pass; no deploy if zero checks are detected or any fails". Availability on the free plan is not restricted in the docs read (not explicitly confirmed: UNVERIFIED). `autoDeploy` is deprecated. |
| `buildFilter` | Object with `paths` and `ignoredPaths` (string arrays, globs relative to repo root). |
| `envVars` | Items: `key` + `value`, or `key` + `sync: false` (prompted only at initial Blueprint creation, ignored on later syncs), `generateValue`, `fromService`, `fromDatabase`, `fromGroup`. |
| Static site | `staticPublishPath` required, relative to the repo root per docs (interaction with `rootDir` UNVERIFIED, so the Blueprint omits `rootDir` and uses `cd frontend && ...` + `./frontend/dist`). `plan` is NOT allowed (schema `additionalProperties: false`). `region`, `startCommand` unsupported. `routes` items: `type` (`redirect` or `rewrite`), `source`, `destination`. `headers` items: `path`, `name`, `value`. |
| `preDeployCommand` | Docs: "available for paid web services, private services, and background workers". NOT available on free. Assumption A1 confirmed; migrations stay in `backend/start.sh`. |
| Failed deploy | If a deploy command fails or times out the service keeps running its last successful deploy (zero downtime). Health checks verify the new instance. Behaviour of a crash-looping `start.sh` on a single free instance is not spelled out: UNVERIFIED (design D5 relies on it). |
| Free web limits | 750 free instance hours per workspace per month (spun-down time not counted; services suspended when exhausted); spin down after 15 min without inbound traffic; spin-up about 1 minute; single instance; no persistent disk, no SSH/shell; ephemeral filesystem; may restart at any time. |
| Bandwidth / build minutes | Counted against monthly included allowances; amounts not stated on the page (UNVERIFIED). Without a payment method, services are suspended when bandwidth is exhausted and new builds are disabled when build minutes run out. |
| Card required | The free-instances page does not require one. Community threads (not official policy, old) report card verification (a $1 authorization hold) is sometimes demanded for anti-abuse. Treat as UNVERIFIED: may be asked at signup or Blueprint creation. |
| Static sites | Free to deploy, global CDN, same bandwidth and build-minute allowances. |
| Node version | `NODE_VERSION` env var > `.node-version` > `.nvmrc` > `package.json` engines; docs warn that unbounded ranges (`>=22`) resolve to latest. Default is 24.x. Whether static sites honor it is UNVERIFIED, so `NODE_VERSION=22` is set as an env var (harmless if ignored). |
| Rollback | Dashboard: Deploys page, "Rollback" on a recent successful deploy. This automatically disables autodeploys for the service (re-enable in Settings). Retained artifact count by plan is UNVERIFIED. |
| Subdomain availability | `eventssound-api` / `eventssound-web` availability cannot be checked offline: UNVERIFIED. If taken, Render appends a suffix; update `CORS_ALLOWED_ORIGINS` and `VITE_API_BASE_URL`. |
| `render blueprints validate` | Render CLI not installed; not installed per instructions. Offline checks done: YAML parse and manual comparison with the JSON schema property names. Real validation happens at T4.7. |

## T4.3 Neon facts

Sources: https://neon.com/docs/connect/connection-pooling, https://neon.com/docs/connect/connect-securely, https://neon.com/docs/introduction/plans (accessed 2026-10-10).

- Pooled string: hostname with `-pooler` suffix (PgBouncer, transaction mode). Direct: no suffix. Neon says to use direct for migrations (tools may not support transaction pooling; `SET`, `LISTEN/NOTIFY`, session advisory locks, SQL-level `PREPARE` do not work pooled). Alembic and the app both use the DIRECT string (design D10).
- Neon requires TLS. `sslmode=require` encrypts and is accepted; Neon recommends `verify-full` (needs a root CA bundle; not adopted here). `channel_binding=require` enables SCRAM-SHA-256-PLUS.
- psycopg 3 / libpq handling of `channel_binding` and `sslmode`: not covered in the Neon page; libpq supports both as connection parameters and `Settings` keeps the query string intact (see `config.py`). Whether the installed psycopg libpq honors `channel_binding=require` against Neon is UNVERIFIED. Fallback: drop `channel_binding`.
- Free plan: 1 GB storage per project, 100 CU-hours per project per month, scale-to-zero after 5 min (cannot be disabled), 100 projects, 10 branches per project. Card requirement and pgvector support are not stated on that page: UNVERIFIED.

## T4.1 decisions and deviations

- `autoDeployTrigger: checksPass` on both services. CI runs on every push to `main` (ci.yml), so checks exist. Risk: a push that triggers no checks never deploys (for example docs-only changes if filters are added later). Design D8 said `autoDeploy: true`; this is stricter and mitigates the "deploys on red CI" risk.
- `rootDir` NOT used (see Docker paths and static rows above). `buildFilter.paths` limits builds to `backend/**` and `frontend/**`.
- `CORS_ALLOWED_ORIGINS` and `VITE_API_BASE_URL` are plain `value:` (public, derived from fixed names) instead of `sync: false` as in tasks.md; that removes two manual dashboard steps and the CORS/redeploy loop. Only `DATABASE_URL` is `sync: false`.
- `region` not set (defaults to `oregon`, immutable). Pick it to match the Neon region before the first deploy.
- Only one DB variable: the direct URL serves both Alembic and the app.

## T4.2

Satisfied by `scripts/smoke.ps1` (see tasks.md). No new script. Gap review: HTTPS works through `Invoke-WebRequest`; the script defaults to local URLs, so deployed use must pass all three of `-BackendUrl`, `-FrontendUrl`, `-Origin`. Each check retries independently, so cold start is absorbed by the first check and the rest pass immediately. Not run against a live URL (nothing is deployed).

## T4.5

`openspec/config.yaml` flipped. The file was NOT valid YAML before (`rules.apply` was a list followed by mapping keys). `rules.apply` is now a mapping with a `rules` list plus `tdd` and `test_command`, matching what tasks.md requires (`apply.tdd`). Any tool reading `rules.apply` as a plain list must read `rules.apply.rules`. `verify.test_command` run from the repo root: 45 passed, 5 skipped (DB tests skip without `DATABASE_URL_TEST`).
