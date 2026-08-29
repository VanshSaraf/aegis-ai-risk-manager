from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from apps.api.app.core.enums import ProcessingStatus
from apps.api.app.core.ids import generate_public_id
from apps.api.app.core.time import utc_now
from apps.api.app.models import (
    Address,
    AuditEvent,
    Customer,
    Device,
    EntityEdge,
    IPAddress,
    Merchant,
    PaymentInstrument,
    RawEvent,
    ScenarioRun,
    Transaction,
)
from apps.api.app.schemas.contracts import NormalizedTransaction, RawPaymentEvent
from apps.api.app.schemas.internal import TrustedSyntheticContext


class DuplicateEventError(Exception):
    pass


@dataclass(slots=True)
class NormalizationError(Exception):
    event_id: str
    detail: str


def _raw_payload(event: RawPaymentEvent) -> dict[str, Any]:
    return event.model_dump(mode="json")


async def preserve_raw_event(session: AsyncSession, event: RawPaymentEvent) -> RawEvent:
    received_at = utc_now()
    raw = RawEvent(
        event_id=event.event_id,
        event_type=event.event_type,
        event_version=event.event_version,
        payload=_raw_payload(event),
        event_time=event.event_time,
        received_at=received_at,
        processing_status=ProcessingStatus.RECEIVED,
    )
    session.add(raw)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateEventError(event.event_id) from exc
    return raw


async def _upsert_entity[ModelT: DeclarativeBase](
    session: AsyncSession,
    model: type[ModelT],
    values: dict[str, Any],
    conflict_column: str,
    update_values: dict[str, Any],
) -> ModelT:
    statement = (
        insert(model)
        .values(**values)
        .on_conflict_do_update(index_elements=[conflict_column], set_=update_values)
        .returning(model)
    )
    return (await session.execute(statement)).scalar_one()


async def _resolve_entities(
    session: AsyncSession,
    event: RawPaymentEvent,
    *,
    is_synthetic: bool,
) -> tuple[Customer, Merchant, PaymentInstrument, Device, IPAddress, Address]:
    now = event.event_time
    customer = await _upsert_entity(
        session,
        Customer,
        {
            "public_id": generate_public_id("cus"),
            "source_ref": event.customer_ref,
            "account_created_at": event.account_created_at,
            "customer_segment": event.customer_segment,
            "home_region": event.home_region,
            "is_synthetic": is_synthetic,
        },
        "source_ref",
        {
            "customer_segment": event.customer_segment,
            "home_region": event.home_region,
            "updated_at": utc_now(),
        },
    )
    merchant = await _upsert_entity(
        session,
        Merchant,
        {
            "public_id": generate_public_id("mer"),
            "source_ref": event.merchant_ref,
            "category": event.merchant_category,
            "risk_baseline": event.merchant_risk_baseline,
            "region": event.merchant_region,
        },
        "source_ref",
        {
            "category": event.merchant_category,
            "risk_baseline": event.merchant_risk_baseline,
            "region": event.merchant_region,
        },
    )
    instrument = await _upsert_entity(
        session,
        PaymentInstrument,
        {
            "public_id": generate_public_id("card"),
            "instrument_type": event.instrument_type,
            "fingerprint": event.instrument_fingerprint,
            "issuer_region": event.issuer_region,
            "first_seen_at": now,
            "last_seen_at": now,
        },
        "fingerprint",
        {
            "first_seen_at": func.least(PaymentInstrument.first_seen_at, now),
            "last_seen_at": func.greatest(PaymentInstrument.last_seen_at, now),
        },
    )
    device = await _upsert_entity(
        session,
        Device,
        {
            "public_id": generate_public_id("dev"),
            "device_fingerprint": event.device_fingerprint,
            "device_type": event.device_type,
            "os_family": event.os_family,
            "browser_family": event.browser_family,
            "first_seen_at": now,
            "last_seen_at": now,
        },
        "device_fingerprint",
        {
            "first_seen_at": func.least(Device.first_seen_at, now),
            "last_seen_at": func.greatest(Device.last_seen_at, now),
        },
    )
    ip_address = await _upsert_entity(
        session,
        IPAddress,
        {
            "public_id": generate_public_id("ip"),
            "ip_hash": event.ip_hash,
            "network_type": event.network_type,
            "region": event.ip_region,
            "first_seen_at": now,
            "last_seen_at": now,
        },
        "ip_hash",
        {
            "first_seen_at": func.least(IPAddress.first_seen_at, now),
            "last_seen_at": func.greatest(IPAddress.last_seen_at, now),
        },
    )
    address = await _upsert_entity(
        session,
        Address,
        {
            "public_id": generate_public_id("addr"),
            "address_fingerprint": event.address_fingerprint,
            "region": event.address_region,
            "postal_prefix": event.postal_prefix,
            "first_seen_at": now,
            "last_seen_at": now,
        },
        "address_fingerprint",
        {
            "first_seen_at": func.least(Address.first_seen_at, now),
            "last_seen_at": func.greatest(Address.last_seen_at, now),
        },
    )
    return customer, merchant, instrument, device, ip_address, address


async def _upsert_edge(
    session: AsyncSession,
    source_type: str,
    source_public_id: str,
    relation_type: str,
    target_type: str,
    target_public_id: str,
    observed_at: datetime,
) -> None:
    await session.execute(
        insert(EntityEdge)
        .values(
            source_type=source_type,
            source_public_id=source_public_id,
            relation_type=relation_type,
            target_type=target_type,
            target_public_id=target_public_id,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            observation_count=1,
        )
        .on_conflict_do_update(
            constraint="uq_entity_edges_logical_edge",
            set_={
                "first_seen_at": func.least(EntityEdge.first_seen_at, observed_at),
                "last_seen_at": func.greatest(EntityEdge.last_seen_at, observed_at),
                "observation_count": EntityEdge.observation_count + 1,
                "updated_at": utc_now(),
            },
        )
    )


async def _mark_raw_failed(session: AsyncSession, raw_id: Any, detail: str) -> None:
    raw = await session.get(RawEvent, raw_id, with_for_update=True)
    if raw is None:
        raise RuntimeError("Preserved raw event disappeared")
    raw.processing_status = ProcessingStatus.FAILED
    raw.processing_error = detail[:4000]
    await session.commit()


async def ingest_transaction(
    session: AsyncSession,
    event: RawPaymentEvent,
    *,
    synthetic_context: TrustedSyntheticContext | None = None,
) -> NormalizedTransaction:
    raw = await preserve_raw_event(session, event)
    raw_id = raw.id
    try:
        raw = await session.get(RawEvent, raw_id, with_for_update=True)
        if raw is None:
            raise RuntimeError("Preserved raw event disappeared")
        raw.processing_status = ProcessingStatus.PROCESSING

        scenario_run = None
        if synthetic_context is not None:
            scenario_run = await session.scalar(
                select(ScenarioRun).where(
                    ScenarioRun.public_id == synthetic_context.scenario_run_public_id
                )
            )
            if scenario_run is None:
                raise ValueError(
                    f"Unknown scenario_run_id: {synthetic_context.scenario_run_public_id}"
                )

        customer, merchant, instrument, device, ip_address, address = await _resolve_entities(
            session, event, is_synthetic=synthetic_context is not None
        )
        processed_at = utc_now()
        transaction = Transaction(
            public_id=generate_public_id("txn"),
            customer_id=customer.id,
            merchant_id=merchant.id,
            payment_instrument_id=instrument.id,
            device_id=device.id,
            ip_address_id=ip_address.id,
            address_id=address.id,
            amount_paise=event.amount_paise,
            currency=event.currency,
            payment_method=event.payment_method,
            status=event.status,
            failure_code=event.failure_code,
            event_time=event.event_time,
            received_at=raw.received_at,
            processed_at=processed_at,
            scenario_run_id=scenario_run.id if scenario_run else None,
            ground_truth_label=synthetic_context.label if synthetic_context else None,
            ground_truth_scenario=(synthetic_context.scenario_type if synthetic_context else None),
            ground_truth_ring_id=synthetic_context.ring_id if synthetic_context else None,
        )
        session.add(transaction)

        edges = (
            ("CUSTOMER", customer.public_id, "USES", "DEVICE", device.public_id),
            ("CUSTOMER", customer.public_id, "USES", "PAYMENT_INSTRUMENT", instrument.public_id),
            ("CUSTOMER", customer.public_id, "USES", "IP_ADDRESS", ip_address.public_id),
            ("CUSTOMER", customer.public_id, "USES", "ADDRESS", address.public_id),
            (
                "PAYMENT_INSTRUMENT",
                instrument.public_id,
                "SEEN_ON",
                "DEVICE",
                device.public_id,
            ),
        )
        for source_type, source_id, relation, target_type, target_id in edges:
            await _upsert_edge(
                session, source_type, source_id, relation, target_type, target_id, event.event_time
            )

        session.add(
            AuditEvent(
                public_id=generate_public_id("aud"),
                aggregate_type="TRANSACTION",
                aggregate_id=transaction.public_id,
                event_type="TRANSACTION_INGESTED",
                actor_type="SYSTEM",
                actor_id=None,
                payload={"event_id": event.event_id, "raw_event_id": str(raw.id)},
            )
        )
        raw.processing_status = ProcessingStatus.PROCESSED
        raw.processing_error = None
        await session.commit()
        await session.refresh(transaction)
        return await transaction_to_schema(session, transaction)
    except Exception as exc:
        await session.rollback()
        detail = f"{type(exc).__name__}: {exc}"
        await _mark_raw_failed(session, raw_id, detail)
        raise NormalizationError(event.event_id, detail) from exc


def _transaction_query() -> Select[
    tuple[Transaction, Customer, Merchant, PaymentInstrument, Device, IPAddress, Address]
]:
    return (
        select(Transaction, Customer, Merchant, PaymentInstrument, Device, IPAddress, Address)
        .join(Customer, Transaction.customer_id == Customer.id)
        .join(Merchant, Transaction.merchant_id == Merchant.id)
        .join(PaymentInstrument, Transaction.payment_instrument_id == PaymentInstrument.id)
        .join(Device, Transaction.device_id == Device.id)
        .join(IPAddress, Transaction.ip_address_id == IPAddress.id)
        .join(Address, Transaction.address_id == Address.id)
    )


def _row_to_schema(row: Any) -> NormalizedTransaction:
    transaction, customer, merchant, instrument, device, ip_address, address = row
    return NormalizedTransaction(
        transaction_public_id=transaction.public_id,
        customer_public_id=customer.public_id,
        merchant_public_id=merchant.public_id,
        payment_instrument_public_id=instrument.public_id,
        device_public_id=device.public_id,
        ip_address_public_id=ip_address.public_id,
        address_public_id=address.public_id,
        amount_paise=transaction.amount_paise,
        currency=transaction.currency,
        payment_method=transaction.payment_method,
        event_time=transaction.event_time,
        status=transaction.status,
        failure_code=transaction.failure_code,
        received_at=transaction.received_at,
        processed_at=transaction.processed_at,
        created_at=transaction.created_at,
    )


async def transaction_to_schema(
    session: AsyncSession, transaction: Transaction
) -> NormalizedTransaction:
    row = (
        await session.execute(_transaction_query().where(Transaction.id == transaction.id))
    ).one()
    return _row_to_schema(row)


async def get_transaction(session: AsyncSession, public_id: str) -> NormalizedTransaction | None:
    row = (
        await session.execute(_transaction_query().where(Transaction.public_id == public_id))
    ).one_or_none()
    return _row_to_schema(row) if row else None


async def list_transactions(
    session: AsyncSession, limit: int, offset: int
) -> list[NormalizedTransaction]:
    rows = (
        await session.execute(
            _transaction_query()
            .order_by(Transaction.event_time.desc(), Transaction.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [_row_to_schema(row) for row in rows]
