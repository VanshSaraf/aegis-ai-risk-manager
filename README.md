# Aegis

Aegis is a graph-assisted system intended to detect coordinated payment abuse such as card-testing rings, account farms, identity rotation, and collusive payment clusters.

This repository implements the Phase 1 backend/data foundation and the Phase 2 deterministic synthetic payment world. Synthetic legitimate personas and coordinated-abuse rings flow through the real ingestion pipeline and produce versioned manifests, scenario runs, ground truth, entities, edges, and audit records.

**Risk scoring, feature computation, graph abuse detection, policy decision logic, model training, and LLM investigation are not implemented.** No endpoint returns placeholder scores or fake AI output.

## Architecture boundaries

- `apps/api` owns HTTP transport, orchestration, and persistence models.
- `packages/risk_engine/features` reserves the shared training/inference feature boundary.
- `packages/synthetic` owns reproducible population, behavior, scenarios, manifests, and sanity validation.
- `packages/graph_engine`, `packages/policy_engine`, and `packages/investigator` remain unimplemented boundaries.
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

## Synthetic generation

After applying migrations, generate a mixed dataset or an isolated scenario:

```bash
python scripts/generate_synthetic.py --seed 42017 --transactions 10000
python scripts/generate_synthetic.py --scenario CARD_TESTING --seed 1234 --transactions 200
```

The CLI validates before ingestion and optionally writes `manifest.json` and `events.jsonl` beneath `ml/datasets/generated/`, which is ignored by Git. See [docs/DATA_GENERATION.md](docs/DATA_GENERATION.md).

## Implemented API

- `GET /health`
- `GET /ready`
- `POST /api/v1/transactions`
- `GET /api/v1/transactions`
- `GET /api/v1/transactions/{public_id}`
- `GET /api/v1/entities/{entity_type}/{public_id}/neighbors`
