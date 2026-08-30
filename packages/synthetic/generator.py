import hashlib

from apps.api.app.core.enums import ScenarioType
from packages.synthetic.config import GenerationConfig
from packages.synthetic.domain import GeneratedEvent, SyntheticDataset
from packages.synthetic.population import build_population
from packages.synthetic.rng import RandomStream
from packages.synthetic.scenarios.account_farm import AccountFarmGenerator
from packages.synthetic.scenarios.base import ScenarioContext, ScenarioGenerator
from packages.synthetic.scenarios.card_testing import CardTestingGenerator
from packages.synthetic.scenarios.collusive_ring import CollusiveRingGenerator
from packages.synthetic.scenarios.identity_rotation import IdentityRotationGenerator
from packages.synthetic.scenarios.normal import NormalTrafficGenerator

SCENARIO_GENERATORS: dict[ScenarioType, ScenarioGenerator] = {
    ScenarioType.NORMAL_TRAFFIC: NormalTrafficGenerator(),
    ScenarioType.CARD_TESTING: CardTestingGenerator(),
    ScenarioType.ACCOUNT_FARM: AccountFarmGenerator(),
    ScenarioType.IDENTITY_ROTATION: IdentityRotationGenerator(),
    ScenarioType.COLLUSIVE_RING: CollusiveRingGenerator(),
}


def _generators_and_population(config: GenerationConfig):
    if config.generator_version == "synthetic-v1":
        return SCENARIO_GENERATORS, build_population
    if config.generator_version == "synthetic-v2":
        from packages.synthetic.v2 import SCENARIO_GENERATORS_V2, build_population_v2

        return SCENARIO_GENERATORS_V2, build_population_v2
    raise ValueError(f"unsupported generator version: {config.generator_version}")


def _event_counts(
    config: GenerationConfig, scenario: ScenarioType | None
) -> dict[ScenarioType, int]:
    total = config.dataset.transaction_count
    if scenario is not None:
        return {item: total if item == scenario else 0 for item in ScenarioType}
    abuse_count = round(total * config.abuse.prevalence)
    rng = RandomStream(config.dataset.seed, "scenario_allocation")
    abuse_counts = rng.weighted_counts(abuse_count, config.abuse.scenario_weights)
    return {
        ScenarioType.NORMAL_TRAFFIC: total - abuse_count,
        **abuse_counts,
    }


def generate_dataset(
    config: GenerationConfig, scenario: ScenarioType | None = None
) -> SyntheticDataset:
    counts = _event_counts(config, scenario)
    generators, population_builder = _generators_and_population(config)
    population = population_builder(config, counts[ScenarioType.NORMAL_TRAFFIC])
    events: list[GeneratedEvent] = []
    for scenario_type in ScenarioType:
        count = counts[scenario_type]
        if count == 0:
            continue
        context = ScenarioContext(
            config=config,
            population=population,
            rng=RandomStream(config.dataset.seed, scenario_type.value.lower()),
            scenario=scenario_type,
        )
        events.extend(generators[scenario_type].generate(context, count))

    events.sort(key=lambda event: (event.facts.event_time, event.facts.event_id))
    mode = scenario.value if scenario else "MIXED"
    config_hash = hashlib.sha256(f"{config.config_hash()}:{mode}".encode()).hexdigest()
    numbered = tuple(
        GeneratedEvent(
            facts=event.facts.model_copy(
                update={
                    "event_id": (f"evt_syn_{config.dataset.seed}_{config_hash[:8]}_{index:08d}")
                }
            ),
            truth=event.truth,
        )
        for index, event in enumerate(events)
    )
    return SyntheticDataset(
        events=numbered,
        population=population,
        generator_version=config.generator_version,
        seed=config.dataset.seed,
        config_hash=config_hash,
    )
