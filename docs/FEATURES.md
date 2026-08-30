# Point-in-Time Features

## Scoring moment

`features-v1` freezes the scoring moment after payment and identity context arrives but before
the current payment's final outcome is available. The engine therefore uses current amount,
time, account, merchant, and identity context, but never the current `status` or `failure_code`.
Historical outcomes are allowed; `FAILED` is centrally defined as a historical failure.

Synthetic label, scenario, ring, persona, scenario-run ID, and dataset version are excluded from
the feature input and payload. Offline `TrainingExample` records attach truth only after feature
computation.

The engine receives an outcome-free `ScoringFeatureTransaction`; `status` and `failure_code`
exist only on historical records added after scoring. Three otherwise useful context candidates
(`home_network_region_match`, `home_merchant_region_match`, and `merchant_risk_baseline`) are
deliberately excluded from `features-v1`: their current PostgreSQL source rows are mutable during
entity resolution, so recomputing an old transaction could otherwise observe a later profile
value. They can return only after immutable point-in-time source snapshots exist.

## Point-in-time and window semantics

All history satisfies `historical.event_time < current.event_time`. A window is closed on its
lower boundary and open on its upper boundary:

```text
current_time - window <= historical.event_time < current_time
```

Transactions with equal timestamps do not see one another. Offline backfill computes an entire
same-time batch, validates it, and only then adds that batch to history. PostgreSQL queries use
the same strict cutoff.

`max_source_event_time` is the newest relevant historical transaction used by the vector. It is
null when no relevant history exists and otherwise must be strictly earlier than the current
event.

## Architecture and parity

`FeatureEngine` owns every feature formula. `InMemoryHistoryProvider` supplies indexed
chronological history for offline backfill. `PostgreSQLHistoryProvider` fetches the relevant
point-in-time entity-history union in one query for online computation. Both providers return
the same history contract to the same engine; a PostgreSQL parity test requires equal feature
values and watermarks.

Final `EntityEdge` state is never used. Its accumulated counts and timestamps may include future
observations and would leak future relationships into historical backfills.

## Missing-history behavior

- Counts, rates, means, standard deviations, ratios, and z-scores default to zero.
- New-entity flags are true when the customer has no earlier matching relationship.
- A single prior amount has zero standard deviation, so its z-score is zero.
- All outputs are validated as finite `int`, `float`, or `bool` values.

## features-v1 registry

The machine-readable registry is `ml/artifacts/features-v1/schema.json`. It contains name, family,
primitive type, description, optional window, and whether historical outcomes are used.

### Transaction (6)

`amount_paise`, `log_amount`, `account_age_hours`, `hour_of_day`, `day_of_week`, `is_weekend`.

### Customer (19)

`customer_txn_count_1h`, `customer_txn_count_24h`, `customer_txn_count_30d`,
`customer_failed_txn_count_1h`, `customer_failed_txn_count_24h`,
`customer_failure_rate_30d`, `customer_avg_amount_30d`, `customer_amount_std_30d`,
`amount_vs_customer_mean`, `amount_zscore_customer`, `customer_unique_devices_24h`,
`customer_unique_instruments_24h`, `customer_unique_ips_24h`,
`customer_unique_addresses_30d`, `customer_merchant_txn_count_30d`,
`is_new_device_for_customer`, `is_new_instrument_for_customer`, `is_new_ip_for_customer`,
`is_new_address_for_customer`.

### Velocity (21)

`device_txn_count_1m`, `device_txn_count_10m`, `device_txn_count_1h`,
`device_failed_txn_count_10m`, `device_failed_txn_count_1h`,
`device_unique_customers_1h`, `device_unique_instruments_1h`, `ip_txn_count_10m`,
`ip_txn_count_1h`, `ip_failed_txn_count_10m`, `ip_failed_txn_count_1h`,
`ip_unique_customers_1h`, `ip_unique_customers_24h`, `instrument_txn_count_10m`,
`instrument_txn_count_1h`, `instrument_txn_count_24h`,
`instrument_failed_txn_count_1h`, `instrument_unique_devices_24h`,
`address_txn_count_1h`, `address_txn_count_24h`, `address_unique_customers_24h`.

### Relationship (6)

`historical_customers_on_current_device`, `historical_instruments_on_current_device`,
`historical_customers_on_current_ip`, `historical_devices_on_current_ip`,
`historical_customers_on_current_address`, `historical_devices_for_current_instrument`.

These are raw point-in-time structural counts, not graph scores or abuse classifications.

## Snapshot versioning

Snapshots are immutable by `(transaction_id, feature_version)`. Recomputing an identical
`features-v1` snapshot returns the existing row; a mismatch raises an error instead of rewriting
evidence. Different feature versions may coexist. Feature definitions and names are also stored
in the `FeatureVersion` registry.
