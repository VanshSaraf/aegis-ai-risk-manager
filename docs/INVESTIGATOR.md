# Aegis Investigator

## Purpose and architecture

The investigator explains an already-computed Aegis decision. It is not a detector or policy
engine and cannot select ALLOW, VERIFY, HOLD, ESCALATE, or RECOMMEND_BLOCK.

```text
immutable feature/graph snapshots + model prediction + policy decision
                              -> EvidenceBuilder
                              -> truth-free EvidenceBundle
                                  -> deterministic explanation
                                  -> optional injected narrative provider
```

The structured bundle always remains in the response. Supplementary provider prose can never
replace evidence or modify the decision.

## Evidence

Controlled categories are TRANSACTION, BEHAVIOR, VELOCITY, GRAPH, POLICY, and CLUSTER. Evidence is
selected from a small explicit features-v1 mapping, named graph-v1 signals, frozen policy reasons,
and safe tokenized transaction references. Items are ranked deterministically by policy basis,
graph signals, cluster reference, structural concentration, velocity, and novelty, then capped at
eight.

Recent related transactions are capped at eight and must satisfy
`historical.event_time < current.event_time`. Feature and graph facts come from immutable
point-in-time snapshots. Because cluster membership rows can evolve, the report exposes only the
cluster ID frozen into the policy decision; it does not misrepresent later membership counts as
historical facts.

Ground truth, scenario, ring ID, persona, split, current transaction outcome, PAN, and CVV are not
part of EvidenceBundle.

## Deterministic and degraded behavior

Deterministic explanation is always available and clearly distinguishes the model action band from
graph corroboration. Graph evidence cannot be described as independently creating an underlying
HOLD. Language describes support, association, and uncertainty rather than confirmed fraud.

Default configuration:

```env
AEGIS_INVESTIGATOR_PROVIDER=disabled
AEGIS_INVESTIGATOR_MAX_NARRATIVE_CHARS=2000
```

No API key is required. The bundled runtime intentionally performs no network LLM call. A small
`InvestigatorProvider` interface supports dependency injection of a read-only provider. Disabled,
missing-key, unsupported-provider, exception, empty-response, and oversized-response cases all
return HTTP 200 with the deterministic report. Valid injected prose is length-bounded and remains
supplementary.

## API

After assessment:

```text
GET /api/v1/transactions/{public_id}/investigation
```

The endpoint is read-only and on-demand; it adds no persistence or migration. If the transaction
has not been assessed, it returns a conflict instead of silently creating a decision.

## Limitations

The model score is uncalibrated, explanations are rule-selected rather than causal, cluster counts
are unavailable as immutable historical snapshots, and evidence indicates patterns rather than
confirmed fraud. No SHAP, RAG, vector database, agent framework, arbitrary SQL, or mutation tool is
present.
