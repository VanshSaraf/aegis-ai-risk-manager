import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.api.app.core.enums import NetworkType, ScenarioType
from packages.synthetic.config import GenerationConfig
from packages.synthetic.domain import (
    AddressIdentity,
    CustomerIdentity,
    DeviceIdentity,
    GeneratedEvent,
    InstrumentIdentity,
    MerchantIdentity,
    NetworkIdentity,
    SyntheticPopulation,
)
from packages.synthetic.ids import synthetic_key
from packages.synthetic.rng import RandomStream

ABUSE_REGIONS = ("IN-KA", "IN-MH", "IN-DL", "IN-TN", "IN-WB", "IN-GJ", "IN-TG")


@dataclass(frozen=True, slots=True)
class ScenarioContext:
    config: GenerationConfig
    population: SyntheticPopulation
    rng: RandomStream
    scenario: ScenarioType

    @property
    def start_time(self) -> datetime:
        return self.config.dataset.start_time

    @property
    def duration(self) -> timedelta:
        return timedelta(days=self.config.dataset.simulation_days)


class ScenarioGenerator(Protocol):
    scenario_type: ScenarioType

    def generate(self, context: ScenarioContext, count: int) -> list[GeneratedEvent]: ...


def abuse_customer(
    context: ScenarioContext,
    index: int,
    *,
    age_days: int,
    devices: tuple[DeviceIdentity, ...],
    instruments: tuple[InstrumentIdentity, ...],
    networks: tuple[NetworkIdentity, ...],
    address: AddressIdentity,
) -> CustomerIdentity:
    region = address.region
    return CustomerIdentity(
        ref=synthetic_key(
            f"{context.scenario.value.lower()}_customer", context.config.dataset.seed, index
        ),
        account_created_at=context.start_time - timedelta(days=age_days),
        segment="RETAIL",
        home_region=region,
        persona=None,
        devices=devices,
        instruments=instruments,
        networks=networks,
        address=address,
    )


def device(context: ScenarioContext, index: int) -> DeviceIdentity:
    offset = list(ScenarioType).index(context.scenario)
    return DeviceIdentity(
        fingerprint=synthetic_key(
            f"{context.scenario.value.lower()}_device", context.config.dataset.seed, index
        ),
        device_type=("MOBILE", "DESKTOP", "TABLET")[(index + offset) % 3],
        os_family=("ANDROID", "WINDOWS", "IOS", "MACOS")[(index + offset) % 4],
        browser_family=("CHROME", "SAFARI", "FIREFOX", "EDGE")[(index + offset) % 4],
    )


def instrument(
    context: ScenarioContext, index: int, region: str | None = None
) -> InstrumentIdentity:
    selected_region = (
        region
        or ABUSE_REGIONS[(index + list(ScenarioType).index(context.scenario)) % len(ABUSE_REGIONS)]
    )
    return InstrumentIdentity(
        fingerprint=synthetic_key(
            f"{context.scenario.value.lower()}_instrument", context.config.dataset.seed, index
        ),
        instrument_type=("CARD", "UPI_TOKEN")[index % 2],
        issuer_region=selected_region,
    )


def network(
    context: ScenarioContext,
    index: int,
    network_type: NetworkType = NetworkType.MOBILE,
    region: str | None = None,
) -> NetworkIdentity:
    selected_region = (
        region
        or ABUSE_REGIONS[(index + list(ScenarioType).index(context.scenario)) % len(ABUSE_REGIONS)]
    )
    return NetworkIdentity(
        ip_hash=synthetic_key(
            f"{context.scenario.value.lower()}_ip", context.config.dataset.seed, index
        ),
        network_type=network_type,
        region=selected_region,
    )


def address(context: ScenarioContext, index: int, region: str | None = None) -> AddressIdentity:
    scenario_offset = (
        0
        if context.scenario == ScenarioType.CARD_TESTING
        else list(ScenarioType).index(context.scenario)
    )
    selected_region = region or ABUSE_REGIONS[(index + scenario_offset) % len(ABUSE_REGIONS)]
    return AddressIdentity(
        fingerprint=synthetic_key(
            f"{context.scenario.value.lower()}_address", context.config.dataset.seed, index
        ),
        region=selected_region,
        postal_prefix=str(500 + index % 300),
    )


def merchant(context: ScenarioContext, index: int) -> MerchantIdentity:
    return context.population.merchants[index % len(context.population.merchants)]


def event_time(
    context: ScenarioContext, index: int, count: int, *, burst: bool = False
) -> datetime:
    if burst:
        ring = index // 25
        within_ring = index % 25
        ring_count = max(1, math.ceil(count / 25))
        base_seconds = int((ring + 1) * context.duration.total_seconds() / (ring_count + 1))
        return context.start_time + timedelta(
            seconds=(
                base_seconds + within_ring * context.config.behavior.abuse_burst_spacing_seconds
            )
        )
    return context.start_time + timedelta(
        seconds=context.rng.integer(0, int(context.duration.total_seconds()))
    )
