# Failure Log

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
