from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from apps.api.app.core.enums import GroundTruthLabel, NetworkType, ScenarioType
from apps.api.app.schemas.contracts import RawPaymentEvent


class LegitimatePersona(StrEnum):
    STANDARD_RETAIL = "STANDARD_RETAIL"
    POWER_SHOPPER = "POWER_SHOPPER"
    FAMILY_HOUSEHOLD = "FAMILY_HOUSEHOLD"
    CORPORATE_OR_CAMPUS_NETWORK = "CORPORATE_OR_CAMPUS_NETWORK"
    TRAVELLER = "TRAVELLER"


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    fingerprint: str
    device_type: str
    os_family: str
    browser_family: str


@dataclass(frozen=True, slots=True)
class InstrumentIdentity:
    fingerprint: str
    instrument_type: str
    issuer_region: str


@dataclass(frozen=True, slots=True)
class NetworkIdentity:
    ip_hash: str
    network_type: NetworkType
    region: str


@dataclass(frozen=True, slots=True)
class AddressIdentity:
    fingerprint: str
    region: str
    postal_prefix: str


@dataclass(frozen=True, slots=True)
class MerchantIdentity:
    ref: str
    category: str
    region: str
    risk_baseline: float


@dataclass(frozen=True, slots=True)
class CustomerIdentity:
    ref: str
    account_created_at: datetime
    segment: str
    home_region: str
    persona: LegitimatePersona | None
    devices: tuple[DeviceIdentity, ...]
    instruments: tuple[InstrumentIdentity, ...]
    networks: tuple[NetworkIdentity, ...]
    address: AddressIdentity


@dataclass(frozen=True, slots=True)
class SyntheticGroundTruth:
    label: GroundTruthLabel
    scenario_type: ScenarioType
    ring_id: str | None = None
    persona: LegitimatePersona | None = None


@dataclass(frozen=True, slots=True)
class GeneratedEvent:
    facts: RawPaymentEvent
    truth: SyntheticGroundTruth

    def canonical(self) -> dict[str, object]:
        return {
            "facts": self.facts.model_dump(mode="json"),
            "truth": {
                "label": self.truth.label.value,
                "scenario_type": self.truth.scenario_type.value,
                "ring_id": self.truth.ring_id,
                "persona": self.truth.persona.value if self.truth.persona else None,
            },
        }


@dataclass(frozen=True, slots=True)
class SyntheticPopulation:
    customers: tuple[CustomerIdentity, ...]
    merchants: tuple[MerchantIdentity, ...]


@dataclass(frozen=True, slots=True)
class SyntheticDataset:
    events: tuple[GeneratedEvent, ...]
    population: SyntheticPopulation
    generator_version: str
    seed: int
    config_hash: str
