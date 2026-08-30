import math

from packages.graph_engine.domain import GraphAssessment, GraphTransaction
from packages.graph_engine.registry import (
    GRAPH_METRIC_BY_NAME,
    GRAPH_METRIC_NAMES,
    GRAPH_VERSION,
)

FORBIDDEN_FRAGMENTS = (
    "ground_truth",
    "scenario",
    "ring",
    "persona",
    "status",
    "failure",
    "dataset_version",
    "scenario_run",
)


def validate_graph_assessment(
    assessment: GraphAssessment,
    current: GraphTransaction,
) -> None:
    if assessment.graph_version != GRAPH_VERSION:
        raise ValueError(f"unsupported graph version: {assessment.graph_version}")
    if tuple(assessment.metrics) != GRAPH_METRIC_NAMES:
        raise ValueError("graph metric schema mismatch")
    for name, value in assessment.metrics.items():
        if any(fragment in name.lower() for fragment in FORBIDDEN_FRAGMENTS):
            raise ValueError(f"forbidden graph metric: {name}")
        expected_type = GRAPH_METRIC_BY_NAME[name].value_type
        if expected_type == "bool" and type(value) is not bool:
            raise ValueError(f"{name} must be bool")
        if expected_type == "int" and type(value) is not int:
            raise ValueError(f"{name} must be int")
        if expected_type == "float" and type(value) not in (float, int):
            raise ValueError(f"{name} must be numeric")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value < 0 or not math.isfinite(value):
                raise ValueError(f"invalid graph metric: {name}")
    if assessment.metrics["component_multipartite_density"] > 1:
        raise ValueError("component density cannot exceed one")
    if not 0 <= assessment.structural_score <= 1 or not math.isfinite(assessment.structural_score):
        raise ValueError("structural score must be finite and within [0, 1]")
    if (
        assessment.max_source_event_time is not None
        and assessment.max_source_event_time >= current.event_time
    ):
        raise ValueError("graph watermark must be strictly historical")
    node_count = assessment.metrics["component_node_count"]
    typed_nodes = sum(
        assessment.metrics[name]
        for name in (
            "component_customer_count",
            "component_device_count",
            "component_instrument_count",
            "component_ip_count",
            "component_address_count",
        )
    )
    if node_count != typed_nodes:
        raise ValueError("component node count is inconsistent")
    for signal in assessment.signals:
        if not 0 <= signal.strength <= 1 or not math.isfinite(signal.strength):
            raise ValueError(f"invalid signal strength: {signal.code}")
