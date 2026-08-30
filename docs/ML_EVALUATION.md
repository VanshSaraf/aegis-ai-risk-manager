# Phase 5 ML Evaluation

## Experimental question

Phase 5 tests whether raw point-in-time graph metrics improve coordinated-abuse detection beyond
point-in-time tabular behavior and velocity features. It compares 52-feature tabular, 25-metric
graph, and 77-input combined LightGBM models. The frozen `graph-v1` structural detector and a
class-prior dummy classifier are non-ML baselines.

## Why the first benchmark was replaced

The original 50,000-event `synthetic-v1` result was nearly perfect. Retrospective diagnostics did
not find truth fields or exact label aliases, but showed inadequate marginal overlap: for example,
`ip_txn_count_10m` alone had training ROC-AUC 0.946293, with legitimate p99 0 and abuse median 5.
A transaction-only family scored test PR-AUC 0.305603, while adding customer history reached
0.986052 and the 46 non-relational features reached 1.0. The result was therefore dominated by
synthetic velocity and relationship separability rather than a proven implementation leak.

`synthetic-v2` retains deterministic v1 behavior while adding legitimate burst/retry/shared-
infrastructure hard negatives and four abuse strategy variants per subtype. The v2 development
seed was 24681. After validation, generator implementation, configuration, feature/graph schemas,
training configuration, and split method were hashed in `model-v2/freeze.json`; only then was the
final seed 88421 evaluated once.

## Leakage-controlled assembly and split

Each current event is assessed before entering feature or graph history. Labels, scenarios, rings,
personas, timestamps, and typed abuse entities remain evaluation metadata; the model matrix is
built only from registered schemas.

Union-find joins abuse rings that share customer, device, payment-instrument, IP, or address
infrastructure, then the splitter searches for strict chronological boundaries near 70% and 85%
without dividing a resulting supergroup. The final boundaries produced 35,000/7,500/7,500 rows
and 92/19/19 rings. Ring subtype counts were train 20 ACCOUNT_FARM, 28 CARD_TESTING, 20
COLLUSIVE_RING, 24 IDENTITY_ROTATION; validation 4/6/4/5; test 4/6/4/5. There were 130 rings,
130 supergroups, and no shared cross-ring infrastructure.

## Model selection and sealed test

Three explicit LightGBM candidates per family use deterministic single-thread CPU settings.
Validation alone controls early stopping, selection by PR-AUC, and the threshold maximizing
validation F1. Test evaluation requires `--evaluate-test`. Average precision is primary because
abuse is the minority class; ROC-AUC, precision, recall, F1, confusion counts, FPR, and FNR are
also recorded.

The final training-matrix audit found no forbidden, constant, near-constant, non-finite, or exact-
label-alias columns. The strongest single feature was `device_unique_customers_1h` at directional
ROC-AUC 0.788913, below the 0.995 investigation threshold.

## Final results and interpretation

Held-out metrics are reported in [MODEL_CARD.md](MODEL_CARD.md). Combined PR-AUC was 0.998365
versus 0.974894 tabular-only; combined reduced false positives from 83 to 4 and raised F1 from
0.904532 to 0.978056, while recall changed from 0.967010 to 0.964948. Graph-only reached F1
0.986775 and recall 1.0 at its own threshold, so the evidence supports useful graph information but
does not establish that the present combined threshold is optimal for every objective or subtype.

The cluster diagnostic found 19 test truth rings and 223 discovered clusters touching test; 13
truth rings had best typed-entity Jaccard overlap at least 0.5, and median best overlap was 1.0.
This structural-recovery diagnostic is separate from transaction classification.

## Reproducibility and limitations

Artifacts record canonical hashes for configurations, schemas, split manifest, and the pre-test
freeze. Native reload and same-environment replay each produced maximum prediction delta 0.0.
Cross-platform equivalence is not guaranteed.

These results demonstrate controlled recoverability in a designed synthetic environment. They do
not establish production performance, calibration, robustness to distribution shift, economic
policy suitability, or representativeness of Razorpay traffic.
