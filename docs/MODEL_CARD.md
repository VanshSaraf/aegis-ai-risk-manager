# Aegis Model Card: risk-lgbm-v2

## Status and purpose

`risk-lgbm-v2` is the Phase 5 submission artifact: a LightGBM binary classifier for coordinated
payment abuse in Aegis's leakage-controlled synthetic benchmark. It emits an uncalibrated
`model_score`, not a fraud probability, policy action, or payment decision.

Production status: **not production validated**. Calibration status: **not calibrated**.

## Inputs

The combined model consumes exactly 77 registered, ordered point-in-time inputs: 52
`features-v1` values and 25 raw `graph-v1` metrics. Synthetic labels, scenarios, rings, personas,
public IDs, cluster IDs, current payment outcomes, and final accumulated graph state are excluded.

## Data, development discipline, and split

The final benchmark is `synthetic-v2-seed-88421-b4d7eb9e6d`: 50,000 transactions containing
46,500 legitimate and 3,500 coordinated-abuse transactions. `synthetic-v2` was designed using a
separate 20,000-event seed (24681) to add legitimate hard negatives, varied abuse speeds and
failure rates, and multiple topology variants per subtype. Generator/configuration hashes were
frozen before seed 88421 was generated or evaluated; the final seed was not used to redesign the
generator.

Features and graph state are computed chronologically before label partitioning. The strict
grouped temporal split contains 35,000 train, 7,500 validation, and 7,500 test rows. Its 130 abuse
rings form 130 isolated supergroups with no cross-ring customer, device, instrument, IP, or address
reuse. Ring counts are 92/19/19 across train/validation/test. Each partition contains all four
abuse subtypes; the test set was opened only after candidate, threshold, and generator freeze.

## Held-out synthetic results

| Model | PR-AUC | ROC-AUC | Precision | Recall | F1 | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|
| Deterministic graph detector | 0.158049 | 0.660610 | 0.310811 | 0.379381 | 0.341690 | 408 | 301 |
| Tabular LightGBM (52) | 0.974894 | 0.998004 | 0.849638 | 0.967010 | 0.904532 | 83 | 16 |
| Graph LightGBM (25) | 0.996506 | 0.999857 | 0.973896 | 1.000000 | 0.986775 | 13 | 0 |
| Combined LightGBM (77) | 0.998365 | 0.999886 | 0.991525 | 0.964948 | 0.978056 | 4 | 17 |

Graph inputs materially improved the combined classifier over tabular-only on this benchmark:
PR-AUC rose by 0.023471 and false positives fell from 83 to 4, with a small recall reduction of
0.002062 at validation-selected thresholds. This is evidence about this synthetic benchmark, not
a claim that graph inputs will improve production traffic.

Combined test recall by subtype was ACCOUNT_FARM 117/120 (0.975000), CARD_TESTING 128/130
(0.984615), COLLUSIVE_RING 117/120 (0.975000), and IDENTITY_ROTATION 106/115 (0.921739).
False positives by legitimate persona were 1/1,016 CORPORATE_OR_CAMPUS_NETWORK, 3/2,932
STANDARD_RETAIL, and zero for FAMILY_HOUSEHOLD, POWER_SHOPPER, and TRAVELLER.

## Selection and reproducibility

Three explicit candidates per model family were selected only on validation PR-AUC, with early
stopping and a validation-F1 threshold. The combined model selected `balanced-medium` at iteration
79 and threshold 0.0253487127. This is an experimental threshold, not a business-cost threshold.

Native save/reload reproduced all 7,500 validation scores with maximum absolute delta 0.0. A
same-environment deterministic replay also had delta 0.0. Cross-platform bit-for-bit equivalence
is not promised across LightGBM, operating-system, or CPU versions.

## Limitations

- All training and evaluation data come from one designed synthetic generator family; synthetic
  difficulty is not production realism.
- Distribution shift, adversarial adaptation, fairness, calibration, economic cost, production
  latency, governance, and monitoring remain unevaluated.
- Nineteen independent test rings support a controlled comparison but not broad statistical
  certainty, especially within subtype slices.
- Graph-only outperforming combined F1 at their independently selected thresholds shows that the
  current fusion and threshold objective are not globally optimized.
- No final risk fusion, policy, human-review workflow, explanations, or autonomous action exists.

The easier `risk-lgbm-v1` artifact is retained for reproducibility and diagnosis, not as the
submission headline. Full traceability is in `ml/artifacts/model-v2/benchmark.json`, with the
method in [ML_EVALUATION.md](ML_EVALUATION.md).
