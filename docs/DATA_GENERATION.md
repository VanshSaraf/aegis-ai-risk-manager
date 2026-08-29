# Aegis Data Generation

## Current status

Synthetic transaction generation is planned for Phase 2 and is not implemented. Phase 1 provides only schema fields and version registries needed to store future scenario runs and dataset metadata.

## Planned requirements

- Generate both legitimate traffic and coordinated-abuse scenarios with explicit ground truth.
- Keep legitimate and `COORDINATED_ABUSE` labels, scenario metadata, and ring identifiers separate from runtime scoring inputs.
- Record deterministic random seeds, generator versions, and scenario configuration so datasets can be reproduced.
- Version generated datasets and preserve counts by class.
- Use leakage-safe evaluation splits. Temporal splits must respect event order, and grouped splits must keep linked entities or abuse rings from leaking across training and evaluation partitions.
- Validate generated distributions and scenario assumptions before using data for model claims.

No generator behavior, dataset size, class balance, or quality result is claimed yet.
