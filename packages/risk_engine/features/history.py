from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Protocol

from packages.risk_engine.features.domain import FeatureTransaction, ScoringFeatureTransaction

ENTITY_FIELDS = ("customer_id", "device_id", "instrument_id", "ip_id", "address_id")


class HistoryProvider(Protocol):
    async def history_for(
        self, current: ScoringFeatureTransaction
    ) -> Sequence[FeatureTransaction]: ...


class InMemoryHistoryProvider:
    """Chronological history indexed by entity; queries always enforce strict event-time cutoff."""

    def __init__(self, records: Iterable[FeatureTransaction] = ()) -> None:
        self._indexes: dict[str, dict[str, list[FeatureTransaction]]] = {
            field: defaultdict(list) for field in ENTITY_FIELDS
        }
        for record in sorted(records, key=lambda item: item.event_time):
            self.observe(record)

    def observe(self, transaction: FeatureTransaction) -> None:
        for field in ENTITY_FIELDS:
            self._indexes[field][getattr(transaction, field)].append(transaction)

    def observe_many(self, transactions: Iterable[FeatureTransaction]) -> None:
        for transaction in transactions:
            self.observe(transaction)

    async def history_for(self, current: ScoringFeatureTransaction) -> Sequence[FeatureTransaction]:
        by_id: dict[str, FeatureTransaction] = {}
        for field in ENTITY_FIELDS:
            records = self._indexes[field].get(getattr(current, field), [])
            cutoff = bisect_left(
                [record.event_time for record in records],
                current.event_time,
            )
            for record in records[:cutoff]:
                by_id[record.transaction_public_id] = record
        return tuple(sorted(by_id.values(), key=lambda item: item.event_time))
