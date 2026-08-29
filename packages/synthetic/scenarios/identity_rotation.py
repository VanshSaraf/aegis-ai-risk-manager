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


class IdentityRotationGenerator:
    scenario_type = ScenarioType.IDENTITY_ROTATION

    def generate(self, context: ScenarioContext, count: int) -> list[GeneratedEvent]:
        events: list[GeneratedEvent] = []
        ring_count = max(1, math.ceil(count / 25))
        for index in range(count):
            ring = min(index // 25, ring_count - 1)
            local = index % 25
            ring_id = stable_ring_id(context.config.dataset.seed, self.scenario_type.value, ring)
            persistent_devices = tuple(device(context, ring * 10 + item) for item in range(2))
            persistent_networks = tuple(
                network(
                    context,
                    ring * 10 + item,
                    (NetworkType.MOBILE, NetworkType.PUBLIC_WIFI)[item],
                )
                for item in range(2)
            )
            rotating_instrument = instrument(context, ring * 100 + local // 2)
            customer = abuse_customer(
                context,
                ring * 100 + local // 2,
                age_days=(4, 12, 90, 320)[local % 4],
                devices=persistent_devices,
                instruments=(rotating_instrument,),
                networks=persistent_networks,
                address=address(context, ring * 10 + local % 4),
            )
            selected_merchant = merchant(context, (local % 4) * 2)
            amount = sample_amount(context.rng, context.config, selected_merchant.category)
            if local == 0:
                amount = context.config.behavior.amount_min_paise
            elif local == 1:
                amount = context.config.behavior.high_value_paise * 2
            events.append(
                build_event(
                    event_id=f"pending_identity_rotation_{index}",
                    event_time=event_time(context, index, count, burst=True),
                    customer=customer,
                    device=persistent_devices[local % 2],
                    instrument=rotating_instrument,
                    network=persistent_networks[local % 2],
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
