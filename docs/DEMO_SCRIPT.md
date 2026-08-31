# Aegis 5-Minute Demo Script

Target speaking time: **4:40–4:50**. Keep the dashboard open at `/` and Evaluation Lab available
at `/evaluation`. Start from a fresh database with simulation mode enabled.

## 0:00–0:25 — Problem and pitch

“Individual payments can look legitimate while the accounts behind them quietly share devices,
cards, IPs, and addresses. Aegis is a graph-assisted AI risk manager that detects that coordinated
payment abuse and explains the evidence behind every intervention. Individual payments can look
legitimate. Aegis detects the network behind them.”

## 0:25–0:50 — Product and architecture

Show the empty or baseline operations dashboard.

“Every payment enters one pipeline: immutable ingestion, 52 point-in-time behavioral features,
25 graph metrics, the frozen risk-lgbm-v2 ranker, bounded risk-policy-v2, and then EvidenceBuilder.
The investigator is after the decision—it can explain a recommendation but never change it.”

## 0:50–1:50 — Synthetic Traffic Simulation

Point to **Synthetic Traffic Simulation**, then click **Inject Abuse Ring**.

“This creates 12 legitimate-looking baseline payments, then injects 18 Identity Rotation events.
Customers and instruments rotate while a device and IP persist. These are synthetic events, but
they use exactly the same API and risk services as an external payment source.”

As the queue and graph update:

“Watch new transactions arrive, the identity graph expand, the model score rise, and named graph
signals appear: multi-customer device concentration, multi-instrument concentration, rapid
relationship expansion, and dense multi-entity structure.”

At completion:

“The final real action is VERIFY at roughly a 0.9525 uncalibrated ranking score. The simulator
generates traffic, but it cannot choose the model score or policy outcome. That separation is why
this is a real system demonstration rather than a scripted decision.”

## 1:50–2:40 — Investigation

Keep the final transaction selected and show the graph and investigation.

“The operator sees the score and structural evidence separately. Aegis ranks bounded evidence,
shows safe tokenized relationships, lists only transactions strictly earlier than this payment,
and recommends the configured step-up verification.”

Point to the timeline and limitations.

“There is no ground truth, ring ID, persona, dataset split, current outcome, or fraud probability
in this report. The explanation is deterministic by default, needs no API key, and cannot mutate
the policy decision.”

## 2:40–3:35 — Evaluation Lab

Open `/evaluation`.

“This page reads frozen artifacts; it does not recompute or hand-enter metrics. On the held-out
synthetic-v2 test, tabular PR-AUC was 0.9749, graph-only 0.9965, and combined 0.9984.”

Point to false positives.

“The false-positive story is 83 for tabular, 13 for graph, and 4 for combined. Graph-only retained
the strongest thresholded recall and F1; combined achieved the best ranking PR-AUC.”

Point to external evaluation and limitation copy.

“A fresh post-freeze seed was weaker at 0.9858 PR-AUC. Policy friction also missed its external
budget. We did not retune after seeing that result.”

## 3:35–4:10 — AI and engineering judgment

“LightGBM handles behavioral risk ranking. The temporal graph captures coordinated structure.
Deterministic policy handles business intervention with human-review safeguards. The investigator
explains an already-made decision. An LLM is never used to approve a payment, choose a threshold,
or execute policy, and normal operation has no live network AI dependency.”

## 4:10–4:35 — What broke

“Our first synthetic-v1 model looked almost perfect. We found no direct label leak; the generator
was simply too separable through velocity and relationship patterns. Publishing that score would
have been misleading. We preserved the failure, added legitimate hard negatives and stealthier
abuse in synthetic-v2, froze the design before the final seed, and accepted a more defensible
result. We applied the same discipline when an unconstrained policy caused too much friction.”

## 4:35–4:50 — Limitations and close

“Aegis currently runs on synthetic payment traffic. It is not calibrated or production validated,
and it never autonomously blocks. But the data source can be replaced without changing the risk,
policy, or evidence boundaries. Individual payments can look legitimate. Aegis detects the network
behind them.”
