# Failure Log

## Phase 4: evolving core infrastructure could change a cluster fingerprint

- **Observed:** a cluster fingerprint anchored to the current primary qualifying device is stable
  in normal growth, but another device could later qualify and sort earlier, producing a different
  fingerprint for substantially the same structural cluster.
- **Risk:** repeated discovery could create a second `AbuseCluster` instead of expanding the
  existing record.
- **Fix:** exact fingerprint matching remains the first choice; persistence now falls back to a
  shared-device requirement plus at least 70% typed-member overlap. The original `clu_…` ID is
  retained, new members are added, and existing membership evidence is refreshed. An integration
  test forces a changed fingerprint and verifies one expanding cluster remains.

## Phase 3: optional context features could read future profile state

- **Observed:** a late leakage review found that three proposed features read customer or merchant
  attributes from normalized entity rows that later ingestion can update. Recomputing an old
  transaction could therefore produce a different vector even with a strict transaction-history
  cutoff.
- **Affected candidates:** `home_network_region_match`, `home_merchant_region_match`, and
  `merchant_risk_baseline`.
- **Fix:** all three were removed from `features-v1`; scoring input was split from historical
  records so current `status` and `failure_code` are structurally unavailable to `FeatureEngine`.
  A PostgreSQL regression test mutates those future entity profiles and proves the old vector is
  unchanged.

## Phase 3: feature snapshots initially allowed only one version

- **Observed:** the Phase 1 `transaction_features.transaction_id` uniqueness constraint prevented
  `features-v1` and a future feature version from coexisting for one transaction. Its required
  `max_source_event_time` also could not represent a transaction with no relevant history.
- **Cause:** the initial schema treated a feature row as one-per-transaction rather than an
  immutable, versioned snapshot.
- **Fix:** migration `8b73f4a91c2e` changes uniqueness to
  `(transaction_id, feature_version)`, adds a version-first lookup index, and permits a null
  historical watermark. Idempotency tests verify identical recomputation does not duplicate or
  overwrite a snapshot.

Copy this template for each genuine development or evaluation failure. Do not record hypothetical failures.

## Date

## What we attempted

## Observed failure

## Root cause

## Diagnosis

## Fix

## Result

## Lesson

---

## Date

2026-08-30

## What we attempted

Validated the first mixed `synthetic-v1` world for obvious single-feature class leakage.

## Observed failure

The validator reported that several device and home-region categorical values occurred only in legitimate traffic.

## Root cause

Initial abuse identity helpers used narrower device families and a fixed/default region pattern, while the legitimate population covered the full configured variety.

## Diagnosis

The generator had realistic relationship reuse but avoidable categorical shortcuts that a later model could exploit without learning coordinated behavior.

## Fix

Expanded abuse device/browser/OS variation and distributed abuse identities across the same regional domain used by legitimate traffic while preserving scenario-specific infrastructure reuse.

## Result

The 250-event deterministic mixed smoke world passes the overlap, topology, and leakage sanity validator without warnings.

## Lesson

Relationship realism alone is insufficient; synthetic validation must also test marginal value overlap before data is accepted.

---

## Date

2026-08-30

## What we attempted

Benchmarked and validated the default 10,000-event development dataset after the smaller smoke dataset passed.

## Observed failure

The validator found events just beyond the configured simulation end time.

## Root cause

Burst scheduling divided the time window using a floor-derived ring count. A final partial ring could therefore be placed at the exact window boundary before its within-ring offsets were added.

## Diagnosis

The defect appeared only when a scenario event count was not divisible by the burst size, demonstrating why development-scale validation is needed in addition to small tests.

## Fix

Calculated the number of burst rings with ceiling division and reserved an additional interval after the last ring.

## Result

The full 10,000-event dataset validates `PASS`; pure generation plus validation completed in approximately 0.42 seconds on the development host.

## Lesson

Temporal simulators must explicitly account for partial final buckets; small datasets may not exercise the boundary condition.
