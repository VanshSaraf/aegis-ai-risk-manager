from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Literal

GRAPH_VERSION = "graph-v1"


class GraphMetricFamily(StrEnum):
    LOCAL_ENTITY = "LOCAL_ENTITY"
    COMPONENT = "COMPONENT"
    NOVELTY = "NOVELTY"
    CONNECTIVITY = "CONNECTIVITY"
    TEMPORAL_STRUCTURE = "TEMPORAL_STRUCTURE"


@dataclass(frozen=True, slots=True)
class GraphMetricSpec:
    name: str
    family: GraphMetricFamily
    value_type: Literal["int", "float", "bool"]
    description: str
    window: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _metric(
    name: str,
    family: GraphMetricFamily,
    value_type: Literal["int", "float", "bool"],
    description: str,
    window: str | None = None,
) -> GraphMetricSpec:
    return GraphMetricSpec(name, family, value_type, description, window)


GRAPH_METRICS: tuple[GraphMetricSpec, ...] = (
    _metric(
        "device_customer_degree",
        GraphMetricFamily.LOCAL_ENTITY,
        "int",
        "Historical customers adjacent to current device.",
    ),
    _metric(
        "device_instrument_degree",
        GraphMetricFamily.LOCAL_ENTITY,
        "int",
        "Historical instruments adjacent to current device.",
    ),
    _metric(
        "ip_customer_degree",
        GraphMetricFamily.LOCAL_ENTITY,
        "int",
        "Historical customers adjacent to current IP.",
    ),
    _metric(
        "ip_device_degree",
        GraphMetricFamily.LOCAL_ENTITY,
        "int",
        "Historical devices two hops from current IP through customers.",
    ),
    _metric(
        "address_customer_degree",
        GraphMetricFamily.LOCAL_ENTITY,
        "int",
        "Historical customers adjacent to current address.",
    ),
    _metric(
        "instrument_device_degree",
        GraphMetricFamily.LOCAL_ENTITY,
        "int",
        "Historical devices adjacent to current instrument.",
    ),
    _metric(
        "instrument_customer_degree",
        GraphMetricFamily.LOCAL_ENTITY,
        "int",
        "Historical customers adjacent to current instrument.",
    ),
    _metric(
        "component_node_count",
        GraphMetricFamily.COMPONENT,
        "int",
        "Nodes in historical components touched by current entities.",
    ),
    _metric(
        "component_edge_count",
        GraphMetricFamily.COMPONENT,
        "int",
        "Edges in touched historical components.",
    ),
    _metric(
        "component_customer_count",
        GraphMetricFamily.COMPONENT,
        "int",
        "Customer nodes in touched components.",
    ),
    _metric(
        "component_device_count",
        GraphMetricFamily.COMPONENT,
        "int",
        "Device nodes in touched components.",
    ),
    _metric(
        "component_instrument_count",
        GraphMetricFamily.COMPONENT,
        "int",
        "Instrument nodes in touched components.",
    ),
    _metric(
        "component_ip_count", GraphMetricFamily.COMPONENT, "int", "IP nodes in touched components."
    ),
    _metric(
        "component_address_count",
        GraphMetricFamily.COMPONENT,
        "int",
        "Address nodes in touched components.",
    ),
    _metric(
        "component_multipartite_density",
        GraphMetricFamily.COMPONENT,
        "float",
        "Observed edges divided by capacity across allowed type pairs.",
    ),
    _metric(
        "new_customer_device_edge",
        GraphMetricFamily.NOVELTY,
        "bool",
        "Current customer-device relation is historically unseen.",
    ),
    _metric(
        "new_customer_instrument_edge",
        GraphMetricFamily.NOVELTY,
        "bool",
        "Current customer-instrument relation is historically unseen.",
    ),
    _metric(
        "new_customer_ip_edge",
        GraphMetricFamily.NOVELTY,
        "bool",
        "Current customer-IP relation is historically unseen.",
    ),
    _metric(
        "new_customer_address_edge",
        GraphMetricFamily.NOVELTY,
        "bool",
        "Current customer-address relation is historically unseen.",
    ),
    _metric(
        "new_instrument_device_edge",
        GraphMetricFamily.NOVELTY,
        "bool",
        "Current instrument-device relation is historically unseen.",
    ),
    _metric(
        "preexisting_component_count",
        GraphMetricFamily.NOVELTY,
        "int",
        "Distinct historical components touched by current entities.",
    ),
    _metric(
        "components_bridged_by_transaction",
        GraphMetricFamily.NOVELTY,
        "int",
        "Historical components the current relations would bridge.",
    ),
    _metric(
        "customer_two_hop_customer_count_via_device_or_ip",
        GraphMetricFamily.CONNECTIVITY,
        "int",
        "Other customers reachable in two hops through current device or IP.",
    ),
    _metric(
        "component_new_edges_10m",
        GraphMetricFamily.TEMPORAL_STRUCTURE,
        "int",
        "Touched-component edges first observed recently.",
        "10m",
    ),
    _metric(
        "device_new_identities_10m",
        GraphMetricFamily.TEMPORAL_STRUCTURE,
        "int",
        "Customer or instrument identities newly linked to current device.",
        "10m",
    ),
)

GRAPH_METRIC_NAMES = tuple(metric.name for metric in GRAPH_METRICS)
GRAPH_METRIC_BY_NAME = {metric.name: metric for metric in GRAPH_METRICS}

SIGNAL_DEFINITIONS = (
    {
        "code": "DEVICE_MULTI_CUSTOMER_CONCENTRATION",
        "description": "At least three customers historically share the current device.",
    },
    {
        "code": "DEVICE_MULTI_INSTRUMENT_CONCENTRATION",
        "description": "At least four instruments historically share the current device.",
    },
    {
        "code": "RAPID_RELATIONSHIP_EXPANSION",
        "description": "The local component formed many relationships within ten minutes.",
    },
    {
        "code": "MULTI_COMPONENT_BRIDGE",
        "description": "The current transaction would join separate historical components.",
    },
    {
        "code": "DENSE_MULTI_ENTITY_STRUCTURE",
        "description": (
            "Multiple customers and instruments form corroborating allowed relationships."
        ),
    },
)

if len(GRAPH_METRIC_NAMES) != len(set(GRAPH_METRIC_NAMES)):
    raise RuntimeError("graph-v1 contains duplicate metric names")
