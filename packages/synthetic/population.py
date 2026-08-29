import math
from datetime import timedelta

from apps.api.app.core.enums import NetworkType
from packages.synthetic.config import GenerationConfig
from packages.synthetic.domain import (
    AddressIdentity,
    CustomerIdentity,
    DeviceIdentity,
    InstrumentIdentity,
    LegitimatePersona,
    MerchantIdentity,
    NetworkIdentity,
    SyntheticPopulation,
)
from packages.synthetic.ids import synthetic_key
from packages.synthetic.rng import RandomStream

REGIONS = ("IN-KA", "IN-MH", "IN-DL", "IN-TN", "IN-WB", "IN-GJ", "IN-TG")
MERCHANT_CATEGORIES = (
    "ECOMMERCE",
    "FOOD",
    "TRAVEL",
    "ELECTRONICS",
    "FASHION",
    "GAMING",
    "SUBSCRIPTION",
    "EDUCATION",
)


def _device(seed: int, index: int) -> DeviceIdentity:
    return DeviceIdentity(
        fingerprint=synthetic_key("device", seed, index),
        device_type=("MOBILE", "DESKTOP", "TABLET")[index % 3],
        os_family=("ANDROID", "IOS", "WINDOWS", "MACOS")[index % 4],
        browser_family=("CHROME", "SAFARI", "FIREFOX", "EDGE")[index % 4],
    )


def _instrument(seed: int, index: int, region: str) -> InstrumentIdentity:
    return InstrumentIdentity(
        fingerprint=synthetic_key("instrument", seed, index),
        instrument_type=("CARD", "UPI_TOKEN")[index % 2],
        issuer_region=region,
    )


def build_population(config: GenerationConfig, normal_event_count: int) -> SyntheticPopulation:
    rng = RandomStream(config.dataset.seed, "population")
    customer_count = max(
        40, math.ceil(normal_event_count / config.population.transactions_per_customer)
    )
    personas = list(LegitimatePersona)
    weights = {persona: config.legitimate_persona_weights[persona.value] for persona in personas}
    counts = rng.weighted_counts(customer_count, weights)
    if customer_count >= len(personas) * 2:
        for persona in personas:
            if counts[persona] < 2:
                donor = max(counts, key=counts.get)  # type: ignore[arg-type]
                counts[donor] -= 2 - counts[persona]
                counts[persona] = 2
    assigned = [persona for persona in personas for _ in range(counts[persona])]

    family_networks: dict[int, NetworkIdentity] = {}
    family_addresses: dict[int, AddressIdentity] = {}
    family_devices: dict[int, DeviceIdentity] = {}
    family_instruments: dict[int, InstrumentIdentity] = {}
    corporate_networks: dict[int, NetworkIdentity] = {}
    persona_seen = dict.fromkeys(personas, 0)
    device_index = 0
    instrument_index = 0
    customers: list[CustomerIdentity] = []

    for index, persona in enumerate(assigned):
        occurrence = persona_seen[persona]
        persona_seen[persona] += 1
        region = REGIONS[index % len(REGIONS)]
        is_new = occurrence == 0 or rng.probability(config.behavior.new_account_fraction)
        age_days = rng.integer(1, 15) if is_new else rng.integer(45, 1500)
        account_created_at = config.dataset.start_time - timedelta(days=age_days)

        device_count = {
            LegitimatePersona.STANDARD_RETAIL: rng.integer(1, 4),
            LegitimatePersona.POWER_SHOPPER: rng.integer(2, 5),
            LegitimatePersona.FAMILY_HOUSEHOLD: rng.integer(1, 3),
            LegitimatePersona.CORPORATE_OR_CAMPUS_NETWORK: rng.integer(1, 3),
            LegitimatePersona.TRAVELLER: 2,
        }[persona]
        instrument_count = {
            LegitimatePersona.STANDARD_RETAIL: rng.integer(1, 3),
            LegitimatePersona.POWER_SHOPPER: rng.integer(3, 6),
            LegitimatePersona.FAMILY_HOUSEHOLD: rng.integer(1, 3),
            LegitimatePersona.CORPORATE_OR_CAMPUS_NETWORK: rng.integer(1, 3),
            LegitimatePersona.TRAVELLER: rng.integer(1, 4),
        }[persona]
        devices = tuple(
            _device(config.dataset.seed, device_index + item) for item in range(device_count)
        )
        device_index += device_count
        instruments = tuple(
            _instrument(config.dataset.seed, instrument_index + item, region)
            for item in range(instrument_count)
        )
        instrument_index += instrument_count

        address = AddressIdentity(
            fingerprint=synthetic_key("address", config.dataset.seed, index),
            region=region,
            postal_prefix=str(110 + index % 780),
        )
        networks = (
            NetworkIdentity(
                ip_hash=synthetic_key("ip", config.dataset.seed, index),
                network_type=NetworkType.RESIDENTIAL,
                region=region,
            ),
        )

        if persona == LegitimatePersona.FAMILY_HOUSEHOLD:
            group = occurrence // 4
            family_networks.setdefault(
                group,
                NetworkIdentity(
                    ip_hash=synthetic_key("family_ip", config.dataset.seed, group),
                    network_type=NetworkType.RESIDENTIAL,
                    region=region,
                ),
            )
            family_addresses.setdefault(
                group,
                AddressIdentity(
                    fingerprint=synthetic_key("family_address", config.dataset.seed, group),
                    region=region,
                    postal_prefix=str(560 + group % 20),
                ),
            )
            family_devices.setdefault(group, _device(config.dataset.seed, 100_000 + group))
            family_instruments.setdefault(
                group, _instrument(config.dataset.seed, 100_000 + group, region)
            )
            networks = (family_networks[group],)
            address = family_addresses[group]
            if occurrence % 2 == 0:
                devices = (*devices, family_devices[group])
            if occurrence % 3 == 0:
                instruments = (*instruments, family_instruments[group])
        elif persona == LegitimatePersona.CORPORATE_OR_CAMPUS_NETWORK:
            group = occurrence // 12
            corporate_networks.setdefault(
                group,
                NetworkIdentity(
                    ip_hash=synthetic_key("campus_ip", config.dataset.seed, group),
                    network_type=(NetworkType.CORPORATE, NetworkType.HOSTEL)[group % 2],
                    region=region,
                ),
            )
            networks = (corporate_networks[group],)
        elif persona == LegitimatePersona.POWER_SHOPPER and occurrence % 3 == 0:
            networks = (
                networks[0],
                NetworkIdentity(
                    ip_hash=synthetic_key("vpn_ip", config.dataset.seed, index),
                    network_type=NetworkType.DATACENTER,
                    region=region,
                ),
            )
        elif persona == LegitimatePersona.TRAVELLER:
            travel_region = REGIONS[(index + 3) % len(REGIONS)]
            networks = (
                networks[0],
                NetworkIdentity(
                    ip_hash=synthetic_key("travel_ip", config.dataset.seed, index),
                    network_type=(NetworkType.PUBLIC_WIFI, NetworkType.MOBILE)[index % 2],
                    region=travel_region,
                ),
            )

        customers.append(
            CustomerIdentity(
                ref=synthetic_key("customer", config.dataset.seed, index),
                account_created_at=account_created_at,
                segment="RETAIL",
                home_region=region,
                persona=persona,
                devices=devices,
                instruments=instruments,
                networks=networks,
                address=address,
            )
        )

    merchants = tuple(
        MerchantIdentity(
            ref=synthetic_key("merchant", config.dataset.seed, index),
            category=MERCHANT_CATEGORIES[index % len(MERCHANT_CATEGORIES)],
            region=REGIONS[(index * 3) % len(REGIONS)],
            risk_baseline=round(0.02 + 0.01 * (index % 6), 3),
        )
        for index in range(config.population.merchant_count)
    )
    return SyntheticPopulation(customers=tuple(customers), merchants=merchants)
