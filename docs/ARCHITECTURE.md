# Aegis Architecture

## Problem and current scope

Aegis targets coordinated payment abuse: behavior that becomes meaningful across transactions and linked entities rather than from one payment in isolation. Phase 1 establishes durable ingestion, normalized entities, relationship observations, contracts, and version registries. It gives later intelligence work a stable base without implementing that intelligence early.

## Non-goals

This phase does not implement transaction risk scoring, temporal feature computation, graph algorithms, policy decisions, synthetic scenario generation, investigator prompts or LLM calls, a dashboard, or production deployment claims. Kafka, Redis, Celery, Neo4j, and microservice boundaries are deliberately absent.

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

## Storage and model boundary

The future risk model will never query storage directly. The planned path is:

```text
PostgreSQL/history -> FeatureEngine -> FeatureVector -> RiskModel
                                             |
                                  same feature implementation
                                  for training and inference
```

This prevents storage details and point-in-time query behavior from leaking into model code. `FeatureVector` is an explicit domain contract and the reserved `packages/risk_engine/features` boundary will hold shared feature implementations.

## Ground-truth separation

Ground-truth label, scenario, and ring identifiers exist on synthetic transaction records for training and evaluation only. The runtime-safe `ScoringTransaction`, `FeatureVector`, and prediction contracts contain no ground-truth fields. Future feature assembly must preserve that separation and enforce point-in-time correctness.

## Planned intelligence pipeline

Later, and only after approval, deterministic temporal features will feed a versioned LightGBM model; relationship analysis will supply graph evidence; a deterministic policy layer will choose allowed actions; and an investigator may explain evidence already assembled by the system. The current repository contains persistence contracts for versioning and outputs, but none of these components performs computation yet.
