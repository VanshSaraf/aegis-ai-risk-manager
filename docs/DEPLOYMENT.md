# Public demo deployment

## Architecture

The supported public-demo topology is:

```text
Vercel (Next.js browser application)
  -> Render (FastAPI web service)
    -> Neon PostgreSQL
```

Deploy from the repository manually. Do not place hosting credentials or database URLs in source
control.

## Required environment variables

| Name | Service | Required | Safe example | Secret | Purpose |
|---|---|---:|---|---:|---|
| `NEXT_PUBLIC_API_BASE_URL` | Vercel | yes | `https://aegis-api.onrender.com` | no | Public Render origin used by the browser. It is embedded during `next build`. |
| `AEGIS_DATABASE_URL` | Render | yes | `postgresql://app:password@example-pooler.neon.tech/aegis?sslmode=require` | yes | Pooled Neon application connection. Plain `postgresql://` and `postgres://` URLs are normalized for asyncpg. |
| `AEGIS_MIGRATION_DATABASE_URL` | Render | recommended | `postgresql://owner:password@example.neon.tech/aegis?sslmode=require` | yes | Direct Neon connection used by Alembic; falls back to `AEGIS_DATABASE_URL` when omitted. |
| `AEGIS_CORS_ALLOWED_ORIGINS` | Render | yes | `http://localhost:3000,https://aegis.example.vercel.app` | no | Exact comma-separated browser origins; whitespace and empty entries are discarded. Do not use `*`. |
| `AEGIS_DEMO_MODE` | Render | yes for public demo | `true` | no | Enables the canonical synthetic-demo endpoints. |
| `AEGIS_ENVIRONMENT` | Render | yes | `production` | no | Identifies the deployment environment. |
| `AEGIS_SQL_ECHO` | Render | no | `false` | no | Keeps SQL statement logging disabled. |
| `AEGIS_INVESTIGATOR_PROVIDER` | Render | no | `disabled` | no | Keeps the deterministic investigator as the only provider. |
| `AEGIS_INVESTIGATOR_MAX_NARRATIVE_CHARS` | Render | no | `2000` | no | Existing bounded investigator setting. |
| `AEGIS_OPENAI_API_KEY` | Render | no | leave unset | yes | Only for a separately injected provider; the public demo does not need it. |

`PORT` is supplied by Render and must not be configured manually.

## Neon setup

1. Create a Neon project in a region reasonably close to the Render service.
2. Use the default database or create an `aegis` database.
3. In **Connect**, enable connection pooling and copy the pooled URL for
   `AEGIS_DATABASE_URL`. Its hostname contains `-pooler`.
4. Disable connection pooling in the same dialog and copy the direct URL for
   `AEGIS_MIGRATION_DATABASE_URL`.
5. Keep Neon-provided TLS parameters. Aegis converts `sslmode` to asyncpg's `ssl` parameter and
   removes only `channel_binding`, which asyncpg does not accept; TLS remains required.
6. Store both URLs as secret Render environment variables. Never add them to `.env.example`, a
   commit, a build log, or Vercel.

The pooled URL is preferred for normal public requests because it protects the database's direct
connection limit. Neon recommends a direct URL for schema migration tools, so Alembic uses the
optional migration URL when supplied.

## Render backend setup

Create a **Python 3** web service from the repository with:

| Setting | Value |
|---|---|
| Root Directory | repository root (leave blank) |
| Python version | `3.12.14`, pinned by `.python-version` |
| Build Command | `pip install .` |
| Health Check Path | `/health` |

The repository root is required. The API imports monorepo packages and loads committed files from
`configs/` and `ml/artifacts/`.

For a free Render web service, which does not provide a pre-deploy command, use:

```bash
alembic upgrade head && uvicorn apps.api.app.main:app --host 0.0.0.0 --port $PORT
```

For a paid service, prefer this separation:

```text
Pre-Deploy Command: alembic upgrade head
Start Command:      uvicorn apps.api.app.main:app --host 0.0.0.0 --port $PORT
```

Both commands run from the repository root. Migrations do not run in imports, requests, `/health`,
or `/ready`.

## Vercel frontend setup

Import the same repository as a Vercel project and configure:

| Setting | Value |
|---|---|
| Root Directory | `apps/web` |
| Framework Preset | Next.js |
| Install Command | `npm ci` |
| Build Command | `npm run build` |
| Output Directory | framework default |
| Node.js Version | `20.x` |

Set `NEXT_PUBLIC_API_BASE_URL` to the final HTTPS Render origin without a trailing slash. The
client also removes one trailing slash defensively. Because `NEXT_PUBLIC_` values are embedded in
the browser bundle at build time, set the Render URL before the final production build and redeploy
after changing it.

## CORS

Set `AEGIS_CORS_ALLOWED_ORIGINS` to exact origins, for example:

```text
http://localhost:3000,https://aegis.example.vercel.app
```

Include the production Vercel origin. Add a stable custom-domain origin if one is attached. Do not
add arbitrary preview origins or `*`; credentials are disabled and only `GET`/`POST` with the
existing headers are allowed.

## Health checks

- Render health check: `GET /health` must return `200 {"status":"ok"}`.
- Deployment readiness: `GET /ready` must return `200` with database `available`.
- `/health` intentionally does not query the database; `/ready` does.

## Verification

After Render is healthy and before publishing the frontend:

1. Open `/health`, `/ready`, and `/api/v1/evaluation/summary` on the Render origin.
2. Run `AEGIS_API_BASE_URL=https://<render-origin> python scripts/smoke_submission.py` locally.
3. Confirm the ordinary transaction, assessment, investigation, graph, entity, evaluation,
   canonical simulation, replay, and truth-exclusion checks pass.
4. Set the Render origin in Vercel, build the production deployment, and open `/` and
   `/evaluation`.
5. Confirm the browser console has no CORS or request failures.

## Free-tier cold start

A free Render service can spin down while idle. The first request afterward can take noticeably
longer or temporarily show the dashboard's existing backend-unavailable state. Retry after the
service wakes. Aegis does not add background polling or an external keep-alive.

## Public synthetic-demo state limitation

Demo session IDs are unique, high-entropy identifiers. Up to six sessions coexist in one API
process; the oldest in-memory session is evicted when the bound is exceeded. A visitor who somehow
obtains another visitor's session ID can advance that session, and sessions disappear when the
Render process restarts or spins down.

All visitors share the same PostgreSQL-backed dashboard. Each completed canonical session adds 30
transactions, so database rows grow with public use even though the in-memory registry is bounded.
This is acceptable for a monitored, short-lived public demo, not for tenant-isolated production.
Monitor Neon storage and reset or replace the demo database manually when appropriate.
