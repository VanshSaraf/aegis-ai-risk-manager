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


class CollusiveRingGenerator:
    scenario_type = ScenarioType.COLLUSIVE_RING

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
                    (NetworkType.RESIDENTIAL, NetworkType.HOSTEL)[item],
                )
                for item in range(2)
            )
            addresses = tuple(address(context, ring * 10 + item) for item in range(3))
            instruments = tuple(instrument(context, ring * 100 + item) for item in range(7))
            customer_index = local % 7
            customer = abuse_customer(
                context,
                ring * 20 + customer_index,
                age_days=(8, 25, 80, 240, 500)[customer_index % 5],
                devices=(devices[customer_index % 3], devices[(customer_index + 1) % 3]),
                instruments=(
                    instruments[customer_index],
                    instruments[(customer_index + 2) % len(instruments)],
                ),
                networks=(networks[customer_index % 2],),
                address=addresses[customer_index % 3],
            )
            selected_merchant = merchant(context, (local * 2) % 10)
            amount = sample_amount(
                context.rng,
                context.config,
                selected_merchant.category,
                scale=(0.7, 1.0, 1.5)[local % 3],
            )
            if local == 0:
                amount = context.config.behavior.amount_min_paise
            elif local == 1:
                amount = context.config.behavior.high_value_paise * 2
            events.append(
                build_event(
                    event_id=f"pending_collusive_ring_{index}",
                    event_time=event_time(context, index, count, burst=True),
                    customer=customer,
                    device=customer.devices[local % len(customer.devices)],
                    instrument=customer.instruments[local % len(customer.instruments)],
                    network=customer.networks[0],
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
