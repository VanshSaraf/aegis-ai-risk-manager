import math
from datetime import datetime

from apps.api.app.schemas.contracts import FeatureVector
from packages.risk_engine.features.registry import FEATURE_BY_NAME, FEATURE_NAMES, FEATURE_VERSION

FORBIDDEN_FEATURE_FRAGMENTS = (
    "ground_truth",
    "scenario",
    "ring_id",
    "persona",
    "scenario_run",
    "dataset_version",
    "current_status",
    "current_failure",
)


def validate_feature_vector(vector: FeatureVector, current_event_time: datetime) -> None:
    if vector.feature_version != FEATURE_VERSION:
        raise ValueError(f"unsupported feature version: {vector.feature_version}")
    actual_names = tuple(vector.values)
    if actual_names != FEATURE_NAMES:
        missing = sorted(set(FEATURE_NAMES) - set(actual_names))
        unexpected = sorted(set(actual_names) - set(FEATURE_NAMES))
        raise ValueError(f"feature schema mismatch; missing={missing}, unexpected={unexpected}")
    for name, value in vector.values.items():
        if any(fragment in name.lower() for fragment in FORBIDDEN_FEATURE_FRAGMENTS):
            raise ValueError(f"forbidden feature name: {name}")
        expected = FEATURE_BY_NAME[name].value_type
        if expected == "bool" and type(value) is not bool:
            raise ValueError(f"{name} must be bool")
        if expected == "int" and (type(value) is not int):
            raise ValueError(f"{name} must be int")
        if expected == "float" and (type(value) not in (float, int)):
            raise ValueError(f"{name} must be numeric")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
    if (
        vector.max_source_event_time is not None
        and vector.max_source_event_time >= current_event_time
    ):
        raise ValueError("max_source_event_time must be strictly earlier than current event")
