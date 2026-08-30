from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.enums import PolicyAction, RiskSeverity
from apps.api.app.models import (
    GraphAssessmentSnapshot,
    PolicyDecision,
    RiskPrediction,
    Transaction,
    TransactionFeature,
)
from packages.investigator.domain import (
    ClusterContext,
    EntityReferences,
    EvidenceBundle,
    EvidenceCategory,
    EvidenceItem,
    GraphSummary,
    ModelSummary,
    PolicySummary,
    RelatedEntity,
    TimelineEntry,
    TransactionSummary,
    VersionMetadata,
)
from packages.policy_engine.config import POLICY_VERSION
from packages.risk_engine.features.postgres import transaction_history_query

MAX_EVIDENCE_ITEMS = 8
MAX_TIMELINE_ITEMS = 8

GRAPH_SIGNAL_TEXT = {
    "DEVICE_MULTI_CUSTOMER_CONCENTRATION": (
        "Multiple customer identities are concentrated on the same device."
    ),
    "DEVICE_MULTI_INSTRUMENT_CONCENTRATION": (
        "Multiple payment instruments are concentrated on the same device."
    ),
    "RAPID_RELATIONSHIP_EXPANSION": "The local identity graph expanded unusually quickly.",
    "MULTI_COMPONENT_BRIDGE": (
        "This transaction connects identity structures that were historically separate."
    ),
    "DENSE_MULTI_ENTITY_STRUCTURE": (
        "The surrounding component contains dense cross-entity relationships."
    ),
}

SELECTED_GRAPH_METRICS = (
    "device_customer_degree",
    "device_instrument_degree",
    "ip_customer_degree",
    "component_customer_count",
    "component_instrument_count",
    "component_device_count",
    "component_ip_count",
    "component_edge_count",
    "components_bridged_by_transaction",
    "component_new_edges_10m",
    "device_new_identities_10m",
)


@dataclass(frozen=True, slots=True)
class FeatureEvidenceRule:
    feature: str
    code: str
    category: EvidenceCategory
    title: str
    threshold: float
    context: str
    importance: int
    boolean: bool = False


FEATURE_EVIDENCE_RULES = (
    FeatureEvidenceRule(
        "device_txn_count_10m",
        "DEVICE_ACTIVITY_10M",
        EvidenceCategory.VELOCITY,
        "Elevated recent device activity",
        3,
        "{value} prior transactions used this device in the previous 10 minutes.",
        76,
    ),
    FeatureEvidenceRule(
        "ip_unique_customers_1h",
        "NETWORK_CUSTOMER_DIVERSITY_1H",
        EvidenceCategory.VELOCITY,
        "Multiple customers used the current network",
        3,
        "{value} historical customers used this network in the previous hour.",
        74,
    ),
    FeatureEvidenceRule(
        "customer_failed_txn_count_1h",
        "CUSTOMER_FAILURES_1H",
        EvidenceCategory.BEHAVIOR,
        "Recent failed customer attempts",
        1,
        "The customer had {value} failed historical transactions in the previous hour.",
        72,
    ),
    FeatureEvidenceRule(
        "is_new_device_for_customer",
        "NEW_DEVICE_FOR_CUSTOMER",
        EvidenceCategory.BEHAVIOR,
        "Previously unseen customer-device relationship",
        1,
        "This device had not been observed previously for the customer.",
        67,
        boolean=True,
    ),
    FeatureEvidenceRule(
        "is_new_instrument_for_customer",
        "NEW_INSTRUMENT_FOR_CUSTOMER",
        EvidenceCategory.BEHAVIOR,
        "Previously unseen customer-instrument relationship",
        1,
        "This payment instrument had not been observed previously for the customer.",
        66,
        boolean=True,
    ),
    FeatureEvidenceRule(
        "historical_customers_on_current_device",
        "DEVICE_SHARED_ACROSS_CUSTOMERS",
        EvidenceCategory.GRAPH,
        "Device shared across historical customers",
        2,
        "The device was historically connected to {value} customers.",
        80,
    ),
    FeatureEvidenceRule(
        "historical_instruments_on_current_device",
        "DEVICE_SHARED_ACROSS_INSTRUMENTS",
        EvidenceCategory.GRAPH,
        "Device shared across payment instruments",
        3,
        "The device was historically connected to {value} payment instruments.",
        79,
    ),
)

REGISTERED_EVIDENCE_CODES = {
    "MODEL_SCORE_POLICY_BAND",
    "POLICY_REASON_CODES",
    "ACTIVE_STRUCTURAL_CLUSTER",
    *(f"GRAPH_SIGNAL_{code}" for code in GRAPH_SIGNAL_TEXT),
    *(rule.code for rule in FEATURE_EVIDENCE_RULES),
}


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _rank(items: list[EvidenceItem]) -> tuple[EvidenceItem, ...]:
    unique = {item.code: item for item in items}
    return tuple(
        sorted(unique.values(), key=lambda item: (-item.importance, item.code))[:MAX_EVIDENCE_ITEMS]
    )


class EvidenceBuilder:
    def __init__(self, *, policy_version: str = POLICY_VERSION) -> None:
        self.policy_version = policy_version

    async def build(self, session: AsyncSession, transaction_id: str) -> EvidenceBundle:
        row = (
            await session.execute(
                transaction_history_query().where(Transaction.public_id == transaction_id)
            )
        ).one_or_none()
        if row is None:
            raise LookupError("transaction not found")
        transaction, customer, merchant, instrument, device, ip, address = row
        prediction = await session.scalar(
            select(RiskPrediction).where(
                RiskPrediction.transaction_id == transaction.id,
                RiskPrediction.model_version == "risk-lgbm-v2",
            )
        )
        decision = await session.scalar(
            select(PolicyDecision).where(
                PolicyDecision.transaction_id == transaction.id,
                PolicyDecision.policy_version == self.policy_version,
            )
        )
        feature = await session.scalar(
            select(TransactionFeature).where(
                TransactionFeature.transaction_id == transaction.id,
                TransactionFeature.feature_version == "features-v1",
            )
        )
        graph = await session.scalar(
            select(GraphAssessmentSnapshot).where(
                GraphAssessmentSnapshot.transaction_id == transaction.id,
                GraphAssessmentSnapshot.graph_version == "graph-v1",
            )
        )
        if prediction is None or decision is None or feature is None or graph is None:
            raise LookupError("transaction has no complete frozen assessment")

        reason = decision.decision_reason
        reason_codes = tuple(str(code) for code in reason.get("reason_codes", ()))
        severity = RiskSeverity(str(reason["severity"]))
        action = PolicyAction(_enum_value(decision.action))
        signal_codes = tuple(
            sorted(
                {
                    str(item["code"])
                    for item in graph.signals
                    if str(item.get("code")) in GRAPH_SIGNAL_TEXT
                }
            )
        )
        cluster_id = reason.get("detected_cluster_id")
        metrics = {
            name: graph.metrics[name] for name in SELECTED_GRAPH_METRICS if name in graph.metrics
        }
        evidence = self._evidence_items(
            prediction.ml_score,
            action,
            reason_codes,
            signal_codes,
            feature.features,
            cluster_id,
        )
        references = EntityReferences(
            customer=customer.public_id,
            merchant=merchant.public_id,
            instrument=instrument.public_id,
            device=device.public_id,
            ip=ip.public_id,
            address=address.public_id,
        )
        timeline = await self._timeline(session, transaction, row)
        cluster = (
            ClusterContext(
                cluster_id=str(cluster_id),
                context=(
                    "The frozen policy decision references an Aegis structural investigation "
                    "cluster. Mutable later membership counts are intentionally not shown."
                ),
            )
            if cluster_id
            else None
        )
        return EvidenceBundle(
            transaction=TransactionSummary(
                transaction_id=transaction.public_id,
                event_time=transaction.event_time,
                amount_paise=transaction.amount_paise,
                formatted_amount=f"₹{transaction.amount_paise / 100:,.2f}",
                currency=transaction.currency,
                payment_method=transaction.payment_method,
                entities=references,
            ),
            model=ModelSummary(version=prediction.model_version, score=prediction.ml_score),
            policy=PolicySummary(
                version=decision.policy_version,
                action=action,
                severity=severity,
                requires_human_review=decision.requires_human_review,
                reason_codes=reason_codes,
            ),
            graph=GraphSummary(
                version=prediction.graph_version,
                structural_score=prediction.graph_score,
                signals=signal_codes,
                selected_metrics=metrics,
            ),
            evidence_items=evidence,
            related_entities=self._related_entities(references, metrics),
            cluster=cluster,
            timeline=timeline,
            limitations=(
                "The model score is an uncalibrated ranking score, not a fraud probability.",
                "Aegis evidence indicates risk patterns; it does not confirm fraud.",
                "Only facts available strictly before the transaction and immutable assessment "
                "snapshots are used.",
                "Cluster membership counts are omitted because they are not point-in-time "
                "snapshots.",
            ),
            versions=VersionMetadata(
                feature_version=feature.feature_version,
                graph_version=graph.graph_version,
                model_version=prediction.model_version,
                policy_version=decision.policy_version,
            ),
        )

    def _evidence_items(
        self,
        model_score: float,
        action: PolicyAction,
        reason_codes: tuple[str, ...],
        signal_codes: tuple[str, ...],
        features: dict[str, Any],
        cluster_id: str | None,
    ) -> tuple[EvidenceItem, ...]:
        items = [
            EvidenceItem(
                code="MODEL_SCORE_POLICY_BAND",
                category=EvidenceCategory.POLICY,
                title="Model score entered the policy action band",
                observed_value=model_score,
                context=f"The frozen model score mapped to the {action.value} policy band.",
                importance=100,
                source="risk-lgbm-v2 score and risk-policy-v2 thresholds",
                source_version=self.policy_version,
            ),
            EvidenceItem(
                code="POLICY_REASON_CODES",
                category=EvidenceCategory.POLICY,
                title="Deterministic policy reasons",
                observed_value=", ".join(reason_codes),
                context="These reason codes were persisted with the immutable policy decision.",
                importance=96,
                source="policy decision",
                source_version=self.policy_version,
            ),
        ]
        for code in signal_codes:
            items.append(
                EvidenceItem(
                    code=f"GRAPH_SIGNAL_{code}",
                    category=EvidenceCategory.GRAPH,
                    title=code.replace("_", " ").title(),
                    observed_value=code,
                    context=GRAPH_SIGNAL_TEXT[code],
                    importance=90,
                    source="graph signal",
                    source_version="graph-v1",
                )
            )
        if cluster_id:
            items.append(
                EvidenceItem(
                    code="ACTIVE_STRUCTURAL_CLUSTER",
                    category=EvidenceCategory.CLUSTER,
                    title="Structural investigation cluster referenced",
                    observed_value=cluster_id,
                    context="The frozen policy decision references this Aegis cluster.",
                    importance=88,
                    source="policy decision",
                    source_version=self.policy_version,
                )
            )
        for rule in FEATURE_EVIDENCE_RULES:
            value = features.get(rule.feature, False if rule.boolean else 0)
            matched = bool(value) if rule.boolean else float(value) >= rule.threshold
            if matched:
                items.append(
                    EvidenceItem(
                        code=rule.code,
                        category=rule.category,
                        title=rule.title,
                        observed_value=value,
                        context=rule.context.format(value=value),
                        importance=rule.importance,
                        source=rule.feature,
                        source_version="features-v1",
                    )
                )
        if any(item.code not in REGISTERED_EVIDENCE_CODES for item in items):
            raise RuntimeError("unregistered evidence code")
        return _rank(items)

    @staticmethod
    def _related_entities(
        references: EntityReferences, metrics: dict[str, Any]
    ) -> tuple[RelatedEntity, ...]:
        return (
            RelatedEntity(
                entity_type="DEVICE",
                public_id=references.device,
                connections={
                    "historical_customers": int(metrics.get("device_customer_degree", 0)),
                    "historical_instruments": int(metrics.get("device_instrument_degree", 0)),
                },
                context="Current transaction device and its point-in-time graph degrees.",
            ),
            RelatedEntity(
                entity_type="IP",
                public_id=references.ip,
                connections={"historical_customers": int(metrics.get("ip_customer_degree", 0))},
                context="Current transaction network and its point-in-time graph degree.",
            ),
            RelatedEntity(
                entity_type="CUSTOMER",
                public_id=references.customer,
                context="Current transaction customer reference.",
            ),
            RelatedEntity(
                entity_type="PAYMENT_INSTRUMENT",
                public_id=references.instrument,
                context="Current tokenized payment-instrument reference.",
            ),
        )

    @staticmethod
    async def _timeline(
        session: AsyncSession, current: Transaction, current_row: Any
    ) -> tuple[TimelineEntry, ...]:
        _, customer, _, instrument, device, ip, address = current_row
        statement = (
            transaction_history_query()
            .where(
                Transaction.event_time < current.event_time,
                or_(
                    Transaction.customer_id == current.customer_id,
                    Transaction.device_id == current.device_id,
                    Transaction.payment_instrument_id == current.payment_instrument_id,
                    Transaction.ip_address_id == current.ip_address_id,
                    Transaction.address_id == current.address_id,
                ),
            )
            .order_by(Transaction.event_time.desc(), Transaction.public_id.desc())
            .limit(MAX_TIMELINE_ITEMS)
        )
        rows = list((await session.execute(statement)).all())
        entries = []
        for (
            transaction,
            row_customer,
            _,
            row_instrument,
            row_device,
            row_ip,
            row_address,
        ) in reversed(rows):
            shared = []
            if row_customer.public_id == customer.public_id:
                shared.append("customer")
            if row_device.public_id == device.public_id:
                shared.append("device")
            if row_instrument.public_id == instrument.public_id:
                shared.append("instrument")
            if row_ip.public_id == ip.public_id:
                shared.append("network")
            if row_address.public_id == address.public_id:
                shared.append("address")
            entries.append(
                TimelineEntry(
                    transaction_id=transaction.public_id,
                    event_time=transaction.event_time,
                    summary=f"Prior related transaction shared {', '.join(shared)}.",
                    entity_references={
                        "customer": row_customer.public_id,
                        "device": row_device.public_id,
                        "instrument": row_instrument.public_id,
                        "ip": row_ip.public_id,
                    },
                )
            )
        return tuple(entries)
