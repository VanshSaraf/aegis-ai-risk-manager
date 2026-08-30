# Aegis Policy Engine

## Scope and score semantics

The policy layer converts the frozen `risk-lgbm-v2` output and separate `graph-v1` evidence into
bounded recommendations. The model output is an **uncalibrated score, not a fraud probability**.
The engine has no external payment adapter and executes no payment action.

There is no weighted model/graph score. `risk-lgbm-v2` already consumes all 25 registered
`graph-v1` metrics, so numerically adding the structural score would double-count graph evidence
without calibration. `ml_score` and `graph_score` remain separate and persisted `fused_score` is
`NULL`.

## Policy-v1 development result

`risk-policy-v1` minimized illustrative synthetic validation cost subject mainly to score-band
structure. This was mathematically correct but operationally aggressive. On the now-developmental
seed 88421 TEST partition it produced 1,017 false positives, touched INR 44,10,560.75 of legitimate
amount, and severely intervened on 32.88% of POWER_SHOPPER and 91.63% of TRAVELLER transactions.
The issue was not a model or implementation bug: the objective omitted explicit friction,
capacity, and cohort budgets. Policy-v1 and its artifacts remain preserved as a reproducible
development lesson, but it is not the runtime default.

## Policy-v2 constrained optimization

`risk-policy-v2` minimizes the same `balanced-v1` illustrative synthetic cost, but only among
validation candidates satisfying these predetermined **ILLUSTRATIVE SYNTHETIC OPERATING
ASSUMPTIONS**:

- abuse intervention recall at least 95%
- legitimate intervention rate at most 5%
- legitimate severe-intervention rate at most 1.5%
- total human-review rate at most 2%
- severe-intervention rate for every individual legitimate validation persona at most 10%

Persona exists only on offline `BacktestExample` metadata. It is unavailable to `PolicyInput` and
does not alter per-transaction runtime decisions. Production cohort budgets would require actual
merchant preferences, review capacity, historical loss, and customer-friction evidence.

The optimizer derives candidates from 41 evenly spaced validation-score quantiles, 0 and 1, the
configured thresholds, the Phase 5 threshold, and policy-v1 thresholds, removing exact duplicates.
Tied feasible candidates prefer lower legitimate amount touched, fewer human reviews, fewer
legitimate severe interventions, fewer interventions, higher precision, and then higher verify and
hold thresholds. Zero feasible candidates fails explicitly; constraints are never relaxed.

Validation produced 21 distinct candidates, 210 ordered threshold pairs, and 9 feasible pairs.
The frozen thresholds are:

- score below `0.0054821592162737475`: `ALLOW`
- score from that value to below `0.9622880006886806`: `VERIFY`
- score at or above `0.9622880006886806`: `HOLD`

Graph evidence can only strengthen an existing HOLD. At least two named strong signals produce
ESCALATE; at least three plus an active cluster produce RECOMMEND_BLOCK. Both require human review.
Graph evidence cannot severe-escalate ALLOW or VERIFY. Cluster-only, IP-only, and address-only
evidence are insufficient.

## Freeze and external evaluation discipline

Policy-v2 was optimized on the seed 88421 validation partition and frozen at
`2026-08-30T17:00:51.502414+00:00`. Its freeze states
`external_seed_evaluated_at_checkpoint: false`. Only afterward was the untouched 50,000-event
synthetic-v2 seed 91573 generated, scored, and evaluated as a whole external synthetic benchmark.
No part of that world trained the model or selected policy thresholds, constraints, graph rules,
or costs.

On seed 91573, policy-v2 reduced legitimate intervention from policy-v1's 25.27% to 11.17% and
legitimate severe intervention from 23.67% to 0%. The 5% aggregate validation budget did not
generalize: every external persona exceeded 5% intervention, although no persona exceeded the 10%
severe-intervention validation guardrail. This is distribution-shift evidence, not a reason to
retune on the external world.

The lower-friction policy traded away synthetic economic protection. Policy-v2 allowed 2 abuse
transactions and INR 14,460.39 of abuse amount, increased remaining assumed abuse loss, and had a
higher total assumed cost than policy-v1. All such monetary values are **ILLUSTRATIVE SYNTHETIC
POLICY ASSUMPTIONS**, not Razorpay economics or production savings.

## Runtime and persistence boundary

The runtime path is transaction -> features-v1 -> graph-v1 -> risk-lgbm-v2 -> immutable
RiskPrediction -> risk-policy-v2 -> immutable PolicyDecision -> audit events. It does not load
costs, personas, validation distributions, labels, scenarios, rings, splits, or dataset metadata.
Repeated identical assessments reuse versioned rows. A same-version mismatch is a conflict, while
policy-v1 and policy-v2 decisions may coexist for the same prediction.

## Limitations

The model and both policies are validated only on one designed synthetic generator family. They
do not establish calibration, production economics, fairness, operational capacity, a production
threshold, or production generalization. Graph clusters remain corroborative because graph-v1
over-fragmented the harder synthetic-v2 benchmark and was deliberately not retuned.
