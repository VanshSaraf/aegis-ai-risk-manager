# Aegis

Aegis is a graph-assisted system intended to detect coordinated payment abuse such as card-testing rings, account farms, identity rotation, and collusive payment clusters.

This repository implements the Phase 1 backend/data foundation, Phase 2 deterministic synthetic
payment world, Phase 3 point-in-time feature engineering, Phase 4 point-in-time graph intelligence,
Phase 5 leakage-controlled LightGBM training and held-out synthetic evaluation, and Phase 6
cost-aware bounded policy recommendations with an operational assessment API.

**Calibrated probabilities, SHAP, a bundled network LLM provider, realtime streaming,
and autonomous payment actions are not implemented.** `risk-lgbm-v2` produces an uncalibrated
model score. `risk-policy-v2` produces bounded recommendations; it performs no payment action.
AI-assisted investigation operates afterward on bounded deterministic evidence and cannot change
the recommendation.

## Architecture boundaries

- `apps/api` owns HTTP transport, orchestration, and persistence models.
- `packages/risk_engine/features` owns the shared online/offline point-in-time feature boundary.
- `packages/graph_engine` owns typed identity-graph state, graph-v1 assessments, and structural cluster discovery.
- `packages/synthetic` owns reproducible population, behavior, scenarios, manifests, and sanity validation.
- `ml/training` and `ml/evaluation` own offline assembly, grouped temporal splitting, training,
  diagnostics, and reproducible artifacts.
- `packages/policy_engine` owns cost profiles, validation-only threshold optimization, bounded
  runtime decisions, backtesting, and operational persistence.
- `packages/investigator` owns truth-free evidence bundles, point-in-time timelines, deterministic
  explanations, and the optional read-only provider boundary.
- `ml` and `configs` hold versioned offline artifacts and experiment configuration.
- PostgreSQL is the system of record. Each valid incoming event is committed to `raw_events` before normalization starts.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the detailed design.
See [docs/FEATURES.md](docs/FEATURES.md) for scoring-moment, window, registry, and leakage semantics.
See [docs/GRAPH_INTELLIGENCE.md](docs/GRAPH_INTELLIGENCE.md) for graph and cluster semantics.
See [docs/ML_EVALUATION.md](docs/ML_EVALUATION.md) and [docs/MODEL_CARD.md](docs/MODEL_CARD.md)
for the Phase 5 methodology, actual metrics, and limitations.
See [docs/POLICY_ENGINE.md](docs/POLICY_ENGINE.md) for Phase 6 score bands, graph corroboration,
cost assumptions, freeze discipline, and operational limitations.
See [docs/INVESTIGATOR.md](docs/INVESTIGATOR.md) for evidence selection, point-in-time timelines,
provider configuration, and degraded behavior.

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

Run the dashboard in a second terminal:

```bash
cd apps/web
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. The frontend uses `NEXT_PUBLIC_API_BASE_URL` (default
`http://localhost:8000`); the API permits `http://localhost:3000` by default through the
configurable `AEGIS_CORS_ALLOWED_ORIGINS` setting.

## Risk operations dashboard

The single-page dashboard shows truth-free operational counts, recent assessed and pending
transactions, policy actions, uncalibrated model scores, bounded point-in-time identity graphs,
and evidence-first investigations. Transaction selection updates the graph and investigation
workspace without navigation. Manual refresh and explicit loading, empty, pending, and backend
failure states are included.

## Demo

The live showcase is a small deterministic demo scenario, not a held-out evaluation. It sends
curated truth-free payment events through the real ingestion, features-v1, graph-v1,
risk-lgbm-v2, risk-policy-v2, and investigator pipeline.

1. Set `AEGIS_DEMO_MODE=true` in `.env` and start the API.
2. Start the frontend and open `http://localhost:3000`.
3. Click **Inject Abuse Ring** to establish a baseline and animate Identity Rotation events.
4. Inspect the changing point-in-time graph and automatically selected investigation.
5. Open **Evaluation Lab** for frozen held-out synthetic and external benchmark results.

Demo mutation endpoints are hidden with a 404 unless demo mode is explicitly enabled. Sessions
are bounded, ephemeral in-memory orchestration; PostgreSQL remains the transaction source of truth.

## Quality checks

```bash
make test
make lint
make ml-smoke
make policy-build
make policy-v2-freeze
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

## Leakage-controlled model benchmark

The normal training path tunes only on train/validation. Test evaluation requires an explicit flag:

```bash
python scripts/train_model.py --config configs/ml/model-v1.yaml
python scripts/train_model.py --config configs/ml/model-v2.yaml --evaluate-test
```

The submission artifact is `risk-lgbm-v2`, evaluated once on the frozen 50,000-event
`synthetic-v2` benchmark (seed 88421). On its held-out test partition, tabular-only PR-AUC was
0.974894 and combined PR-AUC was 0.998365; false positives fell from 83 to 4 while recall changed
from 0.967010 to 0.964948. These designed synthetic results do not estimate performance on
Razorpay or other production traffic. The easier `risk-lgbm-v1` benchmark remains available only
as a retrospective diagnostic baseline.

## Constrained bounded policy assessment

The submission-facing `risk-policy-v2` uses separate model and graph evidence; there is no weighted
fused score. It minimizes the balanced-v1 illustrative synthetic cost only among validation
candidates satisfying predetermined abuse-capture, customer-friction, severe-intervention,
human-review, and cohort budgets. Persona is offline validation metadata and never a runtime input.

Policy-v1 remains reproducible as a development failure: unconstrained cost optimization was
mathematically valid but created excessive customer friction. Build the preserved policy-v1 report
or the policy-v2 freeze with:

```bash
python scripts/build_policy_artifacts.py
python scripts/build_policy_v2_artifacts.py
```

Policy-v2 was frozen before the previously unseen 50,000-event synthetic-v2 seed 91573 was
generated. On that external held-out synthetic benchmark, it reduced legitimate intervention from
policy-v1's 25.27% to 11.17% and eliminated severe legitimate interventions, while allowing 2 abuse
transactions and producing higher remaining assumed abuse loss. Its external legitimate
intervention rate exceeded the 5% validation budget, an honestly retained generalization failure.

All monetary outputs and operating budgets are illustrative synthetic assumptions, not production
or Razorpay economics. The operational API defaults to risk-policy-v2 and reuses immutable feature,
graph, prediction, and versioned policy rows for repeated identical assessments.

## Evidence-first investigation

After a transaction is assessed, retrieve its structured explanation with:

```text
GET /api/v1/transactions/{public_id}/investigation
```

The response includes the model and policy basis, selected behavioral and graph evidence, safe
related entities, a bounded strictly-prior timeline, limitations, and an action-consistent next
step. No LLM key is required; deterministic explanation is the default. Optional injected provider
prose is supplementary, and provider failure degrades to the same deterministic HTTP 200 response.

## Implemented API

- `GET /health`
- `GET /ready`
- `POST /api/v1/transactions`
- `GET /api/v1/transactions`
- `GET /api/v1/transactions/{public_id}`
- `POST /api/v1/transactions/{public_id}/assess`
- `GET /api/v1/transactions/{public_id}/investigation`
- `GET /api/v1/transactions/{public_id}/graph`
- `GET /api/v1/dashboard/summary`
- `GET /api/v1/dashboard/transactions`
- `POST /api/v1/demo/sessions` (demo mode only)
- `POST /api/v1/demo/sessions/{session_id}/step` (demo mode only)
- `GET /api/v1/evaluation/summary`
- `GET /api/v1/entities/{entity_type}/{public_id}/neighbors`
