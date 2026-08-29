from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.db.session import database_is_ready, get_session
from apps.api.app.models import EntityEdge
from apps.api.app.schemas.api import Neighbor, NeighborList, ReadinessResponse, TransactionList
from apps.api.app.schemas.contracts import NormalizedTransaction, RawPaymentEvent
from apps.api.app.services.transactions import (
    DuplicateEventError,
    NormalizationError,
    get_transaction,
    ingest_transaction,
    list_transactions,
)

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


@router.get("/api/v1/entities/{entity_type}/{public_id}/neighbors", response_model=NeighborList)
async def entity_neighbors(entity_type: str, public_id: str, session: Session) -> NeighborList:
    normalized_type = entity_type.upper()
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
