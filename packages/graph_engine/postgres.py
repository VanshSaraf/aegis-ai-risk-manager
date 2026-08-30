from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models import Address, Customer, Device, IPAddress, PaymentInstrument, Transaction
from packages.graph_engine.domain import GraphTransaction
from packages.graph_engine.state import InMemoryGraphState
from packages.risk_engine.features.postgres import transaction_history_query


def row_to_graph_transaction(row) -> GraphTransaction:
    transaction, customer, _merchant, instrument, device, ip, address = row
    return GraphTransaction(
        transaction_public_id=transaction.public_id,
        customer_id=customer.public_id,
        instrument_id=instrument.public_id,
        device_id=device.public_id,
        ip_id=ip.public_id,
        address_id=address.public_id,
        amount_paise=transaction.amount_paise,
        event_time=transaction.event_time,
    )


class PostgreSQLGraphProvider:
    """Reconstructs only historical components touched by the current transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def state_for(self, current: GraphTransaction) -> InMemoryGraphState:
        entity_ids = {
            "customer": {current.customer_id},
            "instrument": {current.instrument_id},
            "device": {current.device_id},
            "ip": {current.ip_id},
            "address": {current.address_id},
        }
        records: dict[str, GraphTransaction] = {}
        while True:
            statement = (
                transaction_history_query()
                .where(
                    Transaction.event_time < current.event_time,
                    or_(
                        Customer.public_id.in_(entity_ids["customer"]),
                        PaymentInstrument.public_id.in_(entity_ids["instrument"]),
                        Device.public_id.in_(entity_ids["device"]),
                        IPAddress.public_id.in_(entity_ids["ip"]),
                        Address.public_id.in_(entity_ids["address"]),
                    ),
                )
                .order_by(Transaction.event_time, Transaction.public_id)
            )
            found_new = False
            for row in await self.session.execute(statement):
                graph_transaction = row_to_graph_transaction(row)
                if graph_transaction.transaction_public_id in records:
                    continue
                records[graph_transaction.transaction_public_id] = graph_transaction
                entity_ids["customer"].add(graph_transaction.customer_id)
                entity_ids["instrument"].add(graph_transaction.instrument_id)
                entity_ids["device"].add(graph_transaction.device_id)
                entity_ids["ip"].add(graph_transaction.ip_id)
                entity_ids["address"].add(graph_transaction.address_id)
                found_new = True
            if not found_new:
                break
        return InMemoryGraphState(records.values())
