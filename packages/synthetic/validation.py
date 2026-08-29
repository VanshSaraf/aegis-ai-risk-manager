from collections import Counter, defaultdict
from datetime import timedelta
from enum import StrEnum
from math import ceil

from pydantic import BaseModel, ConfigDict

from apps.api.app.core.enums import GroundTruthLabel, ScenarioType, TransactionStatus
from packages.synthetic.config import GenerationConfig
from packages.synthetic.domain import GeneratedEvent, SyntheticDataset
from packages.synthetic.manifest import GenerationManifest

GROUND_TRUTH_FIELDS = {
    "ground_truth_label",
    "ground_truth_scenario",
    "ground_truth_ring_id",
    "persona",
}


class ValidationSeverity(StrEnum):
    WARNING = "WARNING"
    ERROR = "ERROR"


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: ValidationSeverity
    message: str


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issues: list[ValidationIssue]

    @property
    def status(self) -> str:
        if any(issue.severity == ValidationSeverity.ERROR for issue in self.issues):
            return "FAIL"
        if self.issues:
            return "WARN"
        return "PASS"

    @property
    def passed(self) -> bool:
        return self.status != "FAIL"


def _issue(
    issues: list[ValidationIssue],
    code: str,
    message: str,
    severity: ValidationSeverity = ValidationSeverity.ERROR,
) -> None:
    issues.append(ValidationIssue(code=code, message=message, severity=severity))


def _shared_ip_exists(events: list[GeneratedEvent]) -> bool:
    customers_by_ip: dict[str, set[str]] = defaultdict(set)
    for event in events:
        customers_by_ip[event.facts.ip_hash].add(event.facts.customer_ref)
    return any(len(customers) > 1 for customers in customers_by_ip.values())


def _multi_instrument_device_exists(events: list[GeneratedEvent]) -> bool:
    instruments_by_device: dict[str, set[str]] = defaultdict(set)
    for event in events:
        instruments_by_device[event.facts.device_fingerprint].add(
            event.facts.instrument_fingerprint
        )
    return any(len(instruments) > 1 for instruments in instruments_by_device.values())


def _validate_class_overlap(
    issues: list[ValidationIssue],
    events: list[GeneratedEvent],
    config: GenerationConfig,
    label: GroundTruthLabel,
) -> None:
    class_events = [event for event in events if event.truth.label == label]
    checks = {
        "payment failure": any(
            event.facts.status == TransactionStatus.FAILED for event in class_events
        ),
        "high-value payment": any(
            event.facts.amount_paise >= config.behavior.high_value_paise for event in class_events
        ),
        "low-value payment": any(
            event.facts.amount_paise <= config.behavior.low_value_paise for event in class_events
        ),
        "shared IP": _shared_ip_exists(class_events),
        "multiple instruments per device": _multi_instrument_device_exists(class_events),
        "newer account": any(
            event.facts.event_time - event.facts.account_created_at <= timedelta(days=30)
            for event in class_events
        ),
    }
    for description, present in checks.items():
        if not present:
            _issue(
                issues,
                "class_overlap_missing",
                f"{label.value} has no {description} example",
            )


def _validate_single_feature_leakage(
    issues: list[ValidationIssue], events: list[GeneratedEvent]
) -> None:
    categorical_fields = (
        "network_type",
        "merchant_category",
        "device_type",
        "os_family",
        "browser_family",
        "payment_method",
        "status",
        "home_region",
    )
    values: dict[str, dict[GroundTruthLabel, Counter[object]]] = {
        field: {label: Counter() for label in GroundTruthLabel} for field in categorical_fields
    }
    by_label: dict[GroundTruthLabel, list[int]] = defaultdict(list)
    for event in events:
        label = event.truth.label
        by_label[label].append(event.facts.amount_paise)
        for field in categorical_fields:
            values[field][label][getattr(event.facts, field)] += 1
    for field, label_counts in values.items():
        for label in GroundTruthLabel:
            other = (
                GroundTruthLabel.COORDINATED_ABUSE
                if label == GroundTruthLabel.LEGITIMATE
                else GroundTruthLabel.LEGITIMATE
            )
            for value, count in label_counts[label].items():
                if count >= 3 and label_counts[other][value] == 0:
                    _issue(
                        issues,
                        "exclusive_categorical_value",
                        f"{field}={value} appears only in {label.value} ({count} events)",
                        ValidationSeverity.WARNING,
                    )
    legitimate = by_label[GroundTruthLabel.LEGITIMATE]
    abuse = by_label[GroundTruthLabel.COORDINATED_ABUSE]
    if legitimate and abuse:
        separated = max(legitimate) < min(abuse) or max(abuse) < min(legitimate)
        if separated:
            _issue(
                issues,
                "amount_perfect_separation",
                "amount ranges are perfectly separated by target label",
            )


def _validate_topology(issues: list[ValidationIssue], events: list[GeneratedEvent]) -> None:
    normal = [event for event in events if event.truth.label == GroundTruthLabel.LEGITIMATE]
    if normal:
        household_addresses: dict[str, set[str]] = defaultdict(set)
        network_customers: dict[str, set[str]] = defaultdict(set)
        for event in normal:
            household_addresses[event.facts.address_fingerprint].add(event.facts.customer_ref)
            network_customers[event.facts.ip_hash].add(event.facts.customer_ref)
        if not any(len(customers) > 1 for customers in household_addresses.values()):
            _issue(issues, "household_topology", "no legitimate shared household address")
        if not any(len(customers) > 1 for customers in network_customers.values()):
            _issue(issues, "shared_network_topology", "no legitimate shared network")

    for scenario in (
        ScenarioType.CARD_TESTING,
        ScenarioType.ACCOUNT_FARM,
        ScenarioType.IDENTITY_ROTATION,
        ScenarioType.COLLUSIVE_RING,
    ):
        scenario_events = [event for event in events if event.truth.scenario_type == scenario]
        if not scenario_events:
            continue
        ring_count = len({event.truth.ring_id for event in scenario_events})
        minimum_ring_count = max(1, ceil(len(scenario_events) / 50))
        if ring_count < minimum_ring_count:
            _issue(
                issues,
                "insufficient_ring_diversity",
                f"{scenario.value} has {ring_count} abuse rings; "
                f"at least {minimum_ring_count} are required for "
                f"{len(scenario_events)} events",
            )
        customers = {event.facts.customer_ref for event in scenario_events}
        infrastructure = {
            (event.facts.device_fingerprint, event.facts.ip_hash) for event in scenario_events
        }
        if len(scenario_events) >= 10 and len(infrastructure) >= len(customers):
            _issue(
                issues,
                "abuse_infrastructure_not_concentrated",
                f"{scenario.value} does not reuse infrastructure across identities",
            )


def validate_dataset(
    dataset: SyntheticDataset,
    manifest: GenerationManifest,
    config: GenerationConfig,
    scenario: ScenarioType | None = None,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    events = list(dataset.events)
    if len(events) != config.dataset.transaction_count:
        _issue(issues, "transaction_count", "generated transaction count is incorrect")
    if manifest.transaction_count != len(events):
        _issue(issues, "manifest_count", "manifest transaction count is inconsistent")
    timestamps = [event.facts.event_time for event in events]
    if any(timestamp.tzinfo is None or timestamp.utcoffset() is None for timestamp in timestamps):
        _issue(issues, "timestamp_timezone", "all timestamps must be timezone-aware")
    if timestamps != sorted(timestamps):
        _issue(issues, "timestamp_order", "events are not chronologically ordered")
    simulation_end = config.dataset.start_time + timedelta(days=config.dataset.simulation_days)
    if any(
        timestamp < config.dataset.start_time or timestamp > simulation_end
        for timestamp in timestamps
    ):
        _issue(issues, "timestamp_range", "events fall outside the simulation window")

    for event in events:
        facts = event.facts.model_dump()
        required_refs = (
            event.facts.customer_ref,
            event.facts.instrument_fingerprint,
            event.facts.device_fingerprint,
            event.facts.ip_hash,
            event.facts.address_fingerprint,
            event.facts.merchant_ref,
        )
        if not all(required_refs):
            _issue(issues, "missing_entity_reference", "an event has a missing entity reference")
        if GROUND_TRUTH_FIELDS.intersection(facts):
            _issue(issues, "ground_truth_leakage", "raw payment facts contain hidden ground truth")
        if event.truth.label == GroundTruthLabel.COORDINATED_ABUSE and not event.truth.ring_id:
            _issue(issues, "missing_ring_id", "an abuse event has no ring ID")
        if event.truth.label == GroundTruthLabel.LEGITIMATE and event.truth.ring_id:
            _issue(issues, "legitimate_ring_id", "a legitimate event has an abuse ring ID")

    truth_counts = Counter(event.truth.label for event in events)
    if manifest.legitimate_count != truth_counts[GroundTruthLabel.LEGITIMATE]:
        _issue(issues, "legitimate_count", "legitimate count is inconsistent")
    if manifest.coordinated_abuse_count != truth_counts[GroundTruthLabel.COORDINATED_ABUSE]:
        _issue(issues, "abuse_count", "coordinated-abuse count is inconsistent")

    expected_prevalence = (
        0.0
        if scenario == ScenarioType.NORMAL_TRAFFIC
        else 1.0
        if scenario is not None
        else config.abuse.prevalence
    )
    if abs(manifest.abuse_prevalence - expected_prevalence) > config.abuse.prevalence_tolerance:
        _issue(issues, "abuse_prevalence", "abuse prevalence is outside configured tolerance")

    if (
        truth_counts[GroundTruthLabel.LEGITIMATE]
        and truth_counts[GroundTruthLabel.COORDINATED_ABUSE]
    ):
        for label in GroundTruthLabel:
            _validate_class_overlap(issues, events, config, label)
        _validate_single_feature_leakage(issues, events)
    _validate_topology(issues, events)
    return ValidationReport(issues=issues)
