# Aegis Architecture

## Problem and current scope

Aegis targets coordinated payment abuse: behavior that becomes meaningful across transactions and
linked entities rather than from one payment in isolation. Phase 1 established durable ingestion
and normalized entities. Phase 2 added a deterministic synthetic payment world. Phase 3 added
point-in-time features, Phase 4 added graph intelligence, and Phase 5 adds offline
leakage-controlled training and a portable score-only model boundary.

## Non-goals

This phase does not implement final risk fusion, policy decisions, investigator prompts or LLM
calls, a dashboard, realtime streaming, or production deployment claims. Kafka, Redis, Celery,
Neo4j, and microservice boundaries are deliberately absent.

## Synthetic-world data flow

```text
Versioned configuration + seed
             ↓
Synthetic World + hidden SyntheticGroundTruth
             ↓
RawPaymentEvent facts + trusted internal context
             ↓
Existing ingestion service
             ↓
RawEvent → normalized entities/Transaction → EntityEdge → AuditEvent
```

Synthetic generation deliberately uses the real ingestion service. It therefore exercises raw-event durability, entity resolution, relationship upserts, audit creation, and transaction boundaries instead of creating ORM transactions through a special shortcut. `DatasetVersion` records the reproducible configuration and manifest; `ScenarioRun` records each included scenario and links its transactions.

## Current data flow

1. FastAPI validates a `RawPaymentEvent` contract.
2. The service commits its original JSON payload as a `RawEvent` with receipt metadata.
3. A separate database transaction resolves tokenized entities, writes the normalized transaction, upserts relationship observations, writes an audit event, and marks the raw event processed.
4. If normalization fails, that second transaction is rolled back. The already-committed raw event is marked `FAILED` with a bounded diagnostic message, so no partial normalized state remains.
5. Read APIs expose normalized transaction metadata and direct edge neighbors only.

Raw payloads and audit records are append-only by application-service policy. A raw event's processing status and error are operational metadata and may transition; its identity and payload are not rewritten.

## Storage decisions

PostgreSQL is the system of record because this phase needs atomic multi-table writes, explicit constraints, JSONB for versioned payloads, durable auditability, and indexed temporal queries. UUIDs are internal primary keys. Public references are sortable ULID-style identifiers with controlled prefixes. Monetary values use integer paise. Timestamps are timezone-aware and represent distinct event, receipt, and processing moments.

Entity edges are stored relationally because only direct relationship persistence and neighbor lookup are required now. A compound uniqueness constraint prevents duplicate logical edges; repeat observations atomically advance `last_seen_at` and `observation_count`.

No PAN, CVV, name, email, phone number, or street address is required. Inputs use synthetic source references, hashes, or fingerprints.

## Point-in-time feature boundary

The future risk model will never query storage directly. The implemented feature path is:

```text
Historical state -> HistoryProvider -> FeatureEngine -> FeatureVector
                                                     -> TransactionFeature
```

`FeatureEngine` owns one set of feature definitions for online and offline use. The PostgreSQL
provider enforces `event_time < current.event_time` in SQL. The indexed in-memory provider is
updated only after a transaction's vector is computed and validated; equal-time transactions are
handled as a batch and cannot see each other. Final `EntityEdge` state is excluded because it can
contain observations from the future.

Current outcome is structurally absent from the engine's scoring-context type. Mutable customer
and merchant profile fields are also absent from `features-v1`, because their normalized entity
rows may be updated by later ingestion and are not immutable point-in-time snapshots.

Feature snapshots are immutable and unique by `(transaction_id, feature_version)`. Their
`max_source_event_time` is null without relevant history and otherwise strictly earlier than the
current transaction. See [FEATURES.md](FEATURES.md) for the complete registry and semantics.

## Point-in-time graph boundary

Graph intelligence is independent from `features-v1`:

```text
Raw Transaction -> features-v1 -------------------┐
                                                  │
Historical identity transactions -> GraphEngine  │
                                  -> graph-v1     │
                                  -> structural clusters
                                                  │
                           [future model boundary]
```

`GraphEngine` receives a temporally safe typed graph reconstructed from transactions strictly
before the current event. Offline batches compute before observe; PostgreSQL recursively loads
only components touched by current identities. Neither path reads final `EntityEdge` state.
Merchants are excluded from connectivity to prevent popular merchants joining unrelated users.

`graph-v1` produces structural metrics, named evidence signals, and a bounded structural score.
The deterministic cluster detector requires corroborating customer, instrument, device, and
relationship-expansion evidence; IP or address sharing alone is insufficient. Assessments are
immutable by `(transaction_id, graph_version)`. See
[GRAPH_INTELLIGENCE.md](GRAPH_INTELLIGENCE.md).

## Ground-truth separation

Ground-truth label, scenario, and ring identifiers exist on synthetic transaction records for training and evaluation only. Public `RawPaymentEvent` facts cannot carry them. An internal trusted context attaches them during synthetic ingestion. The runtime-safe `NormalizedTransaction`, `ScoringTransaction`, `FeatureVector`, and prediction contracts contain no ground-truth fields. Future feature assembly must preserve that separation and enforce point-in-time correctness.

## Offline model boundary

`risk-lgbm-v2` consumes exactly the registered 52 features-v1 and 25 graph-v1 raw metrics. Offline
assembly keeps evaluation truth separate, computes point-in-time history before chronological
group splitting, and serializes a schema-validated LightGBM model. Runtime inference returns only
an uncalibrated `model_score`.

## Bounded policy and operational assessment

The submission-facing decision path is:

```text
seed 88421 VALIDATION metadata -> cost objective + operating constraints
                                             -> frozen risk-policy-v2 thresholds

features-v1 + graph-v1 -> risk-lgbm-v2 -> uncalibrated model score
graph-v1 --------------------------------> separate corroborating evidence
                                             -> risk-policy-v2 -> bounded action
```

The offline optimizer may read labels, amounts, personas, and validation distributions. It uses
them only to select and freeze global thresholds subject to abuse-capture, legitimate-friction,
severe-intervention, review-capacity, and cohort budgets. Runtime policy does not receive or load
that evaluation metadata, cost profiles, or operating constraints.

`risk-policy-v2` maps the score into ALLOW, VERIFY, or HOLD, then permits named graph-v1 evidence
to corroborate only an existing HOLD as ESCALATE or, with stricter evidence and an active cluster,
RECOMMEND_BLOCK. There is no weighted fused score because the model already consumes graph
metrics. Model score, structural score, and evidence remain separately traceable. Policy-v1 is
retained as an unconstrained development policy for reproducibility and comparison.

The API assessment path reuses immutable point-in-time feature and graph snapshots, loads the
frozen model, persists versioned prediction and decision rows, and writes truth-free audit events.
It has no payment-action adapter. Future model and policy versions can coexist; a mismatch under
the same version is rejected. See [POLICY_ENGINE.md](POLICY_ENGINE.md).

The investigator boundary remains unimplemented. Any future LLM must be read-only,
evidence-grounded, and outside the transaction decision path.
