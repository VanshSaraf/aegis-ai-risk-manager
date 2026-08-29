import pytest

from apps.api.app.core.ids import generate_public_id


def test_public_ids_have_prefix_and_are_unique() -> None:
    first = generate_public_id("txn")
    second = generate_public_id("txn")

    assert first.startswith("txn_")
    assert first != second
    assert len(first.removeprefix("txn_")) == 26


def test_unknown_public_id_prefix_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        generate_public_id("unknown")
