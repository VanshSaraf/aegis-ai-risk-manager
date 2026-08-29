# Aegis

Aegis is a graph-assisted system intended to detect coordinated payment abuse such as card-testing rings, account farms, identity rotation, and collusive payment clusters.

This repository currently implements only the Phase 1 backend and data foundation: typed contracts, PostgreSQL persistence, raw-event preservation, transaction normalization, entity/edge maintenance, audit records, retrieval APIs, migrations, and tests.

**Risk scoring, graph abuse detection, policy decision logic, synthetic data generation, and LLM investigation are not implemented yet.** No endpoint returns placeholder scores or fake AI output.

## Architecture boundaries

- `apps/api` owns HTTP transport, orchestration, and persistence models.
- `packages/risk_engine/features` reserves the shared training/inference feature boundary.
- `packages/graph_engine`, `packages/policy_engine`, `packages/investigator`, and `packages/synthetic` reserve cohesive future component boundaries without pretending those components exist.
- `ml` and `configs` hold future offline artifacts and versioned configuration.
- PostgreSQL is the system of record. Each valid incoming event is committed to `raw_events` before normalization starts.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the detailed design.

## Local development

Requirements: Docker with Compose, or Python 3.12+ and PostgreSQL 16.

```bash
cp .env.example .env
docker compose up --build
```

The API is available at `http://localhost:8000`; OpenAPI documentation is at `/docs`. The API container waits for PostgreSQL health, applies Alembic migrations, then starts FastAPI.

For a host-based workflow:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
uvicorn apps.api.app.main:app --reload
```

## Quality checks

```bash
make test
make lint
```

Integration tests require `AEGIS_TEST_DATABASE_URL` pointing to a disposable PostgreSQL database. They skip explicitly when it is absent.

## Implemented API

- `GET /health`
- `GET /ready`
- `POST /api/v1/transactions`
- `GET /api/v1/transactions`
- `GET /api/v1/transactions/{public_id}`
- `GET /api/v1/entities/{entity_type}/{public_id}/neighbors`
