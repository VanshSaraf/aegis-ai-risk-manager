# Aegis Synthetic Data Generation

## Purpose and boundaries

Aegis uses a deterministic synthetic payment world because real Razorpay transaction data is unavailable to this project and would introduce substantial privacy, security, and governance concerns. The generator exists to exercise ingestion, relationship persistence, and later defensive evaluation. Synthetic data does not establish real-world representativeness or production fraud-detection performance.

No model training, feature computation, graph scoring, policy decisions, or AI investigation happens during generation.

## Target and hidden truth

The eventual binary target is `LEGITIMATE` versus `COORDINATED_ABUSE`. Abuse subtype and ring membership are evaluation metadata, not separate prediction targets.

`RawPaymentEvent` contains payment facts only. The generator keeps label, scenario, ring, and persona in an internal `SyntheticGroundTruth` object. A trusted ingestion context attaches this metadata to `Transaction.ground_truth_*` columns and the applicable `ScenarioRun`; public API callers cannot submit those fields. Runtime-safe normalized, feature, and scoring contracts remain truth-free.

## Synthetic world

Persistent customers, payment instruments, devices, network identities, addresses, and merchants are generated and reused across events. Merchant categories include ecommerce, food, travel, electronics, fashion, gaming, subscription, and education, with overlapping skewed amount distributions.

Legitimate personas are:

- `STANDARD_RETAIL`
- `POWER_SHOPPER`
- `FAMILY_HOUSEHOLD`
- `CORPORATE_OR_CAMPUS_NETWORK`
- `TRAVELLER`

Households share addresses and networks, corporate/campus users share network infrastructure, power shoppers create legitimate velocity and instrument diversity, and travellers change region, network, or device. These are deliberate false-positive-pressure cases.

Coordinated-abuse scenarios are:

- `CARD_TESTING`: many instruments and accounts around constrained device/network pools, with mixed outcomes and overlapping amounts.
- `ACCOUNT_FARM`: newer and established accounts with shared devices, networks, and addresses.
- `IDENTITY_ROTATION`: customer and instrument identities rotate while infrastructure persists.
- `COLLUSIVE_RING`: partial, dense reuse among multiple accounts, instruments, devices, networks, and addresses.

Every abuse operation receives a stable `ring_*` identifier. Legitimate transactions never receive ring IDs.

## Reproducibility and time

Two explicit generator versions exist. `synthetic-v1` is retained at its canonical interface for
reproduction of the first benchmark. Retrospective Phase 5 diagnostics found its abuse velocity
and relationship patterns too easily separated from legitimate traffic, so it is not the
submission benchmark. `synthetic-v2` adds legitimate burst, retry, household, corporate, and
campus hard negatives plus multiple speed, failure-rate, entity-mix, and topology variants for
each abuse subtype. These are designed stress cases, not measured production behavior.

Configuration, root seed, and generator version determine the semantic event stream. All
randomness flows through named NumPy `Generator`/PCG64 streams derived from the root seed,
including separate population and scenario streams. This isolates unrelated scenarios from many
incidental changes elsewhere.

The offline simulation uses a configured UTC start time and duration, never wall-clock time. Events are returned in chronological order. Deterministic source references and event IDs preserve logical identity across same-seed runs; random database UUIDs and production public IDs are intentionally excluded from semantic determinism comparisons.

Each run records a config hash, class/scenario/persona counts, entity counts, simulation range, `DatasetVersion`, and one `ScenarioRun` for each generated scenario. Optional `manifest.json` and `events.jsonl` artifacts are written beneath the ignored `ml/datasets/generated/` tree.

## Prevalence and overlap

The default dataset has 10,000 transactions and approximately 7% coordinated abuse. This is configurable and is intentionally not a 50/50 primary dataset. Amounts are bounded integer paise drawn from skewed category distributions.

No single obvious fact is intended to determine the label. Both classes contain small and large payments, failures and successes, newer accounts, shared infrastructure, multiple instruments per device, and varied network, device, and merchant values. Abuse structure is expressed mainly through timing, repeated relationships, identity reuse, and infrastructure concentration.

The validator checks counts, timestamps, truth consistency, prevalence, class overlap, topology, and obvious single-field leakage. These are synthetic sanity checks, not proof of realism.

## Evaluation methodology

Train/validation/test construction is leakage-safe:

- Temporal partitions must respect event order.
- Abuse rings must remain wholly within one partition.
- Grouped splits should prevent linked identities or infrastructure from leaking across partitions where appropriate.
- Dataset, generator, configuration, and feature versions must be recorded together.

The offline pipeline implements this split methodology; generation itself still does not
train a model or expose truth to runtime inputs.

## Usage

```bash
python scripts/generate_synthetic.py --seed 42017 --transactions 10000
python scripts/generate_synthetic.py --scenario CARD_TESTING --seed 1234 --transactions 200
```

The database must be migrated before running the CLI. Generated artifacts are local and ignored by Git.

## Limitations

The simulation encodes assumptions chosen by this project, not measured Razorpay traffic. Frequencies, correlations, merchant mixes, and abuse strategies may differ materially from production. Later work must treat conclusions from synthetic evaluation as experimental and validate them against appropriately governed real evidence before any operational claim.
