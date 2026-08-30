import hashlib
from datetime import timedelta

from apps.api.app.core.enums import GraphEntityType
from packages.graph_engine.domain import DetectedCluster, GraphEntityRef, GraphSignal
from packages.graph_engine.engine import multipartite_density, structural_score
from packages.graph_engine.registry import GRAPH_VERSION
from packages.graph_engine.state import InMemoryGraphState


class StructuralClusterDetector:
    """Deterministic multi-signal detector; no labels, probabilities, or IP-only rules."""

    def discover(self, state: InMemoryGraphState) -> list[DetectedCluster]:
        detections: list[DetectedCluster] = []
        for members in state.all_components():
            customers = {
                member for member in members if member.entity_type == GraphEntityType.CUSTOMER
            }
            instruments = {
                member
                for member in members
                if member.entity_type == GraphEntityType.PAYMENT_INSTRUMENT
            }
            devices = {member for member in members if member.entity_type == GraphEntityType.DEVICE}
            ips = {member for member in members if member.entity_type == GraphEntityType.IP}
            addresses = {
                member for member in members if member.entity_type == GraphEntityType.ADDRESS
            }
            if len(customers) < 3 or len(instruments) < 3 or not devices:
                continue
            qualifying_devices = [
                device
                for device in devices
                if len(state.neighbors(device, GraphEntityType.CUSTOMER)) >= 3
                and len(state.neighbors(device, GraphEntityType.PAYMENT_INSTRUMENT)) >= 3
            ]
            if not qualifying_devices:
                continue
            component_edges = state.component_edges(members)
            last_seen = max(metadata.last_seen_at for metadata in component_edges.values())
            first_seen = min(metadata.first_seen_at for metadata in component_edges.values())
            recent_edges = sum(
                last_seen - timedelta(minutes=10) <= metadata.first_seen_at <= last_seen
                for metadata in component_edges.values()
            )
            if recent_edges < 6 and len(component_edges) < 12:
                continue
            primary_device = min(qualifying_devices)
            device_customers = len(state.neighbors(primary_device, GraphEntityType.CUSTOMER))
            device_instruments = len(
                state.neighbors(primary_device, GraphEntityType.PAYMENT_INSTRUMENT)
            )
            density = multipartite_density(
                len(component_edges),
                len(customers),
                len(devices),
                len(instruments),
                len(ips),
                len(addresses),
            )
            score = structural_score(
                device_customer_degree=device_customers,
                device_instrument_degree=device_instruments,
                customer_count=len(customers),
                instrument_count=len(instruments),
                device_count=len(devices),
                density=density,
                recent_edges=recent_edges,
            )
            if score < 0.45:
                continue
            signals = (
                GraphSignal(
                    "DEVICE_MULTI_CUSTOMER_CONCENTRATION",
                    min(1.0, device_customers / 6),
                    device_customers,
                    3,
                    {"device_id": primary_device.public_id},
                ),
                GraphSignal(
                    "DEVICE_MULTI_INSTRUMENT_CONCENTRATION",
                    min(1.0, device_instruments / 8),
                    device_instruments,
                    3,
                    {"device_id": primary_device.public_id},
                ),
                GraphSignal(
                    "RAPID_RELATIONSHIP_EXPANSION",
                    min(1.0, recent_edges / 10),
                    recent_edges,
                    6,
                    {"window": "10m"},
                ),
            )
            fingerprint_source = f"{GRAPH_VERSION}|{primary_device.canonical()}"
            fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()[:32]
            transactions = [
                transaction
                for transaction in state.transactions
                if any(entity in members for entity in transaction.entities())
            ]
            detections.append(
                DetectedCluster(
                    fingerprint=fingerprint,
                    members=members,
                    structural_score=score,
                    signals=signals,
                    transaction_count=len(transactions),
                    exposure_paise=sum(transaction.amount_paise for transaction in transactions),
                    first_seen_at=first_seen,
                    last_seen_at=last_seen,
                )
            )
        return detections


def membership_reason(
    member: GraphEntityRef,
    detection: DetectedCluster,
) -> dict[str, object]:
    return {
        "basis": "point_in_time_structural_connectivity",
        "entity_type": member.entity_type.value,
        "cluster_fingerprint": detection.fingerprint,
        "signals": [signal.code for signal in detection.signals],
    }
