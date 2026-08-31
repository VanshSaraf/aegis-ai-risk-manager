# Aegis Threat Model

## Scope

Aegis is a defensive system intended to identify coordinated payment abuse. It implements
validated ingestion, synthetic data, point-in-time tabular and graph intelligence, the trained
synthetic-benchmark `risk-lgbm-v2` model, bounded `risk-policy-v2` recommendations, and a read-only
evidence-first investigator. The model is uncalibrated and not production validated. No external
payment action is implemented.

## Data handling boundaries

- Domain references must be synthetic, tokenized, hashed, or fingerprinted identifiers.
- Aegis does not require or store card PAN or CVV.
- Names, email addresses, phone numbers, and full street addresses are outside the current data model.
- Ground-truth fields are reserved for synthetic training and evaluation data and are excluded from runtime scoring inputs.

## Capability boundaries

Aegis has no offensive capability. It does not generate attack instructions, probe payment systems, acquire credentials, or automate abuse. Graph and model components are intended only to analyze evidence already available to the defensive system.

The investigator is read-only, evidence-grounded, and outside the transaction decision path. An
optional injected LLM provider receives only a bounded truth-free EvidenceBundle. It cannot query
arbitrary data, mutate transactions, change policy, execute payment actions, or override the
deterministic recommendation. Provider failure falls back to deterministic explanation. Policy
`RECOMMEND_BLOCK` always requires human review and is not a block instruction.

Graph evidence is corroborative only. It cannot move a low-score ALLOW or intermediate VERIFY to
a severe action; only an existing model-score HOLD can be escalated. Offline persona metadata may
audit validation cohorts but is structurally excluded from runtime policy input.

Production authentication, authorization, retention, deployment isolation, and operational
controls remain outside this prototype and require a separate security review before real-data use.
