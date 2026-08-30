# Point-in-Time Graph Intelligence

## Scope and graph model

`graph-v1` is a deterministic structural assessment, not a fraud probability. It models a
heterogeneous identity graph with typed nodes:

- `CUSTOMER`
- `PAYMENT_INSTRUMENT`
- `DEVICE`
- `IP`
- `ADDRESS`

Allowed undirected relationships are customer-device, customer-instrument, customer-IP,
customer-address, and instrument-device. Each edge tracks first observation, latest observation
as of the cutoff, and observation count as of the cutoff.

Merchants are deliberately excluded from primary connectivity. A popular merchant would connect
otherwise unrelated customers into a giant component and make component structure misleading.
Merchant context remains available outside the identity graph.

## Point-in-time semantics

For transaction `T`, graph history satisfies `historical.event_time < T.event_time`. The current
transaction supplies candidate identities but its nodes and relationships are not observed until
after assessment. Equal-time transactions are assessed as one batch and then observed together,
so they cannot see each other.

The PostgreSQL provider recursively reconstructs only historical components touched by the
current entities using indexed transaction queries. It never reads accumulated `EntityEdge`
counts. Offline processing maintains an incremental typed adjacency state and computes before
observe. Both providers feed the same `GraphEngine`.

Current payment outcome, failure code, synthetic label, scenario, ring, persona, scenario-run ID,
and dataset version are absent from `GraphTransaction`. Ground-truth rings are used only by tests
after discovery.

## graph-v1 metrics

The machine-readable registry is `ml/artifacts/graph-v1/schema.json`.

### Local entity connectivity (7)

`device_customer_degree`, `device_instrument_degree`, `ip_customer_degree`, `ip_device_degree`,
`address_customer_degree`, `instrument_device_degree`, `instrument_customer_degree`.

### Component structure (8)

`component_node_count`, `component_edge_count`, `component_customer_count`,
`component_device_count`, `component_instrument_count`, `component_ip_count`,
`component_address_count`, `component_multipartite_density`.

Component metrics cover the union of historical components touched by current entities. Density
is not generic complete-graph density. Its denominator is the capacity of only allowed type pairs:

```text
C×D + C×I + C×IP + C×A + I×D
```

### Novelty and bridging (7)

`new_customer_device_edge`, `new_customer_instrument_edge`, `new_customer_ip_edge`,
`new_customer_address_edge`, `new_instrument_device_edge`, `preexisting_component_count`,
`components_bridged_by_transaction`.

### Bounded connectivity (1)

`customer_two_hop_customer_count_via_device_or_ip` counts other historical customers reachable
through the current device or IP. Traversal is bounded to two hops.

### Temporal structure (2)

`component_new_edges_10m` and `device_new_identities_10m` measure relationship expansion, not
transaction velocity.

## Structural signals and score

Named signals are:

- `DEVICE_MULTI_CUSTOMER_CONCENTRATION`
- `DEVICE_MULTI_INSTRUMENT_CONCENTRATION`
- `RAPID_RELATIONSHIP_EXPANSION`
- `MULTI_COMPONENT_BRIDGE`
- `DENSE_MULTI_ENTITY_STRUCTURE`

The bounded structural score combines:

```text
0.35 × identity concentration
+ 0.25 × cross-entity reuse
+ 0.25 × recent relationship expansion
+ 0.15 × multi-entity component structure
```

Every term is capped at one. The result means strength of suspicious coordinated graph structure;
it is not calibrated and must not be described as fraud probability.

## Structural cluster discovery

The detector evaluates final point-in-time components after chronological processing. A candidate
must have at least three customers, three instruments, and a device shared by at least three of
each. It must also have rapid expansion or at least twelve corroborating edges and a structural
score of at least `0.45`.

IP sharing alone, address sharing alone, large component size alone, or high degree alone cannot
create a cluster. This protects corporate/campus networks, households, power shoppers, and
travellers. Tests exercise each legitimate persona separately.

Detected IDs are Aegis-generated `clu_…` identifiers. Ground-truth ring IDs never enter detection
or membership evidence. A stable fingerprint derived from the primary qualifying device updates
the same evolving cluster; membership rows are unique per cluster and typed entity. Phase 4 uses
status `OPEN` only and implements no review workflow.

## Persistence and limitations

`GraphAssessmentSnapshot` is immutable and unique by `(transaction_id, graph_version)`. Identical
recomputation reuses the snapshot; mismatch raises a conflict. Different graph versions may
coexist. `max_source_event_time` is null without graph history and otherwise strictly earlier than
the assessed transaction.

The current custom adjacency implementation is appropriate for the Buildathon dataset and is
isolated behind graph state/engine interfaces. Production scale could replace component storage
and traversal without changing assessment contracts. Thresholds are interpretable development
rules, not ML-tuned decision thresholds, and no final risk fusion or policy action exists.
