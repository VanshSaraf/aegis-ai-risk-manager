import math

from apps.api.app.core.enums import GroundTruthLabel, NetworkType, ScenarioType
from packages.synthetic.behavior import build_event, sample_amount
from packages.synthetic.domain import GeneratedEvent, SyntheticGroundTruth
from packages.synthetic.ids import stable_ring_id
from packages.synthetic.scenarios.base import (
    ScenarioContext,
    abuse_customer,
    address,
    device,
    event_time,
    instrument,
    merchant,
    network,
)


class AccountFarmGenerator:
    scenario_type = ScenarioType.ACCOUNT_FARM

    def generate(self, context: ScenarioContext, count: int) -> list[GeneratedEvent]:
        events: list[GeneratedEvent] = []
        ring_count = max(1, math.ceil(count / 30))
        for index in range(count):
            ring = min(index // 30, ring_count - 1)
            local = index % 30
            ring_id = stable_ring_id(context.config.dataset.seed, self.scenario_type.value, ring)
            devices = tuple(device(context, ring * 10 + item) for item in range(3))
            networks = tuple(
                network(
                    context,
                    ring * 10 + item,
                    (NetworkType.MOBILE, NetworkType.CORPORATE)[item],
                )
                for item in range(2)
            )
            shared_addresses = tuple(address(context, ring * 10 + item) for item in range(2))
            instruments = tuple(instrument(context, ring * 100 + item) for item in range(8))
            customer = abuse_customer(
                context,
                ring * 20 + local % 12,
                age_days=(2, 4, 7, 10, 18, 75)[local % 6],
                devices=devices,
                instruments=instruments,
                networks=networks,
                address=shared_addresses[local % 2],
            )
            selected_merchant = merchant(context, local * 5)
            amount = sample_amount(
                context.rng,
                context.config,
                selected_merchant.category,
                scale=(0.6, 1.0, 1.4)[local % 3],
            )
            if local == 0:
                amount = context.config.behavior.amount_min_paise
            elif local == 1:
                amount = context.config.behavior.high_value_paise * 2
            events.append(
                build_event(
                    event_id=f"pending_account_farm_{index}",
                    event_time=event_time(context, index, count, burst=True),
                    customer=customer,
                    device=devices[local % 3],
                    instrument=instruments[(local * 3) % len(instruments)],
                    network=networks[local % 2],
                    address=customer.address,
                    merchant=selected_merchant,
                    amount_paise=amount,
                    failed=local == 2
                    or context.rng.probability(context.config.behavior.abuse_failure_rate),
                    truth=SyntheticGroundTruth(
                        label=GroundTruthLabel.COORDINATED_ABUSE,
                        scenario_type=self.scenario_type,
                        ring_id=ring_id,
                    ),
                )
            )
        return events
