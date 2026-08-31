import asyncio
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from apps.api.app.core.time import utc_now
from apps.api.app.schemas.api import (
    DemoAssessmentSummary,
    DemoScenario,
    DemoSessionResponse,
    DemoStepResponse,
    DemoTransactionSummary,
)
from apps.api.app.schemas.contracts import NormalizedTransaction, RawPaymentEvent
from apps.api.app.services.transactions import ingest_transaction
from packages.policy_engine.service import assess_transaction
from packages.synthetic.demo import build_identity_rotation_demo

MAX_DEMO_SESSIONS = 6


class DemoSessionNotFoundError(LookupError):
    pass


class DemoStepConflictError(ValueError):
    pass


@dataclass(slots=True)
class DemoSessionState:
    session_id: str
    baseline_count: int
    events: tuple[RawPaymentEvent, ...]
    next_step: int = 0
    responses: dict[int, DemoStepResponse] = field(default_factory=dict)
    pending_transactions: dict[int, NormalizedTransaction] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class DemoSessionRegistry:
    def __init__(self, max_sessions: int = MAX_DEMO_SESSIONS) -> None:
        self.max_sessions = max_sessions
        self._sessions: OrderedDict[str, DemoSessionState] = OrderedDict()
        self._lock = asyncio.Lock()

    async def add(self, state: DemoSessionState) -> None:
        async with self._lock:
            self._sessions[state.session_id] = state
            self._sessions.move_to_end(state.session_id)
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)

    async def get(self, session_id: str) -> DemoSessionState:
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                raise DemoSessionNotFoundError(session_id)
            self._sessions.move_to_end(session_id)
            return state

    async def clear(self) -> None:
        async with self._lock:
            self._sessions.clear()


DEMO_SESSIONS = DemoSessionRegistry()


def _generate_demo_session_id() -> str:
    return f"demo_{ULID()}"


def _scenario() -> DemoScenario:
    return DemoScenario(
        code="IDENTITY_ROTATION",
        display_name="Identity Rotation",
        description="Rotating customer and instrument identities reuse shared infrastructure.",
    )


async def create_demo_session(
    session: AsyncSession,
    *,
    registry: DemoSessionRegistry = DEMO_SESSIONS,
    session_id_factory: Callable[[], str] = _generate_demo_session_id,
    clock: Callable[[], datetime] = utc_now,
) -> DemoSessionResponse:
    session_id = session_id_factory()
    namespace = session_id.removeprefix("demo_").lower()
    sequence = build_identity_rotation_demo(namespace, clock().replace(microsecond=0))
    for event in sequence.baseline:
        transaction = await ingest_transaction(session, event)
        await assess_transaction(session, transaction.transaction_public_id)
    state = DemoSessionState(
        session_id=session_id,
        baseline_count=len(sequence.baseline),
        events=sequence.showcase,
    )
    await registry.add(state)
    return DemoSessionResponse(
        session_id=session_id,
        scenario=_scenario(),
        baseline_transactions=len(sequence.baseline),
        total_steps=len(sequence.showcase),
        next_step=0,
    )


async def step_demo_session(
    session: AsyncSession,
    session_id: str,
    expected_step: int,
    *,
    registry: DemoSessionRegistry = DEMO_SESSIONS,
) -> DemoStepResponse:
    state = await registry.get(session_id)
    async with state.lock:
        if expected_step < state.next_step:
            cached = state.responses.get(expected_step)
            if cached is None:
                raise DemoStepConflictError("step replay is no longer available")
            return cached
        if expected_step > state.next_step:
            raise DemoStepConflictError("expected_step is ahead of the session")
        if state.next_step == len(state.events):
            return DemoStepResponse(
                session_id=session_id,
                step=state.next_step,
                total_steps=len(state.events),
                complete=True,
                transaction=None,
                assessment=None,
            )

        transaction = state.pending_transactions.get(state.next_step)
        if transaction is None:
            event = state.events[state.next_step]
            transaction = await ingest_transaction(session, event)
            state.pending_transactions[state.next_step] = transaction
        result = await assess_transaction(session, transaction.transaction_public_id)
        response = DemoStepResponse(
            session_id=session_id,
            step=state.next_step + 1,
            total_steps=len(state.events),
            complete=state.next_step + 1 == len(state.events),
            transaction=DemoTransactionSummary(
                public_id=transaction.transaction_public_id,
                amount_paise=transaction.amount_paise,
                event_time=transaction.event_time,
            ),
            assessment=DemoAssessmentSummary(
                model_score=result.assessment.model_score,
                model_score_semantics=("uncalibrated risk ranking score; not a fraud probability"),
                action=result.decision.action,
                severity=result.assessment.severity,
                graph_signal_count=len(result.assessment.graph_signals),
                cluster_id=result.assessment.detected_cluster_id,
            ),
        )
        state.responses[state.next_step] = response
        state.pending_transactions.pop(state.next_step, None)
        state.next_step += 1
        return response
