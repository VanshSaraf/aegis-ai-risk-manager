import hashlib
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from apps.api.app.core.enums import GraphEntityType
from packages.graph_engine.domain import GraphEntityRef, GraphTransaction


@dataclass(slots=True)
class TemporalEdge:
    first_seen_at: datetime
    last_seen_at: datetime
    observation_count: int = 1


def edge_key(left: GraphEntityRef, right: GraphEntityRef) -> tuple[GraphEntityRef, GraphEntityRef]:
    return (left, right) if left < right else (right, left)


class InMemoryGraphState:
    def __init__(self, transactions: Iterable[GraphTransaction] = ()) -> None:
        self.adjacency: dict[GraphEntityRef, set[GraphEntityRef]] = defaultdict(set)
        self.edges: dict[tuple[GraphEntityRef, GraphEntityRef], TemporalEdge] = {}
        self.node_first_seen: dict[GraphEntityRef, datetime] = {}
        self.transactions: list[GraphTransaction] = []
        for transaction in sorted(transactions, key=lambda item: item.event_time):
            self.observe(transaction)

    def observe(self, transaction: GraphTransaction) -> None:
        for entity in transaction.entities():
            self.node_first_seen.setdefault(entity, transaction.event_time)
            self.adjacency.setdefault(entity, set())
        for left, right in transaction.relationships():
            key = edge_key(left, right)
            metadata = self.edges.get(key)
            if metadata is None:
                self.edges[key] = TemporalEdge(transaction.event_time, transaction.event_time)
                self.adjacency[left].add(right)
                self.adjacency[right].add(left)
            else:
                metadata.last_seen_at = max(metadata.last_seen_at, transaction.event_time)
                metadata.observation_count += 1
        self.transactions.append(transaction)

    def observe_many(self, transactions: Iterable[GraphTransaction]) -> None:
        for transaction in transactions:
            self.observe(transaction)

    def has_node(self, entity: GraphEntityRef) -> bool:
        return entity in self.node_first_seen

    def has_edge(self, left: GraphEntityRef, right: GraphEntityRef) -> bool:
        return edge_key(left, right) in self.edges

    def neighbors(
        self, entity: GraphEntityRef, entity_type: GraphEntityType | None = None
    ) -> set[GraphEntityRef]:
        neighbors = self.adjacency.get(entity, set())
        if entity_type is None:
            return set(neighbors)
        return {neighbor for neighbor in neighbors if neighbor.entity_type == entity_type}

    def component(self, start: GraphEntityRef) -> frozenset[GraphEntityRef]:
        if not self.has_node(start):
            return frozenset()
        seen = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in self.adjacency[current] - seen:
                seen.add(neighbor)
                queue.append(neighbor)
        return frozenset(seen)

    def touched_components(
        self, transaction: GraphTransaction
    ) -> tuple[frozenset[GraphEntityRef], ...]:
        components: dict[frozenset[GraphEntityRef], None] = {}
        for entity in transaction.entities():
            component = self.component(entity)
            if component:
                components[component] = None
        return tuple(sorted(components, key=lambda value: sorted(value)[0]))

    def component_edges(
        self, members: frozenset[GraphEntityRef]
    ) -> dict[tuple[GraphEntityRef, GraphEntityRef], TemporalEdge]:
        return {
            key: metadata
            for key, metadata in self.edges.items()
            if key[0] in members and key[1] in members
        }

    def all_components(self) -> tuple[frozenset[GraphEntityRef], ...]:
        remaining = set(self.node_first_seen)
        components: list[frozenset[GraphEntityRef]] = []
        while remaining:
            component = self.component(min(remaining))
            components.append(component)
            remaining.difference_update(component)
        return tuple(components)

    @staticmethod
    def fingerprint(members: frozenset[GraphEntityRef]) -> str:
        canonical = "|".join(sorted(member.canonical() for member in members))
        return hashlib.sha256(canonical.encode()).hexdigest()[:20]
