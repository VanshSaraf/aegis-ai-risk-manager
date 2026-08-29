from apps.api.app.core.enums import GroundTruthLabel, ScenarioType
from packages.synthetic.behavior import build_event, sample_amount
from packages.synthetic.domain import GeneratedEvent, LegitimatePersona, SyntheticGroundTruth
from packages.synthetic.scenarios.base import ScenarioContext


class NormalTrafficGenerator:
    scenario_type = ScenarioType.NORMAL_TRAFFIC

    def generate(self, context: ScenarioContext, count: int) -> list[GeneratedEvent]:
        if count <= 0:
            return []
        customers = list(context.population.customers)
        representatives = {
            persona: [customer for customer in customers if customer.persona == persona][:2]
            for persona in LegitimatePersona
        }
        guaranteed = [
            customer for persona in LegitimatePersona for customer in representatives[persona]
        ]
        events: list[GeneratedEvent] = []
        for index in range(count):
            if index < len(guaranteed):
                customer = guaranteed[index]
            elif index in (10, 11):
                customer = representatives[LegitimatePersona.POWER_SHOPPER][0]
            else:
                customer = context.rng.choice(customers)
            persona = customer.persona
            assert persona is not None
            device = context.rng.choice(customer.devices)
            instrument = context.rng.choice(customer.instruments)
            network = context.rng.choice(customer.networks)
            if persona == LegitimatePersona.TRAVELLER and index < len(guaranteed):
                device = customer.devices[-1]
                network = customer.networks[-1]
            if index == 10:
                device = customer.devices[0]
                instrument = customer.instruments[0]
            elif index == 11:
                device = customer.devices[0]
                instrument = customer.instruments[1]
            merchant = context.rng.choice(context.population.merchants)
            scale = 1.0
            if persona == LegitimatePersona.POWER_SHOPPER:
                scale = 1.35
            elif persona == LegitimatePersona.TRAVELLER and merchant.category == "TRAVEL":
                scale = 1.6
            amount = sample_amount(context.rng, context.config, merchant.category, scale=scale)
            if index == 0:
                amount = context.config.behavior.amount_min_paise
            elif index == 1:
                amount = context.config.behavior.high_value_paise * 2
            failed = index == 2 or context.rng.probability(
                context.config.behavior.legitimate_failure_rate
            )
            truth = SyntheticGroundTruth(
                label=GroundTruthLabel.LEGITIMATE,
                scenario_type=ScenarioType.NORMAL_TRAFFIC,
                persona=persona,
            )
            events.append(
                build_event(
                    event_id=f"pending_normal_{index}",
                    event_time=context.start_time + context.duration * context.rng.uniform(),
                    customer=customer,
                    device=device,
                    instrument=instrument,
                    network=network,
                    address=customer.address,
                    merchant=merchant,
                    amount_paise=amount,
                    failed=failed,
                    truth=truth,
                )
            )
        return events
