import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from apps.api.app.core.enums import GroundTruthLabel, NetworkType, ScenarioType
from packages.synthetic.behavior import build_event, sample_amount
from packages.synthetic.config import GenerationConfig
from packages.synthetic.domain import (
    CustomerIdentity,
    DeviceIdentity,
    GeneratedEvent,
    InstrumentIdentity,
    LegitimatePersona,
    SyntheticGroundTruth,
    SyntheticPopulation,
)
from packages.synthetic.ids import stable_ring_id, synthetic_key
from packages.synthetic.population import build_population
from packages.synthetic.scenarios.base import (
    ScenarioContext,
    abuse_customer,
    address,
    device,
    instrument,
    merchant,
    network,
)


def _append_unique[IdentityT](
    values: tuple[IdentityT, ...], value: IdentityT
) -> tuple[IdentityT, ...]:
    return values if value in values else (*values, value)


def build_population_v2(config: GenerationConfig, normal_event_count: int) -> SyntheticPopulation:
    """Add deterministic legitimate shared infrastructure without changing synthetic-v1."""
    base = build_population(config, normal_event_count)
    hardening = config.hardening
    assert hardening is not None
    customers = list(base.customers)
    household_groups: dict[str, list[int]] = defaultdict(list)
    corporate_groups: dict[str, list[int]] = defaultdict(list)
    for index, customer in enumerate(customers):
        if customer.persona == LegitimatePersona.FAMILY_HOUSEHOLD:
            household_groups[customer.address.fingerprint].append(index)
        if customer.persona == LegitimatePersona.CORPORATE_OR_CAMPUS_NETWORK:
            corporate_groups[customer.networks[0].ip_hash].append(index)

    for group_number, indices in enumerate(sorted(household_groups.values(), key=min)):
        if not indices:
            continue
        region = customers[indices[0]].home_region
        shared_device = DeviceIdentity(
            fingerprint=synthetic_key("v2_household_device", config.dataset.seed, group_number),
            device_type="TABLET",
            os_family="ANDROID",
            browser_family="CHROME",
        )
        shared_instrument = InstrumentIdentity(
            fingerprint=synthetic_key("v2_household_instrument", config.dataset.seed, group_number),
            instrument_type="CARD",
            issuer_region=region,
        )
        dense_count = max(2, math.ceil(len(indices) * hardening.household_dense_fraction))
        for index in indices[:dense_count]:
            customer = customers[index]
            customers[index] = replace(
                customer,
                devices=_append_unique(customer.devices, shared_device),
                instruments=_append_unique(customer.instruments, shared_instrument),
            )

    for group_number, indices in enumerate(sorted(corporate_groups.values(), key=min)):
        shared_device = DeviceIdentity(
            fingerprint=synthetic_key("v2_campus_kiosk", config.dataset.seed, group_number),
            device_type="DESKTOP",
            os_family="WINDOWS",
            browser_family="EDGE",
        )
        shared_count = max(2, math.ceil(len(indices) * hardening.corporate_shared_device_fraction))
        for index in indices[:shared_count]:
            customer = customers[index]
            customers[index] = replace(
                customer, devices=_append_unique(customer.devices, shared_device)
            )
    return SyntheticPopulation(customers=tuple(customers), merchants=base.merchants)


def _most_shared[IdentityT](values: Sequence[Sequence[IdentityT]]) -> IdentityT | None:
    counts = Counter(item for items in values for item in items)
    return min(counts, key=lambda item: (-counts[item], str(item))) if counts else None


class V2NormalTrafficGenerator:
    scenario_type = ScenarioType.NORMAL_TRAFFIC

    def generate(self, context: ScenarioContext, count: int) -> list[GeneratedEvent]:
        if count <= 0:
            return []
        hardening = context.config.hardening
        assert hardening is not None
        customers = list(context.population.customers)
        by_persona = {
            persona: [customer for customer in customers if customer.persona == persona]
            for persona in LegitimatePersona
        }
        households: dict[str, list[CustomerIdentity]] = defaultdict(list)
        campuses: dict[str, list[CustomerIdentity]] = defaultdict(list)
        for customer in customers:
            if customer.persona == LegitimatePersona.FAMILY_HOUSEHOLD:
                households[customer.address.fingerprint].append(customer)
            if customer.persona == LegitimatePersona.CORPORATE_OR_CAMPUS_NETWORK:
                campuses[customer.networks[0].ip_hash].append(customer)
        household_groups = [group for group in households.values() if len(group) >= 2]
        campus_groups = [group for group in campuses.values() if len(group) >= 3]
        new_customers = [
            customer
            for customer in customers
            if context.start_time - customer.account_created_at <= timedelta(days=30)
        ]
        hard_count = int(count * hardening.legitimate_hard_event_fraction)
        cluster_size = 8
        cluster_count = max(1, math.ceil(hard_count / cluster_size))
        events: list[GeneratedEvent] = []
        for index in range(count):
            if index < hard_count:
                cluster, within = divmod(index, cluster_size)
                strategy = cluster % 5
                base_seconds = int(
                    (cluster + 1) * context.duration.total_seconds() / (cluster_count + 1)
                )
                spacing = (35, 45, 25, 40, 55)[strategy]
                event_at = context.start_time + timedelta(seconds=base_seconds + within * spacing)
                if strategy == 0:
                    customer = by_persona[LegitimatePersona.POWER_SHOPPER][
                        cluster % len(by_persona[LegitimatePersona.POWER_SHOPPER])
                    ]
                elif strategy == 1:
                    group = household_groups[cluster % len(household_groups)]
                    customer = group[within % len(group)]
                elif strategy == 2:
                    group = campus_groups[cluster % len(campus_groups)]
                    customer = group[within % len(group)]
                elif strategy == 3:
                    customer = customers[cluster % len(customers)]
                else:
                    customer = new_customers[cluster % len(new_customers)]
                device_value = customer.devices[within % len(customer.devices)]
                instrument_value = customer.instruments[within % len(customer.instruments)]
                network_value = customer.networks[within % len(customer.networks)]
                if strategy == 1:
                    group = household_groups[cluster % len(household_groups)]
                    shared_device = _most_shared([member.devices for member in group])
                    shared_instrument = _most_shared([member.instruments for member in group])
                    if within % 3 != 2 and shared_device is not None:
                        device_value = shared_device
                    if within % 4 == 0 and shared_instrument is not None:
                        instrument_value = shared_instrument
                selected_merchant = context.population.merchants[
                    (cluster * 3 + within) % len(context.population.merchants)
                ]
                scale = (1.15, 0.9, 1.0, 0.75, 1.4)[strategy]
                amount = sample_amount(
                    context.rng, context.config, selected_merchant.category, scale=scale
                )
                failed = (
                    strategy == 3
                    and within < 3
                    and context.rng.probability(hardening.legitimate_retry_failure_rate)
                ) or context.rng.probability(context.config.behavior.legitimate_failure_rate)
            else:
                customer = context.rng.choice(customers)
                device_value = context.rng.choice(customer.devices)
                instrument_value = context.rng.choice(customer.instruments)
                network_value = context.rng.choice(customer.networks)
                selected_merchant = context.rng.choice(context.population.merchants)
                scale = 1.3 if customer.persona == LegitimatePersona.POWER_SHOPPER else 1.0
                amount = sample_amount(
                    context.rng, context.config, selected_merchant.category, scale=scale
                )
                failed = context.rng.probability(context.config.behavior.legitimate_failure_rate)
                event_at = context.start_time + context.duration * context.rng.uniform()
            persona = customer.persona
            assert persona is not None
            events.append(
                build_event(
                    event_id=f"pending_v2_normal_{index}",
                    event_time=event_at,
                    customer=customer,
                    device=device_value,
                    instrument=instrument_value,
                    network=network_value,
                    address=customer.address,
                    merchant=selected_merchant,
                    amount_paise=amount,
                    failed=failed,
                    truth=SyntheticGroundTruth(
                        label=GroundTruthLabel.LEGITIMATE,
                        scenario_type=ScenarioType.NORMAL_TRAFFIC,
                        persona=persona,
                    ),
                )
            )
        return events


def _ring_time(
    context: ScenarioContext,
    ring: int,
    ring_count: int,
    local: int,
    strategy: int,
) -> datetime:
    base_seconds = int((ring + 1) * context.duration.total_seconds() / (ring_count + 1))
    spacing = (30, 150, 600, 1200)[strategy]
    jitter = context.rng.integer(0, max(2, spacing // 4))
    return context.start_time + timedelta(seconds=base_seconds + local * spacing + jitter)


def _abuse_truth(scenario: ScenarioType, seed: int, ring: int) -> SyntheticGroundTruth:
    return SyntheticGroundTruth(
        label=GroundTruthLabel.COORDINATED_ABUSE,
        scenario_type=scenario,
        ring_id=stable_ring_id(seed, f"synthetic-v2:{scenario.value}", ring),
    )


class V2CardTestingGenerator:
    scenario_type = ScenarioType.CARD_TESTING

    def generate(self, context: ScenarioContext, count: int) -> list[GeneratedEvent]:
        ring_size = 25
        ring_count = max(1, math.ceil(count / ring_size))
        events: list[GeneratedEvent] = []
        for index in range(count):
            ring, local = divmod(index, ring_size)
            strategy = ring % 4
            customer_count = (5, 8, 10, 7)[strategy]
            device_count = (2, 4, 6, 3)[strategy]
            network_count = (2, 4, 5, 3)[strategy]
            instrument_count = (14, 12, 18, 10)[strategy]
            devices = tuple(device(context, ring * 100 + item) for item in range(device_count))
            networks = tuple(
                network(
                    context,
                    ring * 100 + item,
                    (NetworkType.DATACENTER, NetworkType.MOBILE, NetworkType.PUBLIC_WIFI)[item % 3],
                )
                for item in range(network_count)
            )
            instruments = tuple(
                instrument(context, ring * 1000 + item) for item in range(instrument_count)
            )
            customer_index = local % customer_count
            customer = abuse_customer(
                context,
                ring * 100 + customer_index,
                age_days=(5, 45, 180, 420)[strategy],
                devices=devices,
                instruments=instruments,
                networks=networks,
                address=address(context, ring * 100 + customer_index % 4),
            )
            selected_merchant = merchant(context, local * 3 + ring)
            amount = sample_amount(
                context.rng,
                context.config,
                selected_merchant.category,
                scale=(0.3, 0.75, 1.05, 1.25)[strategy],
            )
            failed = (strategy == 0 and local == 2) or context.rng.probability(
                (0.42, 0.28, 0.18, 0.12)[strategy]
            )
            events.append(
                build_event(
                    event_id=f"pending_v2_card_testing_{index}",
                    event_time=_ring_time(context, ring, ring_count, local, strategy),
                    customer=customer,
                    device=devices[(local * 3) % device_count],
                    instrument=instruments[(local * 5) % instrument_count],
                    network=networks[(local * 2) % network_count],
                    address=customer.address,
                    merchant=selected_merchant,
                    amount_paise=amount,
                    failed=failed,
                    truth=_abuse_truth(self.scenario_type, context.config.dataset.seed, ring),
                )
            )
        return events


class V2AccountFarmGenerator:
    scenario_type = ScenarioType.ACCOUNT_FARM

    def generate(self, context: ScenarioContext, count: int) -> list[GeneratedEvent]:
        ring_size = 30
        ring_count = max(1, math.ceil(count / ring_size))
        events: list[GeneratedEvent] = []
        for index in range(count):
            ring, local = divmod(index, ring_size)
            strategy = ring % 4
            customer_count = (12, 15, 10, 14)[strategy]
            device_count = (3, 6, 8, 5)[strategy]
            network_count = (2, 4, 6, 5)[strategy]
            instrument_count = (8, 12, 18, 14)[strategy]
            devices = tuple(device(context, ring * 100 + item) for item in range(device_count))
            networks = tuple(
                network(
                    context,
                    ring * 100 + item,
                    (NetworkType.MOBILE, NetworkType.CORPORATE, NetworkType.RESIDENTIAL)[item % 3],
                )
                for item in range(network_count)
            )
            instruments = tuple(
                instrument(context, ring * 1000 + item) for item in range(instrument_count)
            )
            customer_index = local % customer_count
            customer = abuse_customer(
                context,
                ring * 100 + customer_index,
                age_days=(5 + customer_index, 60 + customer_index * 5, 240, 720)[strategy],
                devices=devices,
                instruments=instruments,
                networks=networks,
                address=address(context, ring * 100 + customer_index % (2 + strategy)),
            )
            selected_merchant = merchant(context, local * 5 + ring)
            amount = sample_amount(
                context.rng,
                context.config,
                selected_merchant.category,
                scale=(0.7, 1.0, 1.25, 0.9)[strategy],
            )
            failed = (strategy == 0 and local == 2) or context.rng.probability(
                (0.30, 0.20, 0.12, 0.08)[strategy]
            )
            events.append(
                build_event(
                    event_id=f"pending_v2_account_farm_{index}",
                    event_time=_ring_time(context, ring, ring_count, local, strategy),
                    customer=customer,
                    device=devices[(local * 2) % device_count],
                    instrument=instruments[(local * 3) % instrument_count],
                    network=networks[(local * 2 + strategy) % network_count],
                    address=customer.address,
                    merchant=selected_merchant,
                    amount_paise=amount,
                    failed=failed,
                    truth=_abuse_truth(self.scenario_type, context.config.dataset.seed, ring),
                )
            )
        return events


class V2IdentityRotationGenerator:
    scenario_type = ScenarioType.IDENTITY_ROTATION

    def generate(self, context: ScenarioContext, count: int) -> list[GeneratedEvent]:
        ring_size = 25
        ring_count = max(1, math.ceil(count / ring_size))
        events: list[GeneratedEvent] = []
        for index in range(count):
            ring, local = divmod(index, ring_size)
            strategy = ring % 4
            shared_devices = tuple(
                device(context, ring * 10_000 + item) for item in range(2 + strategy)
            )
            shared_networks = tuple(
                network(
                    context,
                    ring * 10_000 + item,
                    (NetworkType.MOBILE, NetworkType.PUBLIC_WIFI, NetworkType.RESIDENTIAL)[
                        item % 3
                    ],
                )
                for item in range(2 + strategy)
            )
            unique_device = device(context, ring * 10_000 + 5_000 + local)
            unique_network = network(context, ring * 10_000 + 5_000 + local, NetworkType.MOBILE)
            preserve = local % (2 + strategy) == 0 or (strategy == 0 and local % 3 != 2)
            selected_device = (
                shared_devices[local % len(shared_devices)] if preserve else unique_device
            )
            selected_network = (
                shared_networks[(local * 2) % len(shared_networks)]
                if preserve or local % 3 == 0
                else unique_network
            )
            rotating_instrument = instrument(context, ring * 10_000 + local // 2)
            customer_index = local // 2
            customer = abuse_customer(
                context,
                ring * 10_000 + customer_index,
                age_days=(8, 75, 300, 900)[strategy],
                devices=(selected_device,),
                instruments=(rotating_instrument,),
                networks=(selected_network,),
                address=address(context, ring * 10_000 + customer_index),
            )
            selected_merchant = merchant(context, local * 2 + strategy)
            amount = sample_amount(context.rng, context.config, selected_merchant.category)
            failed = (strategy == 0 and local == 2) or context.rng.probability(
                (0.28, 0.20, 0.14, 0.10)[strategy]
            )
            events.append(
                build_event(
                    event_id=f"pending_v2_identity_rotation_{index}",
                    event_time=_ring_time(context, ring, ring_count, local, strategy),
                    customer=customer,
                    device=selected_device,
                    instrument=rotating_instrument,
                    network=selected_network,
                    address=customer.address,
                    merchant=selected_merchant,
                    amount_paise=amount,
                    failed=failed,
                    truth=_abuse_truth(self.scenario_type, context.config.dataset.seed, ring),
                )
            )
        return events


class V2CollusiveRingGenerator:
    scenario_type = ScenarioType.COLLUSIVE_RING

    def generate(self, context: ScenarioContext, count: int) -> list[GeneratedEvent]:
        ring_size = 30
        ring_count = max(1, math.ceil(count / ring_size))
        events: list[GeneratedEvent] = []
        for index in range(count):
            ring, local = divmod(index, ring_size)
            strategy = ring % 4
            customer_count = (7, 9, 12, 8)[strategy]
            device_count = (3, 5, 8, 6)[strategy]
            network_count = (2, 4, 6, 3)[strategy]
            instrument_count = (7, 10, 14, 9)[strategy]
            devices = tuple(device(context, ring * 100 + item) for item in range(device_count))
            networks = tuple(
                network(
                    context,
                    ring * 100 + item,
                    (NetworkType.RESIDENTIAL, NetworkType.HOSTEL, NetworkType.MOBILE)[item % 3],
                )
                for item in range(network_count)
            )
            instruments = tuple(
                instrument(context, ring * 1000 + item) for item in range(instrument_count)
            )
            customer_index = local % customer_count
            first_device = devices[(customer_index * (strategy + 1)) % device_count]
            second_device = devices[(customer_index * 2 + 1) % device_count]
            first_instrument = instruments[(customer_index * 2 + strategy) % instrument_count]
            second_instrument = instruments[(customer_index * 3 + 1) % instrument_count]
            customer = abuse_customer(
                context,
                ring * 100 + customer_index,
                age_days=(20, 120, 400, 800)[strategy],
                devices=(first_device, second_device),
                instruments=(first_instrument, second_instrument),
                networks=(networks[(customer_index + strategy) % network_count],),
                address=address(context, ring * 100 + customer_index % (3 + strategy)),
            )
            selected_merchant = merchant(context, local * 2 + ring)
            amount = sample_amount(
                context.rng,
                context.config,
                selected_merchant.category,
                scale=(0.8, 1.1, 1.35, 0.95)[strategy],
            )
            failed = (strategy == 0 and local == 2) or context.rng.probability(
                (0.22, 0.16, 0.10, 0.08)[strategy]
            )
            events.append(
                build_event(
                    event_id=f"pending_v2_collusive_ring_{index}",
                    event_time=_ring_time(context, ring, ring_count, local, strategy),
                    customer=customer,
                    device=customer.devices[local % 2],
                    instrument=customer.instruments[(local // 2) % 2],
                    network=customer.networks[0],
                    address=customer.address,
                    merchant=selected_merchant,
                    amount_paise=amount,
                    failed=failed,
                    truth=_abuse_truth(self.scenario_type, context.config.dataset.seed, ring),
                )
            )
        return events


SCENARIO_GENERATORS_V2 = {
    ScenarioType.NORMAL_TRAFFIC: V2NormalTrafficGenerator(),
    ScenarioType.CARD_TESTING: V2CardTestingGenerator(),
    ScenarioType.ACCOUNT_FARM: V2AccountFarmGenerator(),
    ScenarioType.IDENTITY_ROTATION: V2IdentityRotationGenerator(),
    ScenarioType.COLLUSIVE_RING: V2CollusiveRingGenerator(),
}
