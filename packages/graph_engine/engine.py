from datetime import timedelta

from apps.api.app.core.enums import GraphEntityType
from apps.api.app.core.time import utc_now
from packages.graph_engine.domain import (
    GraphAssessment,
    GraphEntityRef,
    GraphSignal,
    GraphTransaction,
)
from packages.graph_engine.registry import GRAPH_VERSION
from packages.graph_engine.state import InMemoryGraphState


def _count_type(members: frozenset[GraphEntityRef], entity_type: GraphEntityType) -> int:
    return sum(member.entity_type == entity_type for member in members)


def multipartite_density(
    edge_count: int,
    customer_count: int,
    device_count: int,
    instrument_count: int,
    ip_count: int,
    address_count: int,
) -> float:
    capacity = (
        customer_count * device_count
        + customer_count * instrument_count
        + customer_count * ip_count
        + customer_count * address_count
        + instrument_count * device_count
    )
    return edge_count / capacity if capacity else 0.0


def structural_score(
    *,
    device_customer_degree: int,
    device_instrument_degree: int,
    customer_count: int,
    instrument_count: int,
    device_count: int,
    density: float,
    recent_edges: int,
) -> float:
    identity_concentration = min(1.0, (device_customer_degree + device_instrument_degree) / 8)
    cross_entity_reuse = min(
        1.0,
        (customer_count + instrument_count) / (max(device_count, 1) * 8),
    )
    relationship_velocity = min(1.0, recent_edges / 10)
    component_structure = (
        min(1.0, density * 2) if customer_count >= 3 and instrument_count >= 3 else 0.0
    )
    return round(
        0.35 * identity_concentration
        + 0.25 * cross_entity_reuse
        + 0.25 * relationship_velocity
        + 0.15 * component_structure,
        6,
    )


class GraphEngine:
    graph_version = GRAPH_VERSION

    def assess(
        self,
        current: GraphTransaction,
        state: InMemoryGraphState,
    ) -> GraphAssessment:
        if any(transaction.event_time >= current.event_time for transaction in state.transactions):
            raise ValueError("graph state contains a current or future transaction")

        customer, instrument, device, ip, address = current.entities()
        components = state.touched_components(current)
        members = frozenset(member for component in components for member in component)
        component_edges = state.component_edges(members)
        customer_count = _count_type(members, GraphEntityType.CUSTOMER)
        device_count = _count_type(members, GraphEntityType.DEVICE)
        instrument_count = _count_type(members, GraphEntityType.PAYMENT_INSTRUMENT)
        ip_count = _count_type(members, GraphEntityType.IP)
        address_count = _count_type(members, GraphEntityType.ADDRESS)
        density = multipartite_density(
            len(component_edges),
            customer_count,
            device_count,
            instrument_count,
            ip_count,
            address_count,
        )

        device_customers = state.neighbors(device, GraphEntityType.CUSTOMER)
        device_instruments = state.neighbors(device, GraphEntityType.PAYMENT_INSTRUMENT)
        ip_customers = state.neighbors(ip, GraphEntityType.CUSTOMER)
        ip_devices = {
            linked_device
            for linked_customer in ip_customers
            for linked_device in state.neighbors(linked_customer, GraphEntityType.DEVICE)
        }
        address_customers = state.neighbors(address, GraphEntityType.CUSTOMER)
        instrument_devices = state.neighbors(instrument, GraphEntityType.DEVICE)
        instrument_customers = state.neighbors(instrument, GraphEntityType.CUSTOMER)
        two_hop_customers = (device_customers | ip_customers) - {customer}

        ten_minutes_ago = current.event_time - timedelta(minutes=10)
        recent_edges = sum(
            ten_minutes_ago <= metadata.first_seen_at < current.event_time
            for metadata in component_edges.values()
        )
        device_new_identities = sum(
            ten_minutes_ago
            <= state.edges[
                (device, neighbor) if device < neighbor else (neighbor, device)
            ].first_seen_at
            < current.event_time
            for neighbor in device_customers | device_instruments
        )
        new_edges = tuple(
            not state.has_edge(left, right) for left, right in current.relationships()
        )
        score = structural_score(
            device_customer_degree=len(device_customers),
            device_instrument_degree=len(device_instruments),
            customer_count=customer_count,
            instrument_count=instrument_count,
            device_count=device_count,
            density=density,
            recent_edges=recent_edges,
        )

        metrics: dict[str, float | int | bool] = {
            "device_customer_degree": len(device_customers),
            "device_instrument_degree": len(device_instruments),
            "ip_customer_degree": len(ip_customers),
            "ip_device_degree": len(ip_devices),
            "address_customer_degree": len(address_customers),
            "instrument_device_degree": len(instrument_devices),
            "instrument_customer_degree": len(instrument_customers),
            "component_node_count": len(members),
            "component_edge_count": len(component_edges),
            "component_customer_count": customer_count,
            "component_device_count": device_count,
            "component_instrument_count": instrument_count,
            "component_ip_count": ip_count,
            "component_address_count": address_count,
            "component_multipartite_density": density,
            "new_customer_device_edge": new_edges[0],
            "new_customer_instrument_edge": new_edges[1],
            "new_customer_ip_edge": new_edges[2],
            "new_customer_address_edge": new_edges[3],
            "new_instrument_device_edge": new_edges[4],
            "preexisting_component_count": len(components),
            "components_bridged_by_transaction": max(0, len(components) - 1),
            "customer_two_hop_customer_count_via_device_or_ip": len(two_hop_customers),
            "component_new_edges_10m": recent_edges,
            "device_new_identities_10m": device_new_identities,
        }

        signals: list[GraphSignal] = []
        if len(device_customers) >= 3:
            signals.append(
                GraphSignal(
                    "DEVICE_MULTI_CUSTOMER_CONCENTRATION",
                    min(1.0, len(device_customers) / 6),
                    len(device_customers),
                    3,
                    {"device_id": device.public_id},
                )
            )
        if len(device_instruments) >= 4:
            signals.append(
                GraphSignal(
                    "DEVICE_MULTI_INSTRUMENT_CONCENTRATION",
                    min(1.0, len(device_instruments) / 8),
                    len(device_instruments),
                    4,
                    {"device_id": device.public_id},
                )
            )
        if recent_edges >= 6 or device_new_identities >= 4:
            signals.append(
                GraphSignal(
                    "RAPID_RELATIONSHIP_EXPANSION",
                    min(1.0, max(recent_edges / 10, device_new_identities / 6)),
                    max(recent_edges, device_new_identities),
                    6,
                    {"window": "10m"},
                )
            )
        if len(components) > 1:
            signals.append(
                GraphSignal(
                    "MULTI_COMPONENT_BRIDGE",
                    min(1.0, (len(components) - 1) / 3),
                    len(components) - 1,
                    1,
                    {"preexisting_components": len(components)},
                )
            )
        if customer_count >= 3 and instrument_count >= 3 and density >= 0.15:
            signals.append(
                GraphSignal(
                    "DENSE_MULTI_ENTITY_STRUCTURE",
                    min(1.0, density / 0.4),
                    density,
                    0.15,
                    {
                        "customers": customer_count,
                        "instruments": instrument_count,
                    },
                )
            )

        candidate_cluster = (
            customer_count >= 3
            and instrument_count >= 3
            and len(device_customers) >= 3
            and len(device_instruments) >= 3
            and (recent_edges >= 5 or len(component_edges) >= 12)
            and score >= 0.45
        )
        max_source_event_time = max(
            (
                max(metadata.first_seen_at, metadata.last_seen_at)
                for metadata in component_edges.values()
            ),
            default=None,
        )
        return GraphAssessment(
            graph_version=self.graph_version,
            transaction_public_id=current.transaction_public_id,
            metrics=metrics,
            signals=tuple(signals),
            structural_score=score,
            touched_component_fingerprints=tuple(
                state.fingerprint(component) for component in components
            ),
            candidate_cluster=candidate_cluster,
            computed_at=utc_now(),
            max_source_event_time=max_source_event_time,
        )
