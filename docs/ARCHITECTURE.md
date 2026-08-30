# Aegis Architecture

## Problem and current scope

Aegis targets coordinated payment abuse: behavior that becomes meaningful across transactions and linked entities rather than from one payment in isolation. Phase 1 established durable ingestion and normalized entities. Phase 2 added a deterministic synthetic payment world. Phase 3 adds reusable point-in-time feature vectors without training or scoring a model.

## Non-goals

This phase does not implement model training, predictions, graph detection or scoring, risk fusion, policy decisions, investigator prompts or LLM calls, a dashboard, realtime streaming, or production deployment claims. Kafka, Redis, Celery, Neo4j, and microservice boundaries are deliberately absent.

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

## Ground-truth separation

Ground-truth label, scenario, and ring identifiers exist on synthetic transaction records for training and evaluation only. Public `RawPaymentEvent` facts cannot carry them. An internal trusted context attaches them during synthetic ingestion. The runtime-safe `NormalizedTransaction`, `ScoringTransaction`, `FeatureVector`, and prediction contracts contain no ground-truth fields. Future feature assembly must preserve that separation and enforce point-in-time correctness.

## Planned intelligence pipeline

Later, and only after approval, the point-in-time features may feed a versioned model; relationship analysis may supply graph evidence; a deterministic policy layer may choose allowed actions; and an investigator may explain evidence already assembled by the system. None of those later components performs computation yet.
