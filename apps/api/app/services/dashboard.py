from collections import Counter

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.enums import ClusterStatus, PolicyAction, RiskSeverity
from apps.api.app.models import (
    AbuseCluster,
    Address,
    Customer,
    Device,
    GraphAssessmentSnapshot,
    IPAddress,
    Merchant,
    PaymentInstrument,
    PolicyDecision,
    RiskPrediction,
    Transaction,
)
from apps.api.app.schemas.api import (
    DashboardSummary,
    DashboardTransaction,
    TransactionGraphEdge,
    TransactionGraphNode,
    TransactionGraphResponse,
    TransactionGraphSignal,
)
from packages.investigator.evidence import GRAPH_SIGNAL_TEXT
from packages.risk_engine.features.postgres import transaction_history_query

MODEL_VERSION = "risk-lgbm-v2"
POLICY_VERSION = "risk-policy-v2"
GRAPH_VERSION = "graph-v1"
MAX_GRAPH_NODES = 40
MAX_GRAPH_EDGES = 60


async def dashboard_summary(session: AsyncSession) -> DashboardSummary:
    transaction_count = await session.scalar(select(func.count()).select_from(Transaction)) or 0
    action_rows = (
        await session.execute(
            select(PolicyDecision.action, func.count())
            .where(PolicyDecision.policy_version == POLICY_VERSION)
            .group_by(PolicyDecision.action)
        )
    ).all()
    action_counts = {PolicyAction(str(action)): count for action, count in action_rows}
    assessed_count = sum(action_counts.values())
    active_cluster_count = (
        await session.scalar(
            select(func.count())
            .select_from(AbuseCluster)
            .where(AbuseCluster.status.in_((ClusterStatus.OPEN, ClusterStatus.UNDER_REVIEW)))
        )
        or 0
    )
    return DashboardSummary(
        transaction_count=transaction_count,
        assessed_count=assessed_count,
        allow_count=action_counts.get(PolicyAction.ALLOW, 0),
        verify_count=action_counts.get(PolicyAction.VERIFY, 0),
        hold_count=action_counts.get(PolicyAction.HOLD, 0),
        escalate_count=action_counts.get(PolicyAction.ESCALATE, 0),
        recommend_block_count=action_counts.get(PolicyAction.RECOMMEND_BLOCK, 0),
        active_cluster_count=active_cluster_count,
    )


async def dashboard_transactions(
    session: AsyncSession,
    *,
    limit: int,
    action: PolicyAction | None,
    severity: RiskSeverity | None,
) -> list[DashboardTransaction]:
    statement = (
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
    )
    if action is not None:
        statement = statement.where(PolicyDecision.action == action)
    if severity is not None:
        statement = statement.where(RiskPrediction.severity == severity)
    rows = (
        await session.execute(
            statement.order_by(Transaction.event_time.desc(), Transaction.public_id.desc()).limit(
                limit
            )
        )
    ).all()
    items = []
    for (
        transaction,
        customer,
        merchant,
        instrument,
        device,
        ip,
        address,
        prediction,
        decision,
        graph,
    ) in rows:
        decision_reason = decision.decision_reason if decision is not None else {}
        policy_severity = (
            RiskSeverity(str(decision_reason["severity"])) if decision is not None else None
        )
        items.append(
            DashboardTransaction(
                transaction_id=transaction.public_id,
                event_time=transaction.event_time,
                amount_paise=transaction.amount_paise,
                currency=transaction.currency,
                payment_method=transaction.payment_method,
                customer_id=customer.public_id,
                merchant_id=merchant.public_id,
                instrument_id=instrument.public_id,
                device_id=device.public_id,
                ip_id=ip.public_id,
                address_id=address.public_id,
                assessed=prediction is not None and decision is not None and graph is not None,
                model_score=prediction.ml_score if prediction is not None else None,
                model_version=prediction.model_version if prediction is not None else None,
                action=decision.action if decision is not None else None,
                severity=policy_severity,
                requires_human_review=(
                    decision.requires_human_review if decision is not None else None
                ),
                graph_signals=(
                    [str(item["code"]) for item in graph.signals if item.get("code")]
                    if graph is not None
                    else []
                ),
                cluster_id=(
                    str(decision_reason["detected_cluster_id"])
                    if decision_reason.get("detected_cluster_id")
                    else None
                ),
            )
        )
    return items


def _label(entity_type: str, public_id: str) -> str:
    names = {
        "TRANSACTION": "Transaction",
        "CUSTOMER": "Customer",
        "DEVICE": "Device",
        "PAYMENT_INSTRUMENT": "Instrument",
        "IP_ADDRESS": "IP address",
        "ADDRESS": "Address",
    }
    return f"{names[entity_type]} {public_id[-6:]}"


async def transaction_graph(session: AsyncSession, transaction_id: str) -> TransactionGraphResponse:
    current_row = (
        await session.execute(
            transaction_history_query().where(Transaction.public_id == transaction_id)
        )
    ).one_or_none()
    if current_row is None:
        raise LookupError("transaction not found")
    current, customer, _merchant, instrument, device, ip, address = current_row
    graph = await session.scalar(
        select(GraphAssessmentSnapshot).where(
            GraphAssessmentSnapshot.transaction_id == current.id,
            GraphAssessmentSnapshot.graph_version == GRAPH_VERSION,
        )
    )
    decision = await session.scalar(
        select(PolicyDecision).where(
            PolicyDecision.transaction_id == current.id,
            PolicyDecision.policy_version == POLICY_VERSION,
        )
    )
    if graph is None or decision is None:
        raise LookupError("transaction has no complete frozen assessment")

    current_entities = {
        "CUSTOMER": customer.public_id,
        "DEVICE": device.public_id,
        "PAYMENT_INSTRUMENT": instrument.public_id,
        "IP_ADDRESS": ip.public_id,
        "ADDRESS": address.public_id,
    }
    prior_rows = list(
        (
            await session.execute(
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
                .limit(50)
            )
        ).all()
    )

    node_specs: dict[str, tuple[str, bool]] = {current.public_id: ("TRANSACTION", True)}
    for entity_type, public_id in current_entities.items():
        node_specs[public_id] = (entity_type, True)
    edge_specs: list[tuple[str, str, str]] = [
        (current.public_id, public_id, "INVOLVES") for public_id in current_entities.values()
    ]

    relation_specs = (
        ("CUSTOMER", "DEVICE", "USES"),
        ("CUSTOMER", "PAYMENT_INSTRUMENT", "USES"),
        ("CUSTOMER", "IP_ADDRESS", "USES"),
        ("CUSTOMER", "ADDRESS", "USES"),
        ("PAYMENT_INSTRUMENT", "DEVICE", "SEEN_ON"),
    )
    for (
        _,
        row_customer,
        _row_merchant,
        row_instrument,
        row_device,
        row_ip,
        row_address,
    ) in prior_rows:
        row_entities = {
            "CUSTOMER": row_customer.public_id,
            "DEVICE": row_device.public_id,
            "PAYMENT_INSTRUMENT": row_instrument.public_id,
            "IP_ADDRESS": row_ip.public_id,
            "ADDRESS": row_address.public_id,
        }
        candidate_ids = set(row_entities.values())
        if len(node_specs.keys() | candidate_ids) > MAX_GRAPH_NODES:
            continue
        for entity_type, public_id in row_entities.items():
            node_specs.setdefault(public_id, (entity_type, public_id in current_entities.values()))
        for source_type, target_type, relation_type in relation_specs:
            edge_specs.append((row_entities[source_type], row_entities[target_type], relation_type))

    unique_edges: dict[tuple[str, str, str], None] = {}
    for edge in edge_specs:
        unique_edges.setdefault(edge, None)
        if len(unique_edges) == MAX_GRAPH_EDGES:
            break
    connection_counts: Counter[str] = Counter()
    for source, target, _ in unique_edges:
        connection_counts[source] += 1
        connection_counts[target] += 1
    nodes = [
        TransactionGraphNode(
            id=public_id,
            type=entity_type,
            label=_label(entity_type, public_id),
            is_current=is_current,
            connection_count=connection_counts[public_id],
        )
        for public_id, (entity_type, is_current) in node_specs.items()
    ]
    edges = [
        TransactionGraphEdge(id=f"edge-{index}", source=source, target=target, type=relation_type)
        for index, (source, target, relation_type) in enumerate(unique_edges)
    ]
    reason = decision.decision_reason
    cluster_id = reason.get("detected_cluster_id")
    return TransactionGraphResponse(
        transaction_id=current.public_id,
        nodes=nodes,
        edges=edges,
        signals=[
            TransactionGraphSignal(
                code=str(item["code"]), label=GRAPH_SIGNAL_TEXT[str(item["code"])]
            )
            for item in graph.signals
            if str(item.get("code")) in GRAPH_SIGNAL_TEXT
        ],
        cluster_id=str(cluster_id) if cluster_id else None,
        has_prior_relationships=bool(prior_rows),
        max_nodes=MAX_GRAPH_NODES,
        max_edges=MAX_GRAPH_EDGES,
    )
