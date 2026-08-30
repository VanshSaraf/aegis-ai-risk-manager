import hashlib
import json
from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from apps.api.app.core.enums import ScenarioType
from ml.training.config import SplitRatios
from ml.training.dataset import EvaluationMetadata

SPLIT_NAMES = ("train", "validation", "test")
ABUSE_SCENARIOS = tuple(
    scenario.value for scenario in ScenarioType if scenario != ScenarioType.NORMAL_TRAFFIC
)


class _UnionFind:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


@dataclass(frozen=True, slots=True)
class SplitResult:
    train: np.ndarray
    validation: np.ndarray
    test: np.ndarray
    supergroup_by_ring: dict[str, str]
    cross_ring_shared_entities: dict[str, tuple[str, ...]]
    first_validation_time: datetime
    first_test_time: datetime
    manifest: dict[str, object]

    def indices(self, split: str) -> np.ndarray:
        return getattr(self, split)


def build_abuse_supergroups(
    metadata: tuple[EvaluationMetadata, ...],
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    rings = sorted({item.ring_id for item in metadata if item.ring_id})
    union_find = _UnionFind(rings)
    rings_by_entity: dict[str, set[str]] = defaultdict(set)
    for item in metadata:
        if item.ring_id:
            for entity in item.abuse_entities:
                rings_by_entity[entity].add(item.ring_id)
    overlaps: dict[str, tuple[str, ...]] = {}
    for entity, entity_rings in rings_by_entity.items():
        ordered = sorted(entity_rings)
        if len(ordered) > 1:
            overlaps[entity] = tuple(ordered)
            for other in ordered[1:]:
                union_find.union(ordered[0], other)
    roots = {ring: union_find.find(ring) for ring in rings}
    unique_roots = {root: index for index, root in enumerate(sorted(set(roots.values())))}
    return (
        {ring: f"abuse-supergroup-{unique_roots[root]:05d}" for ring, root in roots.items()},
        dict(sorted(overlaps.items())),
    )


def _safe_boundaries(
    metadata: tuple[EvaluationMetadata, ...],
    supergroup_by_ring: dict[str, str],
    target_indices: tuple[int, int],
    *,
    require_all_scenarios: bool,
) -> tuple[datetime, datetime]:
    span: dict[str, list[datetime]] = defaultdict(list)
    scenarios_by_group: dict[str, set[str]] = defaultdict(set)
    for item in metadata:
        if item.ring_id:
            group = supergroup_by_ring[item.ring_id]
            span[group].append(item.event_time)
            scenarios_by_group[group].add(item.scenario)
    intervals = {group: (min(times), max(times)) for group, times in span.items()}
    timestamps = sorted({item.event_time for item in metadata})
    candidates = [
        timestamp
        for timestamp in timestamps[1:]
        if not any(start < timestamp <= end for start, end in intervals.values())
    ]
    if not candidates:
        raise ValueError("no safe chronological boundary exists without splitting an abuse group")
    event_times = [item.event_time for item in metadata]
    # Many legitimate timestamps represent the same abuse-group partition state. Keep the
    # timestamp closest to each desired row count for each distinct state.
    states: dict[frozenset[str], list[datetime]] = defaultdict(list)
    for timestamp in candidates:
        left = frozenset(group for group, (_, end) in intervals.items() if end < timestamp)
        states[left].append(timestamp)
    state_choices: dict[frozenset[str], tuple[datetime, datetime]] = {}
    for state, values in states.items():
        state_choices[state] = tuple(
            min(values, key=lambda value: abs(bisect_left(event_times, value) - target))
            for target in target_indices
        )  # type: ignore[assignment]
    all_groups = set(intervals)
    required = set(ABUSE_SCENARIOS)

    def scenarios(groups: set[str] | frozenset[str]) -> set[str]:
        return {scenario for group in groups for scenario in scenarios_by_group[group]}

    choices: list[tuple[int, datetime, datetime]] = []
    for first_state, first_times in state_choices.items():
        for second_state, second_times in state_choices.items():
            if not first_state < second_state:
                continue
            partitions = (
                set(first_state),
                set(second_state - first_state),
                all_groups - set(second_state),
            )
            if any(not partition for partition in partitions):
                continue
            if require_all_scenarios and any(
                scenarios(partition) != required for partition in partitions
            ):
                continue
            first_time, second_time = first_times[0], second_times[1]
            if first_time >= second_time:
                continue
            deviation = abs(bisect_left(event_times, first_time) - target_indices[0]) + abs(
                bisect_left(event_times, second_time) - target_indices[1]
            )
            choices.append((deviation, first_time, second_time))
    if not choices:
        qualifier = " with all abuse scenarios" if require_all_scenarios else ""
        raise ValueError(f"no valid three-way abuse-group split exists{qualifier}")
    _, first, second = min(choices)
    return first, second


def _summary(
    indices: np.ndarray,
    metadata: tuple[EvaluationMetadata, ...],
    supergroup_by_ring: dict[str, str],
) -> dict[str, object]:
    items = [metadata[int(index)] for index in indices]
    labels = Counter("abuse" if item.label else "legitimate" for item in items)
    rings = {item.ring_id for item in items if item.ring_id}
    return {
        "transaction_count": len(items),
        "class_counts": dict(sorted(labels.items())),
        "abuse_prevalence": sum(item.label for item in items) / len(items),
        "ring_count": len(rings),
        "supergroup_count": len({supergroup_by_ring[ring] for ring in rings}),
        "scenario_counts": dict(sorted(Counter(item.scenario for item in items).items())),
        "persona_counts": dict(
            sorted(Counter(item.persona for item in items if item.persona).items())
        ),
        "start_time": min(item.event_time for item in items).isoformat(),
        "end_time": max(item.event_time for item in items).isoformat(),
    }


def split_chronologically(
    metadata: tuple[EvaluationMetadata, ...],
    ratios: SplitRatios,
    *,
    require_all_scenarios: bool = True,
) -> SplitResult:
    if tuple(sorted(metadata, key=lambda item: (item.event_time, item.transaction_id))) != metadata:
        raise ValueError("metadata must be in chronological transaction-ID tie-break order")
    supergroup_by_ring, overlaps = build_abuse_supergroups(metadata)
    first_validation, first_test = _safe_boundaries(
        metadata,
        supergroup_by_ring,
        (
            round(len(metadata) * ratios.train),
            round(len(metadata) * (ratios.train + ratios.validation)),
        ),
        require_all_scenarios=require_all_scenarios,
    )
    if first_validation >= first_test:
        raise ValueError("safe temporal boundaries do not create three ordered splits")
    train = np.asarray(
        [index for index, item in enumerate(metadata) if item.event_time < first_validation],
        dtype=np.int64,
    )
    validation = np.asarray(
        [
            index
            for index, item in enumerate(metadata)
            if first_validation <= item.event_time < first_test
        ],
        dtype=np.int64,
    )
    test = np.asarray(
        [index for index, item in enumerate(metadata) if item.event_time >= first_test],
        dtype=np.int64,
    )
    result_parts = {"train": train, "validation": validation, "test": test}
    validate_split(
        result_parts,
        metadata,
        supergroup_by_ring,
        require_all_scenarios=require_all_scenarios,
    )
    manifest: dict[str, object] = {
        "boundaries": {
            "validation_starts_at": first_validation.isoformat(),
            "test_starts_at": first_test.isoformat(),
        },
        "splits": {
            name: _summary(indices, metadata, supergroup_by_ring)
            for name, indices in result_parts.items()
        },
        "overlap_audit": {
            "cross_ring_shared_entity_count": len(overlaps),
            "ring_count": len(supergroup_by_ring),
            "supergroup_count": len(set(supergroup_by_ring.values())),
        },
    }
    return SplitResult(
        train,
        validation,
        test,
        supergroup_by_ring,
        overlaps,
        first_validation,
        first_test,
        manifest,
    )


def validate_split(
    parts: dict[str, np.ndarray],
    metadata: tuple[EvaluationMetadata, ...],
    supergroup_by_ring: dict[str, str],
    *,
    require_all_scenarios: bool,
) -> None:
    id_sets: dict[str, set[str]] = {}
    ring_sets: dict[str, set[str]] = {}
    group_sets: dict[str, set[str]] = {}
    for name, indices in parts.items():
        items = [metadata[int(index)] for index in indices]
        if not items:
            raise ValueError(f"{name} split is empty")
        if {item.label for item in items} != {0, 1}:
            raise ValueError(f"{name} must contain both classes")
        scenarios = {item.scenario for item in items if item.label}
        if require_all_scenarios and scenarios != set(ABUSE_SCENARIOS):
            raise ValueError(
                f"{name} is missing abuse scenarios: {set(ABUSE_SCENARIOS) - scenarios}"
            )
        id_sets[name] = {item.transaction_id for item in items}
        ring_sets[name] = {item.ring_id for item in items if item.ring_id}
        group_sets[name] = {supergroup_by_ring[ring] for ring in ring_sets[name]}
    for index, left in enumerate(SPLIT_NAMES):
        for right in SPLIT_NAMES[index + 1 :]:
            if id_sets[left] & id_sets[right]:
                raise ValueError("transaction IDs overlap across splits")
            if ring_sets[left] & ring_sets[right]:
                raise ValueError("abuse rings overlap across splits")
            if group_sets[left] & group_sets[right]:
                raise ValueError("abuse supergroups overlap across splits")
    ordered = [[metadata[int(index)] for index in parts[name]] for name in SPLIT_NAMES]
    if not max(item.event_time for item in ordered[0]) < min(
        item.event_time for item in ordered[1]
    ):
        raise ValueError("train and validation are not strictly chronological")
    if not max(item.event_time for item in ordered[1]) < min(
        item.event_time for item in ordered[2]
    ):
        raise ValueError("validation and test are not strictly chronological")


def manifest_hash(manifest: dict[str, object]) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
