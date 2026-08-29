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


class CardTestingGenerator:
    scenario_type = ScenarioType.CARD_TESTING

    def generate(self, context: ScenarioContext, count: int) -> list[GeneratedEvent]:
        events: list[GeneratedEvent] = []
        ring_count = max(1, math.ceil(count / 25))
        for index in range(count):
            ring = min(index // 25, ring_count - 1)
            local = index % 25
            ring_id = stable_ring_id(context.config.dataset.seed, self.scenario_type.value, ring)
            devices = tuple(device(context, ring * 10 + item) for item in range(2))
            networks = tuple(
                network(
                    context,
                    ring * 10 + item,
                    (NetworkType.DATACENTER, NetworkType.MOBILE)[item],
                )
                for item in range(2)
            )
            instruments = tuple(instrument(context, ring * 100 + item) for item in range(14))
            customer = abuse_customer(
                context,
                ring * 10 + local % 5,
                age_days=(3, 9, 120, 400, 30)[local % 5],
                devices=devices,
                instruments=instruments,
                networks=networks,
                address=address(context, ring * 10 + local % 3),
            )
            selected_instrument = instruments[(local * 5) % len(instruments)]
            selected_merchant = merchant(context, local * 3)
            amount = sample_amount(
                context.rng,
                context.config,
                selected_merchant.category,
                scale=(0.18, 0.55, 1.1)[local % 3],
            )
            if local == 0:
                amount = context.config.behavior.amount_min_paise
            elif local == 1:
                amount = context.config.behavior.high_value_paise * 2
            events.append(
                build_event(
                    event_id=f"pending_card_testing_{index}",
                    event_time=event_time(context, index, count, burst=True),
                    customer=customer,
                    device=devices[local % len(devices)],
                    instrument=selected_instrument,
                    network=networks[local % len(networks)],
                    address=customer.address,
                    merchant=selected_merchant,
                    amount_paise=amount,
                    failed=local == 2
                    or context.rng.probability(context.config.behavior.abuse_failure_rate + 0.15),
                    truth=SyntheticGroundTruth(
                        label=GroundTruthLabel.COORDINATED_ABUSE,
                        scenario_type=self.scenario_type,
                        ring_id=ring_id,
                    ),
                )
            )
        return events
