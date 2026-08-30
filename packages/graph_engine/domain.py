from dataclasses import dataclass
from datetime import datetime
from typing import Any

from apps.api.app.core.enums import GraphEntityType


@dataclass(frozen=True, order=True, slots=True)
class GraphEntityRef:
    entity_type: GraphEntityType
    public_id: str

    def canonical(self) -> str:
        return f"{self.entity_type.value}:{self.public_id}"


@dataclass(frozen=True, slots=True)
class GraphTransaction:
    transaction_public_id: str
    customer_id: str
    instrument_id: str
    device_id: str
    ip_id: str
    address_id: str
    amount_paise: int
    event_time: datetime

    def entities(self) -> tuple[GraphEntityRef, ...]:
        return (
            GraphEntityRef(GraphEntityType.CUSTOMER, self.customer_id),
            GraphEntityRef(GraphEntityType.PAYMENT_INSTRUMENT, self.instrument_id),
            GraphEntityRef(GraphEntityType.DEVICE, self.device_id),
            GraphEntityRef(GraphEntityType.IP, self.ip_id),
            GraphEntityRef(GraphEntityType.ADDRESS, self.address_id),
        )

    def relationships(self) -> tuple[tuple[GraphEntityRef, GraphEntityRef], ...]:
        customer, instrument, device, ip, address = self.entities()
        return (
            (customer, device),
            (customer, instrument),
            (customer, ip),
            (customer, address),
            (instrument, device),
        )


@dataclass(frozen=True, slots=True)
class GraphSignal:
    code: str
    strength: float
    observed_value: float
    threshold: float
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "strength": self.strength,
            "observed_value": self.observed_value,
            "threshold": self.threshold,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class GraphAssessment:
    graph_version: str
    transaction_public_id: str
    metrics: dict[str, float | int | bool]
    signals: tuple[GraphSignal, ...]
    structural_score: float
    touched_component_fingerprints: tuple[str, ...]
    candidate_cluster: bool
    computed_at: datetime
    max_source_event_time: datetime | None


@dataclass(frozen=True, slots=True)
class DetectedCluster:
    fingerprint: str
    members: frozenset[GraphEntityRef]
    structural_score: float
    signals: tuple[GraphSignal, ...]
    transaction_count: int
    exposure_paise: int
    first_seen_at: datetime
    last_seen_at: datetime
