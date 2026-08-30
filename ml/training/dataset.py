import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from apps.api.app.core.enums import GroundTruthLabel
from ml.training.config import TrainingConfig
from packages.graph_engine.domain import DetectedCluster, GraphTransaction
from packages.graph_engine.offline import (
    build_synthetic_graph,
    generated_event_to_graph_transaction,
)
from packages.graph_engine.registry import GRAPH_METRIC_NAMES, GRAPH_VERSION
from packages.risk_engine.features.offline import (
    build_offline_feature_vectors,
    generated_event_to_feature_transaction,
)
from packages.risk_engine.features.registry import FEATURE_NAMES, FEATURE_VERSION
from packages.synthetic.config import load_generation_config
from packages.synthetic.domain import SyntheticDataset
from packages.synthetic.generator import generate_dataset
from packages.synthetic.manifest import GenerationManifest, build_manifest

COMBINED_FEATURE_NAMES = FEATURE_NAMES + GRAPH_METRIC_NAMES
FORBIDDEN_INPUT_TERMS = (
    "ground_truth",
    "label",
    "scenario",
    "ring",
    "persona",
    "dataset",
    "scenario_run",
    "status",
    "failure_code",
    "cluster_id",
    "transaction_id",
    "public_id",
)


@dataclass(frozen=True, slots=True)
class PredictiveExample:
    transaction_id: str
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class EvaluationMetadata:
    transaction_id: str
    event_time: datetime
    label: int
    scenario: str
    ring_id: str | None
    persona: str | None
    abuse_entities: tuple[str, ...]


@dataclass(slots=True)
class AssembledDataset:
    feature_names: tuple[str, ...]
    X: np.ndarray
    predictive_examples: tuple[PredictiveExample, ...]
    metadata: tuple[EvaluationMetadata, ...]
    graph_baseline: np.ndarray
    graph_transactions: tuple[GraphTransaction, ...]
    clusters: tuple[DetectedCluster, ...]
    synthetic_dataset: SyntheticDataset
    manifest: GenerationManifest
    runtimes: dict[str, float]

    @property
    def y(self) -> np.ndarray:
        return np.asarray([item.label for item in self.metadata], dtype=np.int8)


def _stable_file_hash(path: Path) -> str:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def schema_hashes(repository_root: Path) -> dict[str, str]:
    return {
        "feature_schema_hash": _stable_file_hash(
            repository_root / "ml/artifacts/features-v1/schema.json"
        ),
        "graph_schema_hash": _stable_file_hash(
            repository_root / "ml/artifacts/graph-v1/schema.json"
        ),
    }


async def assemble_benchmark(config: TrainingConfig) -> AssembledDataset:
    if config.feature_version != FEATURE_VERSION or config.graph_version != GRAPH_VERSION:
        raise ValueError("training config does not reference the frozen feature/graph versions")
    generation_config = load_generation_config(
        Path(config.generation_config_path) if config.generation_config_path else None
    )
    generation_config = generation_config.model_copy(
        update={
            "dataset": generation_config.dataset.model_copy(
                update={
                    "seed": config.benchmark_seed,
                    "transaction_count": config.transaction_count,
                }
            ),
            "abuse": generation_config.abuse.model_copy(
                update={"prevalence": config.abuse_prevalence}
            ),
        }
    )
    started = time.perf_counter()
    synthetic = generate_dataset(generation_config)
    generation_seconds = time.perf_counter() - started

    started = time.perf_counter()
    vectors = await build_offline_feature_vectors(
        [generated_event_to_feature_transaction(event) for event in synthetic.events]
    )
    feature_seconds = time.perf_counter() - started

    started = time.perf_counter()
    graph = await build_synthetic_graph(synthetic)
    graph_seconds = time.perf_counter() - started

    vectors_by_id = {vector.transaction_public_id: vector for vector in vectors}
    graph_by_id = {item.transaction_public_id: item for item in graph.assessments}
    expected_ids = {event.facts.event_id for event in synthetic.events}
    if len(vectors_by_id) != len(expected_ids) or set(vectors_by_id) != expected_ids:
        raise ValueError("every transaction must have exactly one features-v1 vector")
    if len(graph_by_id) != len(expected_ids) or set(graph_by_id) != expected_ids:
        raise ValueError("every transaction must have exactly one graph-v1 assessment")

    examples: list[PredictiveExample] = []
    metadata: list[EvaluationMetadata] = []
    graph_baseline: list[bool] = []
    graph_transactions: list[GraphTransaction] = []
    for event in synthetic.events:
        event_id = event.facts.event_id
        vector = vectors_by_id[event_id]
        assessment = graph_by_id[event_id]
        values = tuple(float(vector.values[name]) for name in FEATURE_NAMES) + tuple(
            float(assessment.metrics[name]) for name in GRAPH_METRIC_NAMES
        )
        examples.append(PredictiveExample(event_id, values))
        graph_transaction = generated_event_to_graph_transaction(event)
        graph_transactions.append(graph_transaction)
        metadata.append(
            EvaluationMetadata(
                transaction_id=event_id,
                event_time=event.facts.event_time,
                label=int(event.truth.label == GroundTruthLabel.COORDINATED_ABUSE),
                scenario=event.truth.scenario_type.value,
                ring_id=event.truth.ring_id,
                persona=event.truth.persona.value if event.truth.persona else None,
                abuse_entities=tuple(entity.canonical() for entity in graph_transaction.entities())
                if event.truth.ring_id
                else (),
            )
        )
        graph_baseline.append(assessment.candidate_cluster)
    matrix = np.asarray([item.values for item in examples], dtype=np.float64)
    if matrix.shape != (len(synthetic.events), 77):
        raise ValueError(f"combined matrix must be N x 77, received {matrix.shape}")
    if not np.isfinite(matrix).all():
        raise ValueError("predictive matrix contains non-finite values")
    return AssembledDataset(
        feature_names=COMBINED_FEATURE_NAMES,
        X=matrix,
        predictive_examples=tuple(examples),
        metadata=tuple(metadata),
        graph_baseline=np.asarray(graph_baseline, dtype=bool),
        graph_transactions=tuple(graph_transactions),
        clusters=tuple(graph.clusters),
        synthetic_dataset=synthetic,
        manifest=build_manifest(synthetic, generation_config),
        runtimes={
            "synthetic_generation_seconds": generation_seconds,
            "feature_generation_seconds": feature_seconds,
            "graph_generation_seconds": graph_seconds,
        },
    )
