# Aegis

Aegis is a graph-assisted system intended to detect coordinated payment abuse such as card-testing rings, account farms, identity rotation, and collusive payment clusters.

This repository implements the Phase 1 backend/data foundation, Phase 2 deterministic synthetic payment world, Phase 3 point-in-time feature engineering, and Phase 4 point-in-time graph intelligence with deterministic structural cluster discovery.

**Model training or prediction, LightGBM, SHAP, final risk fusion, policy decisions, LLM investigation, frontend, and realtime streaming are not implemented.** The graph structural score is interpretable graph evidence, not fraud probability.

## Architecture boundaries

- `apps/api` owns HTTP transport, orchestration, and persistence models.
- `packages/risk_engine/features` owns the shared online/offline point-in-time feature boundary.
- `packages/graph_engine` owns typed identity-graph state, graph-v1 assessments, and structural cluster discovery.
- `packages/synthetic` owns reproducible population, behavior, scenarios, manifests, and sanity validation.
- `packages/graph_engine`, `packages/policy_engine`, and `packages/investigator` remain unimplemented boundaries.
- `ml` and `configs` hold future offline artifacts and versioned configuration.
- PostgreSQL is the system of record. Each valid incoming event is committed to `raw_events` before normalization starts.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the detailed design.
See [docs/FEATURES.md](docs/FEATURES.md) for scoring-moment, window, registry, and leakage semantics.
See [docs/GRAPH_INTELLIGENCE.md](docs/GRAPH_INTELLIGENCE.md) for graph and cluster semantics.

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

## Point-in-time feature snapshots

After transactions have been ingested, build or verify immutable `features-v1` snapshots:

```bash
python scripts/build_features.py --feature-version features-v1
```

The engine computes each vector before allowing the current transaction into history. Current
payment outcomes and synthetic truth are excluded. PostgreSQL and indexed in-memory providers
share the same `FeatureEngine` semantics and are covered by an exact parity test.

## Point-in-time graph assessments

After ingestion, build immutable `graph-v1` assessments and deduplicated structural clusters:

```bash
python scripts/build_graph.py --graph-version graph-v1
```

The graph uses customer, payment-instrument, device, IP, and address nodes. Merchants are excluded
from connectivity. PostgreSQL and offline processing both reconstruct only relationships created
strictly before each transaction; final accumulated edge state is never used for backfill.

## Implemented API

- `GET /health`
- `GET /ready`
- `POST /api/v1/transactions`
- `GET /api/v1/transactions`
- `GET /api/v1/transactions/{public_id}`
- `GET /api/v1/entities/{entity_type}/{public_id}/neighbors`
