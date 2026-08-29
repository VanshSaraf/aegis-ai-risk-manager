from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.core.enums import ProcessingStatus
from apps.api.app.schemas.contracts import NormalizedTransaction


class TransactionList(BaseModel):
    items: list[NormalizedTransaction]
    limit: int
    offset: int


class Neighbor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str
    public_id: str
    relation_type: str
    direction: str
    first_seen_at: datetime
    last_seen_at: datetime
    observation_count: int = Field(ge=1)


class NeighborList(BaseModel):
    entity_type: str
    public_id: str
    neighbors: list[Neighbor]


class ReadinessResponse(BaseModel):
    status: str
    database: str


class IngestionFailure(BaseModel):
    event_id: str
    processing_status: ProcessingStatus
    detail: str
