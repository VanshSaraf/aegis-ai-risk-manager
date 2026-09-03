from collections import Counter

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.enums import EntityIntelligenceType, PolicyAction, RiskSeverity
from apps.api.app.models import (
    Address,
    Customer,
    Device,
    EntityEdge,
    GraphAssessmentSnapshot,
    IPAddress,
    Merchant,
    PaymentInstrument,
    PolicyDecision,
    RiskPrediction,
    Transaction,
)
from apps.api.app.schemas.api import (
    EntityIntelligenceResponse,
    EntityNetwork,
    EntityNetworkEdge,
    EntityNetworkNode,
    EntityNetworkSummary,
    EntityObservedTransaction,
    EntityProfile,
    EntityRecentActionCounts,
    EntityRiskContext,
    EntityStructuralContext,
)
from packages.investigator.evidence import GRAPH_SIGNAL_TEXT

MODEL_VERSION = "risk-lgbm-v2"
POLICY_VERSION = "risk-policy-v2"
GRAPH_VERSION = "graph-v1"
MAX_ENTITY_NODES = 40
MAX_ENTITY_EDGES = 60
MAX_RECENT_TRANSACTIONS = 12

ENTITY_MODELS = {
    EntityIntelligenceType.CUSTOMER: Customer,
    EntityIntelligenceType.DEVICE: Device,
    EntityIntelligenceType.PAYMENT_INSTRUMENT: PaymentInstrument,
    EntityIntelligenceType.IP_ADDRESS: IPAddress,
    EntityIntelligenceType.ADDRESS: Address,
}
TRANSACTION_COLUMNS = {
    EntityIntelligenceType.CUSTOMER: Transaction.customer_id,
    EntityIntelligenceType.DEVICE: Transaction.device_id,
    EntityIntelligenceType.PAYMENT_INSTRUMENT: Transaction.payment_instrument_id,
    EntityIntelligenceType.IP_ADDRESS: Transaction.ip_address_id,
    EntityIntelligenceType.ADDRESS: Transaction.address_id,
}
ENTITY_NAMES = {
    EntityIntelligenceType.CUSTOMER: "Customer",
    EntityIntelligenceType.DEVICE: "Device",
    EntityIntelligenceType.PAYMENT_INSTRUMENT: "Instrument",
    EntityIntelligenceType.IP_ADDRESS: "IP address",
    EntityIntelligenceType.ADDRESS: "Address",
}


def _node_label(entity_type: EntityIntelligenceType, public_id: str) -> str:
    return f"{ENTITY_NAMES[entity_type]} {public_id[-6:]}"


async def entity_intelligence(
    session: AsyncSession,
    entity_type: EntityIntelligenceType,
    public_id: str,
) -> EntityIntelligenceResponse:
    model = ENTITY_MODELS[entity_type]
    entity = await session.scalar(select(model).where(model.public_id == public_id))
    if entity is None:
        raise LookupError("entity not found")

    persisted_type = entity_type.value
    incident_edges = list(
        (
            await session.scalars(
                select(EntityEdge)
                .where(
                    or_(
                        (EntityEdge.source_type == persisted_type)
                        & (EntityEdge.source_public_id == public_id),
                        (EntityEdge.target_type == persisted_type)
                        & (EntityEdge.target_public_id == public_id),
                    )
                )
                .order_by(
                    EntityEdge.last_seen_at.desc(),
                    EntityEdge.source_public_id,
                    EntityEdge.target_public_id,
                )
                .limit(MAX_ENTITY_EDGES + 1)
            )
        ).all()
    )

    node_specs: dict[str, EntityIntelligenceType] = {public_id: entity_type}
    selected_edges: list[EntityEdge] = []
    truncated = len(incident_edges) > MAX_ENTITY_EDGES
    for edge in incident_edges[:MAX_ENTITY_EDGES]:
        outgoing = edge.source_type == persisted_type and edge.source_public_id == public_id
        neighbor_id = edge.target_public_id if outgoing else edge.source_public_id
        neighbor_type_value = edge.target_type if outgoing else edge.source_type
        try:
            neighbor_type = EntityIntelligenceType(neighbor_type_value)
        except ValueError:
            continue
        if neighbor_id not in node_specs and len(node_specs) == MAX_ENTITY_NODES:
            truncated = True
            continue
        node_specs.setdefault(neighbor_id, neighbor_type)
        selected_edges.append(edge)

    connection_counts: Counter[str] = Counter()
    network_edges: list[EntityNetworkEdge] = []
    for index, edge in enumerate(selected_edges):
        connection_counts[edge.source_public_id] += 1
        connection_counts[edge.target_public_id] += 1
        network_edges.append(
            EntityNetworkEdge(
                id=f"entity-edge-{index}",
                source=edge.source_public_id,
                target=edge.target_public_id,
                type=edge.relation_type,
                first_seen_at=edge.first_seen_at,
                last_seen_at=edge.last_seen_at,
                observation_count=edge.observation_count,
            )
        )

    network_nodes = [
        EntityNetworkNode(
            id=node_id,
            type=node_type,
            label=_node_label(node_type, node_id),
            is_center=node_id == public_id,
            connection_count=connection_counts[node_id],
        )
        for node_id, node_type in node_specs.items()
    ]
    visible_type_counts = Counter(node.type for node in network_nodes)

    transaction_column = TRANSACTION_COLUMNS[entity_type]
    transaction_count, first_observed_at, last_observed_at = (
        await session.execute(
            select(
                func.count(Transaction.id),
                func.min(Transaction.event_time),
                func.max(Transaction.event_time),
            ).where(transaction_column == entity.id)
        )
    ).one()

    rows = list(
        (
            await session.execute(
                select(
                    Transaction,
                    Customer,
                    Merchant,
                    PaymentInstrument,
                    Device,
                    IPAddress,
                    Address,
                    RiskPrediction,
                    PolicyDecision,
                    GraphAssessmentSnapshot,
                )
                .join(Customer, Transaction.customer_id == Customer.id)
                .join(Merchant, Transaction.merchant_id == Merchant.id)
                .join(PaymentInstrument, Transaction.payment_instrument_id == PaymentInstrument.id)
                .join(Device, Transaction.device_id == Device.id)
                .join(IPAddress, Transaction.ip_address_id == IPAddress.id)
                .join(Address, Transaction.address_id == Address.id)
                .outerjoin(
                    RiskPrediction,
                    (RiskPrediction.transaction_id == Transaction.id)
                    & (RiskPrediction.model_version == MODEL_VERSION),
                )
                .outerjoin(
                    PolicyDecision,
                    (PolicyDecision.transaction_id == Transaction.id)
                    & (PolicyDecision.policy_version == POLICY_VERSION),
                )
                .outerjoin(
                    GraphAssessmentSnapshot,
                    (GraphAssessmentSnapshot.transaction_id == Transaction.id)
                    & (GraphAssessmentSnapshot.graph_version == GRAPH_VERSION),
                )
                .where(transaction_column == entity.id)
                .order_by(Transaction.event_time.desc(), Transaction.public_id.desc())
                .limit(MAX_RECENT_TRANSACTIONS)
            )
        ).all()
    )

    recent_transactions: list[EntityObservedTransaction] = []
    action_counts: Counter[PolicyAction] = Counter()
    structural_codes: dict[str, str] = {}
    scores: list[float] = []
    for (
        transaction,
        customer,
        merchant,
        instrument,
        device,
        ip_address,
        address,
        prediction,
        decision,
        graph,
    ) in rows:
        reason = decision.decision_reason if decision is not None else {}
        severity = RiskSeverity(str(reason["severity"])) if reason.get("severity") else None
        if prediction is not None:
            scores.append(prediction.ml_score)
        if decision is not None:
            action_counts[PolicyAction(str(decision.action))] += 1
        graph_signals = (
            [str(item["code"]) for item in graph.signals if item.get("code")]
            if graph is not None
            else []
        )
        for code in graph_signals:
            if code in GRAPH_SIGNAL_TEXT:
                structural_codes.setdefault(code, GRAPH_SIGNAL_TEXT[code])
        recent_transactions.append(
            EntityObservedTransaction(
                transaction_id=transaction.public_id,
                event_time=transaction.event_time,
                amount_paise=transaction.amount_paise,
                currency=transaction.currency,
                payment_method=transaction.payment_method,
                customer_id=customer.public_id,
                merchant_id=merchant.public_id,
                instrument_id=instrument.public_id,
                device_id=device.public_id,
                ip_id=ip_address.public_id,
                address_id=address.public_id,
                assessed=prediction is not None and decision is not None and graph is not None,
                model_score=prediction.ml_score if prediction is not None else None,
                model_version=prediction.model_version if prediction is not None else None,
                action=decision.action if decision is not None else None,
                severity=severity,
                requires_human_review=(
                    decision.requires_human_review if decision is not None else None
                ),
                graph_signals=graph_signals,
                cluster_id=(
                    str(reason["detected_cluster_id"])
                    if reason.get("detected_cluster_id")
                    else None
                ),
                status=transaction.status,
            )
        )

    return EntityIntelligenceResponse(
        view_semantics="CURRENT_OBSERVED_HISTORY",
        entity=EntityProfile(
            entity_type=entity_type,
            public_id=public_id,
            first_observed_at=first_observed_at,
            last_observed_at=last_observed_at,
            transaction_count=transaction_count,
        ),
        summary=EntityNetworkSummary(
            visible_customers=visible_type_counts[EntityIntelligenceType.CUSTOMER],
            visible_devices=visible_type_counts[EntityIntelligenceType.DEVICE],
            visible_instruments=visible_type_counts[EntityIntelligenceType.PAYMENT_INSTRUMENT],
            visible_ips=visible_type_counts[EntityIntelligenceType.IP_ADDRESS],
            visible_addresses=visible_type_counts[EntityIntelligenceType.ADDRESS],
            visible_relationships=len(network_edges),
        ),
        network=EntityNetwork(
            nodes=network_nodes,
            edges=network_edges,
            max_nodes=MAX_ENTITY_NODES,
            max_edges=MAX_ENTITY_EDGES,
            truncated=truncated,
        ),
        recent_transactions=recent_transactions,
        structural_context=[
            EntityStructuralContext(code=code, label=label)
            for code, label in structural_codes.items()
        ],
        risk_context=EntityRiskContext(
            highest_recent_transaction_score=max(scores) if scores else None,
            recent_action_counts=EntityRecentActionCounts(
                allow=action_counts[PolicyAction.ALLOW],
                verify=action_counts[PolicyAction.VERIFY],
                hold=action_counts[PolicyAction.HOLD],
                escalate=action_counts[PolicyAction.ESCALATE],
                recommend_block=action_counts[PolicyAction.RECOMMEND_BLOCK],
            ),
        ),
    )
