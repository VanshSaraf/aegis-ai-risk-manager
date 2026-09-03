from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import get_settings
from apps.api.app.core.enums import EntityIntelligenceType, PolicyAction, RiskSeverity
from apps.api.app.db.session import database_is_ready, get_session
from apps.api.app.models import EntityEdge
from apps.api.app.schemas.api import (
    DashboardSummary,
    DashboardTransactionList,
    DemoScenarioRequest,
    DemoSessionResponse,
    DemoStepRequest,
    DemoStepResponse,
    EntityIntelligenceResponse,
    EvaluationSummary,
    GraphEvidenceResponse,
    ModelScoreResponse,
    Neighbor,
    NeighborList,
    OperationalAssessmentResponse,
    PolicyResponse,
    ReadinessResponse,
    RiskResponse,
    TransactionGraphResponse,
    TransactionList,
)
from apps.api.app.schemas.contracts import NormalizedTransaction, RawPaymentEvent
from apps.api.app.services.dashboard import (
    dashboard_summary,
    dashboard_transactions,
    transaction_graph,
)
from apps.api.app.services.demo import (
    DemoSessionNotFoundError,
    DemoStepConflictError,
    create_demo_session,
    step_demo_session,
)
from apps.api.app.services.entities import entity_intelligence
from apps.api.app.services.evaluation import load_evaluation_summary
from apps.api.app.services.transactions import (
    DuplicateEventError,
    NormalizationError,
    get_transaction,
    ingest_transaction,
    list_transactions,
)
from packages.investigator.domain import InvestigationReport
from packages.investigator.service import InvestigatorService
from packages.policy_engine.service import AssessmentConflictError, assess_transaction

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=ReadinessResponse)
async def ready() -> ReadinessResponse | JSONResponse:
    if not await database_is_ready():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "database": "unavailable"},
        )
    return ReadinessResponse(status="ready", database="available")


@router.get("/api/v1/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary_route(session: Session) -> DashboardSummary:
    return await dashboard_summary(session)


@router.get("/api/v1/dashboard/transactions", response_model=DashboardTransactionList)
async def dashboard_transactions_route(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    action: PolicyAction | None = None,
    severity: RiskSeverity | None = None,
) -> DashboardTransactionList:
    items = await dashboard_transactions(session, limit=limit, action=action, severity=severity)
    return DashboardTransactionList(items=items, limit=limit)


@router.get("/api/v1/evaluation/summary", response_model=EvaluationSummary)
async def evaluation_summary_route() -> EvaluationSummary:
    return load_evaluation_summary()


def _require_demo_mode() -> None:
    if not get_settings().demo_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


@router.post("/api/v1/demo/sessions", response_model=DemoSessionResponse)
async def start_demo(request: DemoScenarioRequest, session: Session) -> DemoSessionResponse:
    _require_demo_mode()
    del request  # The registered canonical scenario is validated by the request schema.
    return await create_demo_session(session)


@router.post("/api/v1/demo/sessions/{session_id}/step", response_model=DemoStepResponse)
async def demo_step(
    session_id: str, request: DemoStepRequest, session: Session
) -> DemoStepResponse:
    _require_demo_mode()
    try:
        return await step_demo_session(session, session_id, request.expected_step)
    except DemoSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="demo session not found"
        ) from exc
    except DemoStepConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/api/v1/transactions",
    response_model=NormalizedTransaction,
    status_code=status.HTTP_201_CREATED,
)
async def create_transaction(event: RawPaymentEvent, session: Session) -> NormalizedTransaction:
    try:
        return await ingest_transaction(session, event)
    except DuplicateEventError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="event_id already exists"
        ) from exc
    except NormalizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "event_id": exc.event_id,
                "processing_status": "FAILED",
                "error": exc.detail,
            },
        ) from exc


@router.get("/api/v1/transactions", response_model=TransactionList)
async def transactions(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TransactionList:
    items = await list_transactions(session, limit, offset)
    return TransactionList(items=items, limit=limit, offset=offset)


@router.get("/api/v1/transactions/{public_id}", response_model=NormalizedTransaction)
async def transaction(public_id: str, session: Session) -> NormalizedTransaction:
    result = await get_transaction(session, public_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="transaction not found")
    return result


@router.post(
    "/api/v1/transactions/{public_id}/assess",
    response_model=OperationalAssessmentResponse,
)
async def assess(public_id: str, session: Session) -> OperationalAssessmentResponse:
    try:
        result = await assess_transaction(session, public_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="transaction not found"
        ) from exc
    except AssessmentConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="immutable assessment conflict"
        ) from exc
    assessment = result.assessment
    decision = result.decision
    return OperationalAssessmentResponse(
        transaction_id=public_id,
        risk_prediction_id=result.risk_prediction_id,
        policy_decision_id=result.policy_decision_id,
        model=ModelScoreResponse(
            version=assessment.model_version,
            score=assessment.model_score,
            semantics="uncalibrated model score; not a fraud probability",
        ),
        graph=GraphEvidenceResponse(
            version=assessment.graph_version,
            structural_score=assessment.graph_structure_score,
            signals=[signal.code for signal in assessment.graph_signals],
            detected_cluster_id=assessment.detected_cluster_id,
        ),
        risk=RiskResponse(severity=assessment.severity),
        policy=PolicyResponse(
            version=decision.policy_version,
            action=decision.action,
            requires_human_review=decision.requires_human_review,
            reason_codes=list(decision.reason_codes),
        ),
        latency_ms=result.latency_ms,
    )


@router.get(
    "/api/v1/transactions/{public_id}/investigation",
    response_model=InvestigationReport,
)
async def investigation(public_id: str, session: Session) -> InvestigationReport:
    try:
        return await InvestigatorService().investigate(session, public_id)
    except LookupError as exc:
        if str(exc) == "transaction not found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="transaction not found"
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="transaction must be assessed before investigation",
        ) from exc


@router.get(
    "/api/v1/transactions/{public_id}/graph",
    response_model=TransactionGraphResponse,
)
async def graph(public_id: str, session: Session) -> TransactionGraphResponse:
    try:
        return await transaction_graph(session, public_id)
    except LookupError as exc:
        if str(exc) == "transaction not found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="transaction not found"
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="transaction must be assessed before graph inspection",
        ) from exc


@router.get(
    "/api/v1/entities/{entity_type}/{public_id}",
    response_model=EntityIntelligenceResponse,
)
async def entity_intelligence_route(
    entity_type: EntityIntelligenceType,
    public_id: str,
    session: Session,
) -> EntityIntelligenceResponse:
    try:
        return await entity_intelligence(session, entity_type, public_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="entity not found"
        ) from exc


@router.get("/api/v1/entities/{entity_type}/{public_id}/neighbors", response_model=NeighborList)
async def entity_neighbors(
    entity_type: EntityIntelligenceType,
    public_id: str,
    session: Session,
) -> NeighborList:
    normalized_type = entity_type.value
    edges = (
        await session.scalars(
            select(EntityEdge)
            .where(
                or_(
                    (EntityEdge.source_type == normalized_type)
                    & (EntityEdge.source_public_id == public_id),
                    (EntityEdge.target_type == normalized_type)
                    & (EntityEdge.target_public_id == public_id),
                )
            )
            .order_by(EntityEdge.last_seen_at.desc())
            .limit(100)
        )
    ).all()
    neighbors = []
    for edge in edges:
        outgoing = edge.source_type == normalized_type and edge.source_public_id == public_id
        neighbors.append(
            Neighbor(
                entity_type=edge.target_type if outgoing else edge.source_type,
                public_id=edge.target_public_id if outgoing else edge.source_public_id,
                relation_type=edge.relation_type,
                direction="OUTGOING" if outgoing else "INCOMING",
                first_seen_at=edge.first_seen_at,
                last_seen_at=edge.last_seen_at,
                observation_count=edge.observation_count,
            )
        )
    return NeighborList(entity_type=normalized_type, public_id=public_id, neighbors=neighbors)
