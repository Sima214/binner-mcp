"""Unit and mock tests for Binner Swarm client (src/binner_mcp/swarmer)."""

from unittest.mock import MagicMock, patch
import pytest
import requests

from binner_mcp.swarmer.client import SwarmClient
from binner_mcp.swarmer.exceptions import (
    SwarmAPIError,
    SwarmConnectionError,
    SwarmRateLimitError,
    SwarmTimeoutError,
)
from binner_mcp.swarmer.models import (
    Circuit,
    PartNumber,
    PartResults,
    Pinout,
    RateLimitInfo,
    SearchPartResponse,
    ServiceResult,
    StatusResponse,
)


def test_swarm_client_init_headers() -> None:
    """Verify headers with and without API key."""
    # Free tier / unauthenticated
    client_free = SwarmClient()
    assert "X-ApiKey" not in client_free.session.headers
    assert client_free.session.headers["User-Agent"] == "binner-mcp/swarmer"
    assert client_free.session.headers["Accept"] == "application/json"

    # Authenticated
    client_auth = SwarmClient(api_key="TEST_API_KEY")
    assert client_auth.session.headers.get("X-ApiKey") == "TEST_API_KEY"


def test_rate_limit_extraction() -> None:
    """Verify extraction and parsing of rate-limit headers."""
    client = SwarmClient()
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.headers = {
        "x-rate-limit-limit": "30d",
        "x-rate-limit-remaining": "4999",
        "x-rate-limit-reset": "2026-10-13T14:30:44.8176200Z",
    }

    info = client._extract_rate_limit_info(mock_resp)
    assert isinstance(info, RateLimitInfo)
    assert info.limit == "30d"
    assert info.remaining == 4999
    assert info.reset == "2026-10-13T14:30:44.8176200Z"
    assert client.last_rate_limit == info


def test_get_status_success() -> None:
    """Verify get_status parses StatusResponse properly."""
    client = SwarmClient()
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.headers = {
        "x-rate-limit-limit": "1d",
        "x-rate-limit-remaining": "450",
    }
    mock_resp.json.return_value = {
        "isUp": True,
        "isDatabaseUp": True,
        "lastCheckedUtc": "2026-09-13T14:30:45Z",
    }

    with patch.object(client.session, "request", return_value=mock_resp) as mock_req:
        status = client.get_status()
        assert isinstance(status, StatusResponse)
        assert status.is_up is True
        assert status.is_database_up is True
        assert status.last_checked_utc == "2026-09-13T14:30:45Z"
        mock_req.assert_called_once_with(
            "GET",
            "https://swarm.binner.io/Status",
            timeout=30.0,
        )


def test_search_parts_success() -> None:
    """Verify search_parts serializes SearchPartRequest and deserializes ServiceResult[SearchPartResponse]."""
    client = SwarmClient()
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.json.return_value = {
        "response": {
            "parts": [
                {
                    "partNumberId": 142,
                    "name": "NE555",
                    "description": "IC OSC SGL TIMER 100KHZ 8-SOIC",
                    "partType": "IC",
                    "circuits": [
                        {
                            "circuitId": 7,
                            "name": "555 Monostable Timer",
                            "description": "Monostable multivibrator",
                            "parts": [
                                {
                                    "circuitPartAssignmentId": 102,
                                    "partName": "NE555",
                                    "partType": "IC",
                                    "reference": "IC1",
                                }
                            ],
                        }
                    ],
                    "pinouts": [
                        {
                            "pinoutId": 12,
                            "partName": "NE555",
                            "packageName": "SOIC",
                            "pinCount": 8,
                            "pinoutDefinition": '{"pins": [{"pin": 1, "label": "GND"}]}',
                        }
                    ],
                    "partNumberManufacturers": [
                        {
                            "partNumberManufacturerId": 55,
                            "name": "NE555P",
                            "manufacturerName": "Texas Instruments",
                            "parametrics": [
                                {
                                    "name": "Frequency",
                                    "value": "100kHz",
                                    "valueNumber": 100000.0,
                                }
                            ],
                            "suppliers": [
                                {
                                    "supplierId": 1,
                                    "supplierName": "DigiKey",
                                    "supplierPartNumber": "296-1411-5-ND",
                                    "cost": 0.58,
                                    "currency": "USD",
                                    "quantityAvailable": 12500,
                                }
                            ],
                        }
                    ],
                }
            ]
        },
        "errors": [],
        "requiresAuthentication": False,
        "redirectUrl": None,
        "apiName": "SwarmApi",
    }

    with patch.object(client.session, "request", return_value=mock_resp) as mock_req:
        result = client.search_parts("NE555", record_count=5)
        assert isinstance(result, ServiceResult)
        assert result.is_success is True
        assert result.response is not None
        assert len(result.response.parts) == 1

        part = result.response.parts[0]
        assert isinstance(part, PartNumber)
        assert part.name == "NE555"
        assert len(part.circuits) == 1
        assert isinstance(part.circuits[0], Circuit)
        assert len(part.pinouts) == 1
        assert isinstance(part.pinouts[0], Pinout)
        assert part.pinouts[0].pin_count == 8

        mfg = part.part_number_manufacturers[0]
        assert mfg.manufacturer_name == "Texas Instruments"
        assert mfg.suppliers[0].supplier_name == "DigiKey"
        assert mfg.suppliers[0].cost == 0.58
        assert mfg.parametrics[0].value == "100kHz"

        mock_req.assert_called_once_with(
            "POST",
            "https://swarm.binner.io/Part/search",
            json={"partNumber": "NE555", "recordCount": 5},
            timeout=30.0,
        )


def test_get_part_info_success() -> None:
    """Verify get_part_info deserializes ServiceResult[PartResults]."""
    client = SwarmClient()
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.json.return_value = {
        "response": {
            "parts": [],
            "productImages": [],
            "datasheets": [],
            "pinouts": [],
            "circuits": [],
        },
        "errors": [],
        "requiresAuthentication": False,
        "redirectUrl": None,
        "apiName": None,
    }

    with patch.object(client.session, "request", return_value=mock_resp):
        res = client.get_part_info("2N2222")
        assert isinstance(res, ServiceResult)
        assert res.is_success is True
        assert isinstance(res.response, PartResults)


def test_rate_limit_error_raised() -> None:
    """Verify HTTP 429 raises SwarmRateLimitError with header details."""
    client = SwarmClient()
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 429
    mock_resp.text = "Too Many Requests"
    mock_resp.headers = {
        "x-rate-limit-limit": "1d",
        "x-rate-limit-remaining": "0",
        "x-rate-limit-reset": "2026-09-14T00:00:00Z",
    }

    with patch.object(client.session, "request", return_value=mock_resp):
        with pytest.raises(SwarmRateLimitError) as exc_info:
            client.get_status()
        err = exc_info.value
        assert err.limit == "1d"
        assert err.remaining == 0
        assert err.reset == "2026-09-14T00:00:00Z"


def test_timeout_error_raised() -> None:
    """Verify requests.exceptions.Timeout maps to SwarmTimeoutError."""
    client = SwarmClient(timeout=5.0)
    with patch.object(
        client.session,
        "request",
        side_effect=requests.exceptions.Timeout("Read timeout"),
    ):
        with pytest.raises(SwarmTimeoutError) as exc_info:
            client.search_parts("NE555")
        assert "timed out" in str(exc_info.value)


def test_connection_error_raised() -> None:
    """Verify requests.exceptions.ConnectionError maps to SwarmConnectionError."""
    client = SwarmClient()
    with patch.object(
        client.session,
        "request",
        side_effect=requests.exceptions.ConnectionError("DNS failure"),
    ):
        with pytest.raises(SwarmConnectionError) as exc_info:
            client.get_status()
        assert "Failed to connect" in str(exc_info.value)


def test_api_error_raised() -> None:
    """Verify HTTP 500 raises SwarmAPIError."""
    client = SwarmClient()
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    mock_resp.headers = {}

    with patch.object(client.session, "request", return_value=mock_resp):
        with pytest.raises(SwarmAPIError) as exc_info:
            client.get_part_info("NE555P")
        assert exc_info.value.status_code == 500
        assert "Internal Server Error" in exc_info.value.response_text
