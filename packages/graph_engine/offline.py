from dataclasses import dataclass
from itertools import groupby

from packages.graph_engine.clustering import StructuralClusterDetector
from packages.graph_engine.domain import DetectedCluster, GraphAssessment, GraphTransaction
from packages.graph_engine.engine import GraphEngine
from packages.graph_engine.state import InMemoryGraphState
from packages.graph_engine.validation import validate_graph_assessment
from packages.risk_engine.features.offline import generated_event_to_feature_transaction
from packages.synthetic.domain import GeneratedEvent, SyntheticDataset


@dataclass(slots=True)
class OfflineGraphResult:
    assessments: list[GraphAssessment]
    state: InMemoryGraphState
    clusters: list[DetectedCluster]


def generated_event_to_graph_transaction(event: GeneratedEvent) -> GraphTransaction:
    transaction = generated_event_to_feature_transaction(event)
    return GraphTransaction(
        transaction_public_id=transaction.transaction_public_id,
        customer_id=transaction.customer_id,
        instrument_id=transaction.instrument_id,
        device_id=transaction.device_id,
        ip_id=transaction.ip_id,
        address_id=transaction.address_id,
        amount_paise=transaction.amount_paise,
        event_time=transaction.event_time,
    )


async def build_offline_graph(
    transactions: list[GraphTransaction],
) -> OfflineGraphResult:
    engine = GraphEngine()
    state = InMemoryGraphState()
    assessments: list[GraphAssessment] = []
    ordered = sorted(
        transactions,
        key=lambda transaction: (transaction.event_time, transaction.transaction_public_id),
    )
    for _, same_time_iterator in groupby(ordered, key=lambda item: item.event_time):
        same_time = list(same_time_iterator)
        for transaction in same_time:
            assessment = engine.assess(transaction, state)
            validate_graph_assessment(assessment, transaction)
            assessments.append(assessment)
        state.observe_many(same_time)
    return OfflineGraphResult(
        assessments=assessments,
        state=state,
        clusters=StructuralClusterDetector().discover(state),
    )


async def build_synthetic_graph(dataset: SyntheticDataset) -> OfflineGraphResult:
    return await build_offline_graph(
        [generated_event_to_graph_transaction(event) for event in dataset.events]
    )
