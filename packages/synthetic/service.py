from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.enums import GroundTruthLabel, ScenarioType, TransactionStatus
from apps.api.app.core.ids import generate_public_id
from apps.api.app.core.time import utc_now
from apps.api.app.models import DatasetVersion, ScenarioRun
from apps.api.app.schemas.internal import TrustedSyntheticContext
from apps.api.app.services.transactions import ingest_transaction
from packages.synthetic.config import GenerationConfig
from packages.synthetic.domain import SyntheticDataset
from packages.synthetic.generator import generate_dataset
from packages.synthetic.manifest import (
    GenerationManifest,
    build_manifest,
    write_dataset_artifacts,
)
from packages.synthetic.validation import ValidationReport, validate_dataset


@dataclass(frozen=True, slots=True)
class GenerationResult:
    dataset: SyntheticDataset
    manifest: GenerationManifest
    validation: ValidationReport
    scenario_run_ids: dict[ScenarioType, str]
    elapsed_seconds: float
    output_directory: Path | None


async def _create_registry_records(
    session: AsyncSession,
    config: GenerationConfig,
    manifest: GenerationManifest,
    scenario: ScenarioType | None,
) -> dict[ScenarioType, str]:
    registry_config = {
        "generation_config": config.canonical_dict(),
        "manifest": manifest.model_dump(mode="json"),
        "isolated_scenario": scenario.value if scenario else None,
    }
    existing = await session.get(DatasetVersion, manifest.dataset_version)
    if existing is None:
        session.add(
            DatasetVersion(
                version=manifest.dataset_version,
                generator_version=manifest.generator_version,
                seed=manifest.seed,
                config=registry_config,
                transaction_count=manifest.transaction_count,
                legitimate_count=manifest.legitimate_count,
                abuse_count=manifest.coordinated_abuse_count,
            )
        )
    elif (
        existing.generator_version != manifest.generator_version
        or existing.seed != manifest.seed
        or existing.config != registry_config
        or existing.transaction_count != manifest.transaction_count
        or existing.legitimate_count != manifest.legitimate_count
        or existing.abuse_count != manifest.coordinated_abuse_count
    ):
        raise ValueError(
            f"Dataset version conflicts with its existing registry record: "
            f"{manifest.dataset_version}"
        )
    scenario_run_ids: dict[ScenarioType, str] = {}
    for scenario_name, count in manifest.scenario_counts.items():
        if count == 0:
            continue
        scenario_type = ScenarioType(scenario_name)
        public_id = generate_public_id("run")
        scenario_run_ids[scenario_type] = public_id
        session.add(
            ScenarioRun(
                public_id=public_id,
                scenario_type=scenario_type,
                seed=config.dataset.seed,
                status="RUNNING",
                config={
                    "dataset_version": manifest.dataset_version,
                    "event_count": count,
                    "config_hash": manifest.config_hash,
                },
                started_at=utc_now(),
                completed_at=None,
            )
        )
    await session.commit()
    return scenario_run_ids


async def generate_and_ingest(
    session: AsyncSession,
    config: GenerationConfig,
    *,
    scenario: ScenarioType | None = None,
    output_root: Path | None = None,
) -> GenerationResult:
    started = perf_counter()
    dataset = generate_dataset(config, scenario)
    manifest = build_manifest(dataset, config)
    validation = validate_dataset(dataset, manifest, config, scenario)
    if not validation.passed:
        messages = "; ".join(issue.message for issue in validation.issues)
        raise ValueError(f"Synthetic dataset validation failed: {messages}")

    scenario_run_ids = await _create_registry_records(session, config, manifest, scenario)
    try:
        for event in dataset.events:
            truth = event.truth
            scenario_run_id = scenario_run_ids[truth.scenario_type]
            persisted_facts = event.facts.model_copy(
                update={"event_id": f"{event.facts.event_id}__{scenario_run_id}"}
            )
            context = TrustedSyntheticContext(
                scenario_run_public_id=scenario_run_id,
                label=truth.label,
                scenario_type=truth.scenario_type,
                ring_id=truth.ring_id,
                persona=truth.persona.value if truth.persona else None,
            )
            await ingest_transaction(session, persisted_facts, synthetic_context=context)
    except Exception:
        for public_id in scenario_run_ids.values():
            run = await session.scalar(
                select(ScenarioRun).where(ScenarioRun.public_id == public_id)
            )
            if run is not None:
                run.status = "FAILED"
                run.completed_at = utc_now()
        await session.commit()
        raise

    completed_at = utc_now()
    for public_id in scenario_run_ids.values():
        run = await session.scalar(select(ScenarioRun).where(ScenarioRun.public_id == public_id))
        if run is not None:
            run.status = "COMPLETED"
            run.completed_at = completed_at
    await session.commit()

    output_directory = output_root / manifest.dataset_version if output_root else None
    if output_directory is not None:
        write_dataset_artifacts(dataset, manifest, output_directory)
    return GenerationResult(
        dataset=dataset,
        manifest=manifest,
        validation=validation,
        scenario_run_ids=scenario_run_ids,
        elapsed_seconds=perf_counter() - started,
        output_directory=output_directory,
    )


def format_generation_report(result: GenerationResult) -> str:
    manifest = result.manifest
    abuse_ring_count = len(
        {event.truth.ring_id for event in result.dataset.events if event.truth.ring_id}
    )
    class_events = {
        label: [event for event in result.dataset.events if event.truth.label == label]
        for label in GroundTruthLabel
    }
    class_summaries: list[str] = []
    shared_network_summaries: list[str] = []
    for label, events in class_events.items():
        if not events:
            continue
        amounts = [event.facts.amount_paise for event in events]
        failures = sum(event.facts.status == TransactionStatus.FAILED for event in events)
        customers_by_ip: dict[str, set[str]] = defaultdict(set)
        for event in events:
            customers_by_ip[event.facts.ip_hash].add(event.facts.customer_ref)
        shared_networks = sum(len(customers) > 1 for customers in customers_by_ip.values())
        class_summaries.append(
            f"{label.value}: failure_rate={failures / len(events):.2%}, "
            f"amount_paise[min/median/max]={min(amounts)}/{int(median(amounts))}/{max(amounts)}"
        )
        shared_network_summaries.append(f"{label.value}={shared_networks}")
    lines = [
        f"Dataset version: {manifest.dataset_version}",
        f"Seed: {manifest.seed}",
        f"Transactions: {manifest.transaction_count}",
        f"Legitimate: {manifest.legitimate_count}",
        f"Coordinated abuse: {manifest.coordinated_abuse_count}",
        f"Abuse prevalence: {manifest.abuse_prevalence:.2%}",
        "Scenario counts: "
        + ", ".join(f"{key}={value}" for key, value in manifest.scenario_counts.items()),
        "Persona counts: "
        + ", ".join(f"{key}={value}" for key, value in manifest.persona_counts.items()),
        "Entities: " + ", ".join(f"{key}={value}" for key, value in manifest.entity_counts.items()),
        f"Abuse rings: {abuse_ring_count}",
        "Class summaries: " + " | ".join(class_summaries),
        "Shared networks: " + ", ".join(shared_network_summaries),
        f"Validation: {result.validation.status}",
        f"Runtime seconds: {result.elapsed_seconds:.3f}",
    ]
    if result.validation.issues:
        lines.append(
            "Validation issues: "
            + "; ".join(
                f"{issue.severity.value}:{issue.code}" for issue in result.validation.issues
            )
        )
    if result.output_directory:
        lines.append(f"Output: {result.output_directory}")
    return "\n".join(lines)
