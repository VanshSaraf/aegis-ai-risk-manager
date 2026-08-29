from datetime import datetime

import pytest
from pydantic import ValidationError

from apps.api.app.schemas.contracts import RawPaymentEvent, ScoringTransaction
from apps.api.tests.factories import raw_event_payload


@pytest.mark.parametrize("amount", [0, -1, 10.5, "1899.99"])
def test_money_must_be_positive_integer_paise(amount: object) -> None:
    with pytest.raises(ValidationError):
        RawPaymentEvent.model_validate(raw_event_payload(amount_paise=amount))


def test_naive_timestamps_are_rejected() -> None:
    payload = raw_event_payload(event_time=datetime(2026, 1, 1, 12, 0))
    with pytest.raises(ValidationError, match="timezone-aware"):
        RawPaymentEvent.model_validate(payload)


def test_failed_transaction_requires_failure_code() -> None:
    with pytest.raises(ValidationError, match="failure_code"):
        RawPaymentEvent.model_validate(raw_event_payload(status="FAILED"))


def test_scoring_contract_rejects_ground_truth() -> None:
    with pytest.raises(ValidationError):
        ScoringTransaction.model_validate(
            {
                "transaction_public_id": "txn_1",
                "customer_public_id": "cus_1",
                "merchant_public_id": "mer_1",
                "payment_instrument_public_id": "card_1",
                "device_public_id": "dev_1",
                "ip_address_public_id": "ip_1",
                "address_public_id": "addr_1",
                "amount_paise": 100,
                "currency": "INR",
                "payment_method": "CARD",
                "event_time": "2026-01-01T00:00:00Z",
                "ground_truth_label": "COORDINATED_ABUSE",
            }
        )


def test_ground_truth_requires_synthetic_scenario_run() -> None:
    with pytest.raises(ValidationError, match="scenario_run_id"):
        RawPaymentEvent.model_validate(raw_event_payload(ground_truth_label="COORDINATED_ABUSE"))
