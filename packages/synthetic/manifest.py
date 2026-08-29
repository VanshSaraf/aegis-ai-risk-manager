import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from apps.api.app.core.enums import GroundTruthLabel
from packages.synthetic.config import GenerationConfig
from packages.synthetic.domain import SyntheticDataset


class GenerationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    generator_version: str
    seed: int
    config_hash: str
    transaction_count: int
    legitimate_count: int
    coordinated_abuse_count: int
    scenario_counts: dict[str, int]
    persona_counts: dict[str, int]
    entity_counts: dict[str, int]
    start_time: datetime
    end_time: datetime

    @property
    def abuse_prevalence(self) -> float:
        if self.transaction_count == 0:
            return 0.0
        return self.coordinated_abuse_count / self.transaction_count


def build_manifest(dataset: SyntheticDataset, config: GenerationConfig) -> GenerationManifest:
    events = dataset.events
    scenario_counts = Counter(event.truth.scenario_type.value for event in events)
    persona_counts = Counter(
        event.truth.persona.value for event in events if event.truth.persona is not None
    )
    legitimate_count = sum(event.truth.label == GroundTruthLabel.LEGITIMATE for event in events)
    entity_counts = {
        "customers": len({event.facts.customer_ref for event in events}),
        "devices": len({event.facts.device_fingerprint for event in events}),
        "payment_instruments": len({event.facts.instrument_fingerprint for event in events}),
        "ips": len({event.facts.ip_hash for event in events}),
        "addresses": len({event.facts.address_fingerprint for event in events}),
        "merchants": len({event.facts.merchant_ref for event in events}),
    }
    version = f"{dataset.generator_version}-seed-{dataset.seed}-{dataset.config_hash[:10]}"
    return GenerationManifest(
        dataset_version=version,
        generator_version=dataset.generator_version,
        seed=dataset.seed,
        config_hash=dataset.config_hash,
        transaction_count=len(events),
        legitimate_count=legitimate_count,
        coordinated_abuse_count=len(events) - legitimate_count,
        scenario_counts=dict(sorted(scenario_counts.items())),
        persona_counts=dict(sorted(persona_counts.items())),
        entity_counts=entity_counts,
        start_time=events[0].facts.event_time,
        end_time=events[-1].facts.event_time,
    )


def write_dataset_artifacts(
    dataset: SyntheticDataset, manifest: GenerationManifest, output_directory: Path
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = output_directory / "manifest.json"
    events_path = output_directory / "events.jsonl"
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with events_path.open("w", encoding="utf-8") as stream:
        for event in dataset.events:
            stream.write(json.dumps(event.canonical(), sort_keys=True) + "\n")
