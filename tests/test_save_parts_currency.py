"""Unit tests verifying currency handling in PartSaveInput schema and save_parts_sync."""

from unittest.mock import MagicMock
import pytest

from binner_mcp.api.models import PartResponse
from binner_mcp.mcp.schemas import PartSaveInput
from binner_mcp.mcp.tools.inventory import save_parts_sync
from binner_mcp.mcp.validation import normalize_batch_input


def test_part_save_input_currency_default():
    """Verify PartSaveInput defaults currency to None and reflects in JSON schema."""
    item = PartSaveInput(part_number="RES-10K")
    assert item.currency is None

    schema = PartSaveInput.model_json_schema()
    currency_prop = schema["properties"]["currency"]
    assert currency_prop.get("default") is None

    # Normalization with unset fields excluded
    normalized, err = normalize_batch_input([item], "parts")
    assert err is None
    assert normalized is not None
    assert "currency" not in normalized[0]


def test_save_parts_update_without_currency_preserves_none():
    """Updating a part with currency=None without currency arg must not inject USD."""
    mock_proxy = MagicMock()
    mock_proxy._lock = MagicMock()
    mock_proxy._lock.__enter__ = MagicMock(return_value=None)
    mock_proxy._lock.__exit__ = MagicMock(return_value=None)

    existing_part = PartResponse(
        partId=101,
        partNumber="RES-10K",
        quantity=5,
        currency=None,
        cost=0.0,
    )
    mock_proxy.get_part_by_number.return_value = existing_part

    updated_return = PartResponse(
        partId=101,
        partNumber="RES-10K",
        quantity=10,
        currency=None,
        cost=0.0,
    )
    mock_proxy.update_part.return_value = updated_return

    res = save_parts_sync(
        proxy=mock_proxy,
        category_cache={},
        category_name_to_id={},
        parts=[{"part_number": "RES-10K", "quantity": 10}],
    )

    assert res["status"] == "success"
    assert res["updated_count"] == 1

    # Verify update_part payload had currency=None, NOT "USD"
    mock_proxy.update_part.assert_called_once()
    called_req = mock_proxy.update_part.call_args[0][0]
    assert called_req["currency"] is None

    # Verify diff does not report currency mutation
    changes = res["updated"][0]["changes"]
    assert "currency" not in changes
    assert changes["quantity"] == {"from": 5, "to": 10, "delta": 5}


def test_save_parts_update_without_currency_preserves_existing_currency():
    """Updating a part with currency='EUR' without currency arg must preserve 'EUR'."""
    mock_proxy = MagicMock()
    mock_proxy._lock = MagicMock()
    mock_proxy._lock.__enter__ = MagicMock(return_value=None)
    mock_proxy._lock.__exit__ = MagicMock(return_value=None)

    existing_part = PartResponse(
        partId=102,
        partNumber="CAP-10UF",
        quantity=20,
        currency="EUR",
        cost=0.5,
    )
    mock_proxy.get_part_by_number.return_value = existing_part

    updated_return = PartResponse(
        partId=102,
        partNumber="CAP-10UF",
        quantity=20,
        currency="EUR",
        cost=0.5,
        binNumber="A1-02",
    )
    mock_proxy.update_part.return_value = updated_return

    res = save_parts_sync(
        proxy=mock_proxy,
        category_cache={},
        category_name_to_id={},
        parts=[{"part_number": "CAP-10UF", "bin_number": "A1-02"}],
    )

    assert res["status"] == "success"
    assert res["updated_count"] == 1

    # Verify update_part received existing currency 'EUR'
    called_req = mock_proxy.update_part.call_args[0][0]
    assert called_req["currency"] == "EUR"

    # Verify diff does not report currency mutation
    changes = res["updated"][0]["changes"]
    assert "currency" not in changes
    assert changes["bin_number"] == {"to": "A1-02"}


def test_save_parts_update_with_explicit_currency():
    """Explicitly providing currency in update payload must update currency and report in diff."""
    mock_proxy = MagicMock()
    mock_proxy._lock = MagicMock()
    mock_proxy._lock.__enter__ = MagicMock(return_value=None)
    mock_proxy._lock.__exit__ = MagicMock(return_value=None)

    existing_part = PartResponse(
        partId=103,
        partNumber="IND-10UH",
        quantity=15,
        currency=None,
        cost=1.2,
    )
    mock_proxy.get_part_by_number.return_value = existing_part

    updated_return = PartResponse(
        partId=103,
        partNumber="IND-10UH",
        quantity=15,
        currency="USD",
        cost=1.2,
    )
    mock_proxy.update_part.return_value = updated_return

    res = save_parts_sync(
        proxy=mock_proxy,
        category_cache={},
        category_name_to_id={},
        parts=[{"part_number": "IND-10UH", "currency": "USD"}],
    )

    assert res["status"] == "success"
    assert res["updated_count"] == 1

    called_req = mock_proxy.update_part.call_args[0][0]
    assert called_req["currency"] == "USD"

    # Verify diff reports explicit currency mutation
    changes = res["updated"][0]["changes"]
    assert changes["currency"] == {"to": "USD"}


def test_save_parts_create_without_currency_passes_none():
    """Creating a new part without currency arg must pass currency=None and not report USD."""
    mock_proxy = MagicMock()
    mock_proxy._lock = MagicMock()
    mock_proxy._lock.__enter__ = MagicMock(return_value=None)
    mock_proxy._lock.__exit__ = MagicMock(return_value=None)

    # Component does not exist initially
    mock_proxy.get_part_by_number.return_value = None

    created_return = PartResponse(
        partId=201,
        partNumber="MCU-NEW",
        quantity=1,
        currency=None,
        cost=0.0,
    )
    mock_proxy.create_part.return_value = created_return

    res = save_parts_sync(
        proxy=mock_proxy,
        category_cache={},
        category_name_to_id={},
        parts=[{"part_number": "MCU-NEW", "quantity": 1}],
    )

    assert res["status"] == "success"
    assert res["created_count"] == 1

    # Verify create_part received currency=None
    called_req = mock_proxy.create_part.call_args[0][0]
    assert called_req["currency"] is None

    # Verify initial_values does not contain currency
    initial_values = res["created"][0]["initial_values"]
    assert "currency" not in initial_values


def test_save_parts_create_with_explicit_currency():
    """Creating a new part with explicit currency must pass the specified currency."""
    mock_proxy = MagicMock()
    mock_proxy._lock = MagicMock()
    mock_proxy._lock.__enter__ = MagicMock(return_value=None)
    mock_proxy._lock.__exit__ = MagicMock(return_value=None)

    mock_proxy.get_part_by_number.return_value = None

    created_return = PartResponse(
        partId=202,
        partNumber="CONN-USB",
        quantity=10,
        cost=0.75,
        currency="GBP",
    )
    mock_proxy.create_part.return_value = created_return

    res = save_parts_sync(
        proxy=mock_proxy,
        category_cache={},
        category_name_to_id={},
        parts=[{"part_number": "CONN-USB", "cost": 0.75, "currency": "GBP"}],
    )

    assert res["status"] == "success"
    assert res["created_count"] == 1

    called_req = mock_proxy.create_part.call_args[0][0]
    assert called_req["currency"] == "GBP"

    initial_values = res["created"][0]["initial_values"]
    assert initial_values["currency"] == "GBP"
