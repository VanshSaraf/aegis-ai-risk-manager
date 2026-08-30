from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models import (
    Address,
    Customer,
    Device,
    IPAddress,
    Merchant,
    PaymentInstrument,
    Transaction,
)
from packages.risk_engine.features.domain import FeatureTransaction, ScoringFeatureTransaction


def transaction_history_query():
    return (
        select(
            Transaction,
            Customer,
            Merchant,
            PaymentInstrument,
            Device,
            IPAddress,
            Address,
        )
        .join(Customer, Transaction.customer_id == Customer.id)
        .join(Merchant, Transaction.merchant_id == Merchant.id)
        .join(PaymentInstrument, Transaction.payment_instrument_id == PaymentInstrument.id)
        .join(Device, Transaction.device_id == Device.id)
        .join(IPAddress, Transaction.ip_address_id == IPAddress.id)
        .join(Address, Transaction.address_id == Address.id)
    )


def row_to_feature_transaction(row) -> FeatureTransaction:
    transaction, customer, merchant, instrument, device, ip, address = row
    return FeatureTransaction(
        transaction_public_id=transaction.public_id,
        customer_id=customer.public_id,
        merchant_id=merchant.public_id,
        instrument_id=instrument.public_id,
        device_id=device.public_id,
        ip_id=ip.public_id,
        address_id=address.public_id,
        amount_paise=transaction.amount_paise,
        currency=transaction.currency,
        payment_method=transaction.payment_method,
        event_time=transaction.event_time,
        account_created_at=customer.account_created_at,
        status=transaction.status,
        failure_code=transaction.failure_code,
    )


class PostgreSQLHistoryProvider:
    """Loads one point-in-time union of relevant entity history per transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def history_for(
        self, current: ScoringFeatureTransaction
    ) -> tuple[FeatureTransaction, ...]:
        statement = (
            transaction_history_query()
            .where(
                Transaction.event_time < current.event_time,
                or_(
                    Customer.public_id == current.customer_id,
                    Device.public_id == current.device_id,
                    PaymentInstrument.public_id == current.instrument_id,
                    IPAddress.public_id == current.ip_id,
                    Address.public_id == current.address_id,
                ),
            )
            .order_by(Transaction.event_time, Transaction.public_id)
        )
        return tuple(
            row_to_feature_transaction(row) for row in (await self.session.execute(statement))
        )
