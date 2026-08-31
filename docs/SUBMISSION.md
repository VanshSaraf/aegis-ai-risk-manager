# Aegis Submission Draft

## 1. Project title

**Aegis**

## 2. One-line description

A graph-assisted AI risk system that detects coordinated payment abuse across seemingly unrelated
accounts and explains the evidence behind every intervention.

## 3. Problem statement

Individual payments can look legitimate while coordinated identities reuse devices, instruments,
IPs, and addresses. Transaction-only controls can miss that network. Risk teams need earlier
structural evidence without opaque automation or future-data leakage.

## 4. What we built

Aegis is a working end-to-end prototype: immutable FastAPI ingestion, PostgreSQL persistence,
52 point-in-time behavioral features, 25 temporal graph metrics, a frozen LightGBM risk ranker,
a bounded policy, a truth-free investigator, a live operations dashboard, a synthetic traffic
simulation, and an artifact-backed Evaluation Lab.

## 5. Why Track 2 — AI Risk Manager

Aegis helps operators recognize coordinated abuse, choose bounded interventions, and understand
why a payment was flagged. It treats AI as one governed component of risk management rather than
an autonomous payment authority.

## 6. What makes it different

- It evaluates the network behind a payment, not only the payment row.
- Feature and graph state are reconstructed strictly before the current event.
- Model score and graph corroboration remain separate and auditable.
- Policy recommendations are deterministic and require human review for severe actions.
- Investigation occurs after the decision and cannot change it.
- The live simulation uses the exact external ingestion and assessment services.

## 7. Technical architecture

Payment events enter FastAPI and are durably recorded before normalization. A shared online/offline
engine computes `features-v1`; `graph-v1` reconstructs typed customer, instrument, device, IP, and
address relationships; `risk-lgbm-v2` emits an uncalibrated ranking score; `risk-policy-v2` maps
that score and corroborative graph evidence to ALLOW, VERIFY, HOLD, ESCALATE, or RECOMMEND_BLOCK;
EvidenceBuilder then creates a bounded truth-free investigation for the Next.js dashboard.

## 8. AI/ML usage and judgment

LightGBM ranks behavioral and relationship risk. The graph engine derives coordinated structure.
Business intervention is deliberately deterministic, versioned policy. The primary investigator
is deterministic and evidence-first, with only an optional read-only provider abstraction. No LLM
chooses thresholds, changes policy, or enters the critical payment decision path.

## 9. Evaluation methodology

The final `synthetic-v2` generator was hardened on a development seed, then its implementation,
configuration, schemas, split method, and model configuration were frozen. The final seed 88421
used a strictly temporal, abuse-ring-grouped 35,000/7,500/7,500 split. Candidate selection and
threshold choice used validation only. A fresh seed 91573 was evaluated after policy freeze, with
no subsequent retuning.

## 10. Key measured results

On the frozen synthetic-v2 held-out test, tabular, graph-only, and combined LightGBM achieved
PR-AUC 0.974894, 0.996506, and 0.998365. False positives were 83, 13, and 4 respectively. Combined
precision was 0.991525, recall 0.964948, and F1 0.978056. The fresh external seed produced PR-AUC
0.985832, demonstrating weaker but honestly retained generalization.

## 11. False-positive-cost consideration

An unconstrained cost-minimizing policy was too aggressive. Policy-v2 therefore searches only
among validation candidates satisfying predetermined synthetic abuse-capture, customer-friction,
severe-intervention, review-capacity, and cohort budgets. These costs are illustrative assumptions,
not Razorpay savings or production thresholds.

## 12. What broke and how we recovered

### The suspiciously perfect benchmark

The first hardened-looking `synthetic-v1` evaluation was almost perfect. A leakage audit did not
find a direct truth field or label alias. Instead, diagnostics showed that the generator was too
separable through velocity and relationship patterns: legitimate traffic lacked difficult shared
infrastructure and retry behavior, while abuse was too concentrated.

Reporting the perfect score would have been misleading. We preserved synthetic-v1 as a diagnostic
baseline, created `synthetic-v2` with legitimate hard negatives, slower and stealthier abuse, and
more topology diversity, then froze the generator and configuration before opening the final
seed. The defensible final combined result was 0.998365 PR-AUC with 4 false positives and 17 false
negatives—not a claim of production accuracy.

### The policy that optimized the wrong thing

Unconstrained policy-v1 cost minimization produced excessive legitimate friction. We preserved
that result, introduced explicit operating constraints, and froze risk-policy-v2 before running a
fresh external seed. Its external legitimate intervention rate still drifted to 11.17% against a
5% validation budget. We retained the miss without retuning because honest generalization evidence
is more valuable than a cosmetically perfect report.

## 13. Known limitations

All results use synthetic payment traffic; no real Razorpay data is included. Scores are
uncalibrated. Production fairness, drift, governance, latency at scale, and review capacity remain
unevaluated. Graph clustering can fragment groups. External policy friction exceeded one validation
budget. Economics are illustrative. Aegis makes bounded recommendations and never autonomously
applies a permanent block. No live LLM dependency is bundled.

## 14. Future production path

Replace the synthetic event source with tokenized payment events while preserving the ingestion,
point-in-time feature, graph, model, policy, and evidence boundaries. Then validate on governed
real data, calibrate scores, establish merchant- and cohort-aware operating constraints, perform
fairness and drift evaluation, integrate a human review workflow, and add monitored deployment
controls. Frozen versions and immutable evidence provide the audit trail for that path.
