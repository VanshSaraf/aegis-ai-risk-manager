import math
from collections.abc import Sequence
from datetime import timedelta
from statistics import fmean, pstdev

from apps.api.app.core.enums import TransactionStatus
from apps.api.app.core.time import utc_now
from apps.api.app.schemas.contracts import FeatureVector
from packages.risk_engine.features.domain import FeatureTransaction, ScoringFeatureTransaction
from packages.risk_engine.features.history import HistoryProvider
from packages.risk_engine.features.registry import FEATURE_VERSION

WINDOWS = {
    "1m": timedelta(minutes=1),
    "10m": timedelta(minutes=10),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "30d": timedelta(days=30),
}


def is_historical_failure(transaction: FeatureTransaction) -> bool:
    return transaction.status == TransactionStatus.FAILED


def _within(
    records: Sequence[FeatureTransaction],
    current: ScoringFeatureTransaction,
    window: str,
) -> list[FeatureTransaction]:
    lower = current.event_time - WINDOWS[window]
    return [record for record in records if lower <= record.event_time < current.event_time]


def _matching(
    records: Sequence[FeatureTransaction], field: str, value: str
) -> list[FeatureTransaction]:
    return [record for record in records if getattr(record, field) == value]


def _unique(records: Sequence[FeatureTransaction], field: str) -> int:
    return len({getattr(record, field) for record in records})


class FeatureEngine:
    feature_version = FEATURE_VERSION

    async def compute(
        self,
        current: ScoringFeatureTransaction,
        history_provider: HistoryProvider,
    ) -> FeatureVector:
        history = tuple(await history_provider.history_for(current))
        if any(record.event_time >= current.event_time for record in history):
            raise ValueError("history provider returned a current or future transaction")

        customer = _matching(history, "customer_id", current.customer_id)
        device = _matching(history, "device_id", current.device_id)
        ip = _matching(history, "ip_id", current.ip_id)
        instrument = _matching(history, "instrument_id", current.instrument_id)
        address = _matching(history, "address_id", current.address_id)

        customer_1h = _within(customer, current, "1h")
        customer_24h = _within(customer, current, "24h")
        customer_30d = _within(customer, current, "30d")
        device_1m = _within(device, current, "1m")
        device_10m = _within(device, current, "10m")
        device_1h = _within(device, current, "1h")
        ip_10m = _within(ip, current, "10m")
        ip_1h = _within(ip, current, "1h")
        ip_24h = _within(ip, current, "24h")
        instrument_10m = _within(instrument, current, "10m")
        instrument_1h = _within(instrument, current, "1h")
        instrument_24h = _within(instrument, current, "24h")
        address_1h = _within(address, current, "1h")
        address_24h = _within(address, current, "24h")

        amounts = [record.amount_paise for record in customer_30d]
        amount_mean = fmean(amounts) if amounts else 0.0
        amount_std = pstdev(amounts) if len(amounts) > 1 else 0.0
        failures_30d = sum(is_historical_failure(record) for record in customer_30d)
        account_age_hours = max(
            0.0,
            (current.event_time - current.account_created_at).total_seconds() / 3600,
        )

        values: dict[str, float | int | bool] = {
            "amount_paise": current.amount_paise,
            "log_amount": math.log1p(current.amount_paise),
            "account_age_hours": account_age_hours,
            "hour_of_day": current.event_time.hour,
            "day_of_week": current.event_time.weekday(),
            "is_weekend": current.event_time.weekday() >= 5,
            "customer_txn_count_1h": len(customer_1h),
            "customer_txn_count_24h": len(customer_24h),
            "customer_txn_count_30d": len(customer_30d),
            "customer_failed_txn_count_1h": sum(map(is_historical_failure, customer_1h)),
            "customer_failed_txn_count_24h": sum(map(is_historical_failure, customer_24h)),
            "customer_failure_rate_30d": failures_30d / len(customer_30d) if customer_30d else 0.0,
            "customer_avg_amount_30d": amount_mean,
            "customer_amount_std_30d": amount_std,
            "amount_vs_customer_mean": current.amount_paise / amount_mean if amount_mean else 0.0,
            "amount_zscore_customer": (current.amount_paise - amount_mean) / amount_std
            if amount_std
            else 0.0,
            "customer_unique_devices_24h": _unique(customer_24h, "device_id"),
            "customer_unique_instruments_24h": _unique(customer_24h, "instrument_id"),
            "customer_unique_ips_24h": _unique(customer_24h, "ip_id"),
            "customer_unique_addresses_30d": _unique(customer_30d, "address_id"),
            "customer_merchant_txn_count_30d": sum(
                record.merchant_id == current.merchant_id for record in customer_30d
            ),
            "is_new_device_for_customer": not any(
                record.device_id == current.device_id for record in customer
            ),
            "is_new_instrument_for_customer": not any(
                record.instrument_id == current.instrument_id for record in customer
            ),
            "is_new_ip_for_customer": not any(record.ip_id == current.ip_id for record in customer),
            "is_new_address_for_customer": not any(
                record.address_id == current.address_id for record in customer
            ),
            "device_txn_count_1m": len(device_1m),
            "device_txn_count_10m": len(device_10m),
            "device_txn_count_1h": len(device_1h),
            "device_failed_txn_count_10m": sum(map(is_historical_failure, device_10m)),
            "device_failed_txn_count_1h": sum(map(is_historical_failure, device_1h)),
            "device_unique_customers_1h": _unique(device_1h, "customer_id"),
            "device_unique_instruments_1h": _unique(device_1h, "instrument_id"),
            "ip_txn_count_10m": len(ip_10m),
            "ip_txn_count_1h": len(ip_1h),
            "ip_failed_txn_count_10m": sum(map(is_historical_failure, ip_10m)),
            "ip_failed_txn_count_1h": sum(map(is_historical_failure, ip_1h)),
            "ip_unique_customers_1h": _unique(ip_1h, "customer_id"),
            "ip_unique_customers_24h": _unique(ip_24h, "customer_id"),
            "instrument_txn_count_10m": len(instrument_10m),
            "instrument_txn_count_1h": len(instrument_1h),
            "instrument_txn_count_24h": len(instrument_24h),
            "instrument_failed_txn_count_1h": sum(map(is_historical_failure, instrument_1h)),
            "instrument_unique_devices_24h": _unique(instrument_24h, "device_id"),
            "address_txn_count_1h": len(address_1h),
            "address_txn_count_24h": len(address_24h),
            "address_unique_customers_24h": _unique(address_24h, "customer_id"),
            "historical_customers_on_current_device": _unique(device, "customer_id"),
            "historical_instruments_on_current_device": _unique(device, "instrument_id"),
            "historical_customers_on_current_ip": _unique(ip, "customer_id"),
            "historical_devices_on_current_ip": _unique(ip, "device_id"),
            "historical_customers_on_current_address": _unique(address, "customer_id"),
            "historical_devices_for_current_instrument": _unique(instrument, "device_id"),
        }
        max_source_event_time = max(
            (record.event_time for record in history),
            default=None,
        )
        return FeatureVector(
            transaction_public_id=current.transaction_public_id,
            feature_version=self.feature_version,
            values=values,
            computed_at=utc_now(),
            max_source_event_time=max_source_event_time,
        )
