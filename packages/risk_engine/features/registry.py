from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Literal

FEATURE_VERSION = "features-v1"


class FeatureFamily(StrEnum):
    TRANSACTION = "TRANSACTION"
    CUSTOMER = "CUSTOMER"
    VELOCITY = "VELOCITY"
    RELATIONSHIP = "RELATIONSHIP"


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    family: FeatureFamily
    value_type: Literal["int", "float", "bool"]
    description: str
    window: str | None = None
    uses_historical_outcome: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _spec(
    name: str,
    family: FeatureFamily,
    value_type: Literal["int", "float", "bool"],
    description: str,
    window: str | None = None,
    *,
    uses_historical_outcome: bool = False,
) -> FeatureSpec:
    return FeatureSpec(name, family, value_type, description, window, uses_historical_outcome)


FEATURES_V1: tuple[FeatureSpec, ...] = (
    _spec("amount_paise", FeatureFamily.TRANSACTION, "int", "Requested amount in paise."),
    _spec("log_amount", FeatureFamily.TRANSACTION, "float", "Natural log of 1 + amount."),
    _spec("account_age_hours", FeatureFamily.TRANSACTION, "float", "Account age at request."),
    _spec("hour_of_day", FeatureFamily.TRANSACTION, "int", "UTC hour of request."),
    _spec("day_of_week", FeatureFamily.TRANSACTION, "int", "UTC weekday, Monday is zero."),
    _spec("is_weekend", FeatureFamily.TRANSACTION, "bool", "Whether request is on weekend."),
    _spec("customer_txn_count_1h", FeatureFamily.CUSTOMER, "int", "Prior customer payments.", "1h"),
    _spec(
        "customer_txn_count_24h", FeatureFamily.CUSTOMER, "int", "Prior customer payments.", "24h"
    ),
    _spec(
        "customer_txn_count_30d", FeatureFamily.CUSTOMER, "int", "Prior customer payments.", "30d"
    ),
    _spec(
        "customer_failed_txn_count_1h",
        FeatureFamily.CUSTOMER,
        "int",
        "Prior failed customer payments.",
        "1h",
        uses_historical_outcome=True,
    ),
    _spec(
        "customer_failed_txn_count_24h",
        FeatureFamily.CUSTOMER,
        "int",
        "Prior failed customer payments.",
        "24h",
        uses_historical_outcome=True,
    ),
    _spec(
        "customer_failure_rate_30d",
        FeatureFamily.CUSTOMER,
        "float",
        "Prior customer failure rate.",
        "30d",
        uses_historical_outcome=True,
    ),
    _spec(
        "customer_avg_amount_30d",
        FeatureFamily.CUSTOMER,
        "float",
        "Mean prior customer amount.",
        "30d",
    ),
    _spec(
        "customer_amount_std_30d",
        FeatureFamily.CUSTOMER,
        "float",
        "Population standard deviation of prior amounts.",
        "30d",
    ),
    _spec(
        "amount_vs_customer_mean",
        FeatureFamily.CUSTOMER,
        "float",
        "Current amount divided by prior mean; zero without history.",
        "30d",
    ),
    _spec(
        "amount_zscore_customer",
        FeatureFamily.CUSTOMER,
        "float",
        "Current amount z-score; zero without usable variance.",
        "30d",
    ),
    _spec(
        "customer_unique_devices_24h",
        FeatureFamily.CUSTOMER,
        "int",
        "Distinct prior devices.",
        "24h",
    ),
    _spec(
        "customer_unique_instruments_24h",
        FeatureFamily.CUSTOMER,
        "int",
        "Distinct prior instruments.",
        "24h",
    ),
    _spec(
        "customer_unique_ips_24h", FeatureFamily.CUSTOMER, "int", "Distinct prior networks.", "24h"
    ),
    _spec(
        "customer_unique_addresses_30d",
        FeatureFamily.CUSTOMER,
        "int",
        "Distinct prior addresses.",
        "30d",
    ),
    _spec(
        "customer_merchant_txn_count_30d",
        FeatureFamily.CUSTOMER,
        "int",
        "Prior payments by this customer at this merchant.",
        "30d",
    ),
    _spec(
        "is_new_device_for_customer",
        FeatureFamily.CUSTOMER,
        "bool",
        "Device has no prior use by customer.",
    ),
    _spec(
        "is_new_instrument_for_customer",
        FeatureFamily.CUSTOMER,
        "bool",
        "Instrument has no prior use by customer.",
    ),
    _spec(
        "is_new_ip_for_customer",
        FeatureFamily.CUSTOMER,
        "bool",
        "Network has no prior use by customer.",
    ),
    _spec(
        "is_new_address_for_customer",
        FeatureFamily.CUSTOMER,
        "bool",
        "Address has no prior use by customer.",
    ),
    _spec("device_txn_count_1m", FeatureFamily.VELOCITY, "int", "Prior device payments.", "1m"),
    _spec("device_txn_count_10m", FeatureFamily.VELOCITY, "int", "Prior device payments.", "10m"),
    _spec("device_txn_count_1h", FeatureFamily.VELOCITY, "int", "Prior device payments.", "1h"),
    _spec(
        "device_failed_txn_count_10m",
        FeatureFamily.VELOCITY,
        "int",
        "Prior failed device payments.",
        "10m",
        uses_historical_outcome=True,
    ),
    _spec(
        "device_failed_txn_count_1h",
        FeatureFamily.VELOCITY,
        "int",
        "Prior failed device payments.",
        "1h",
        uses_historical_outcome=True,
    ),
    _spec(
        "device_unique_customers_1h",
        FeatureFamily.VELOCITY,
        "int",
        "Distinct prior customers on device.",
        "1h",
    ),
    _spec(
        "device_unique_instruments_1h",
        FeatureFamily.VELOCITY,
        "int",
        "Distinct prior instruments on device.",
        "1h",
    ),
    _spec("ip_txn_count_10m", FeatureFamily.VELOCITY, "int", "Prior network payments.", "10m"),
    _spec("ip_txn_count_1h", FeatureFamily.VELOCITY, "int", "Prior network payments.", "1h"),
    _spec(
        "ip_failed_txn_count_10m",
        FeatureFamily.VELOCITY,
        "int",
        "Prior failed network payments.",
        "10m",
        uses_historical_outcome=True,
    ),
    _spec(
        "ip_failed_txn_count_1h",
        FeatureFamily.VELOCITY,
        "int",
        "Prior failed network payments.",
        "1h",
        uses_historical_outcome=True,
    ),
    _spec(
        "ip_unique_customers_1h",
        FeatureFamily.VELOCITY,
        "int",
        "Distinct prior customers on network.",
        "1h",
    ),
    _spec(
        "ip_unique_customers_24h",
        FeatureFamily.VELOCITY,
        "int",
        "Distinct prior customers on network.",
        "24h",
    ),
    _spec(
        "instrument_txn_count_10m",
        FeatureFamily.VELOCITY,
        "int",
        "Prior instrument payments.",
        "10m",
    ),
    _spec(
        "instrument_txn_count_1h", FeatureFamily.VELOCITY, "int", "Prior instrument payments.", "1h"
    ),
    _spec(
        "instrument_txn_count_24h",
        FeatureFamily.VELOCITY,
        "int",
        "Prior instrument payments.",
        "24h",
    ),
    _spec(
        "instrument_failed_txn_count_1h",
        FeatureFamily.VELOCITY,
        "int",
        "Prior failed instrument payments.",
        "1h",
        uses_historical_outcome=True,
    ),
    _spec(
        "instrument_unique_devices_24h",
        FeatureFamily.VELOCITY,
        "int",
        "Distinct prior devices for instrument.",
        "24h",
    ),
    _spec("address_txn_count_1h", FeatureFamily.VELOCITY, "int", "Prior address payments.", "1h"),
    _spec("address_txn_count_24h", FeatureFamily.VELOCITY, "int", "Prior address payments.", "24h"),
    _spec(
        "address_unique_customers_24h",
        FeatureFamily.VELOCITY,
        "int",
        "Distinct prior customers at address.",
        "24h",
    ),
    _spec(
        "historical_customers_on_current_device",
        FeatureFamily.RELATIONSHIP,
        "int",
        "All prior customers linked to device.",
    ),
    _spec(
        "historical_instruments_on_current_device",
        FeatureFamily.RELATIONSHIP,
        "int",
        "All prior instruments linked to device.",
    ),
    _spec(
        "historical_customers_on_current_ip",
        FeatureFamily.RELATIONSHIP,
        "int",
        "All prior customers linked to network.",
    ),
    _spec(
        "historical_devices_on_current_ip",
        FeatureFamily.RELATIONSHIP,
        "int",
        "All prior devices linked to network.",
    ),
    _spec(
        "historical_customers_on_current_address",
        FeatureFamily.RELATIONSHIP,
        "int",
        "All prior customers linked to address.",
    ),
    _spec(
        "historical_devices_for_current_instrument",
        FeatureFamily.RELATIONSHIP,
        "int",
        "All prior devices linked to instrument.",
    ),
)

FEATURE_NAMES = tuple(spec.name for spec in FEATURES_V1)
FEATURE_BY_NAME = {spec.name: spec for spec in FEATURES_V1}

if len(FEATURE_NAMES) != len(set(FEATURE_NAMES)):
    raise RuntimeError("features-v1 contains duplicate feature names")
