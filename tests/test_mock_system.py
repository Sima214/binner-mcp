"""Unit tests for system monitoring, versioning, logs, and Swarm integration in BinnerAPIProxy."""
from unittest.mock import MagicMock, patch

import pytest

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.models import (
    DashboardSummaryResponse,
    PaginatedResponse,
    SystemLogEntry,
    TestApiResponse,
)


def test_get_system_version_from_ping_header(proxy: BinnerAPIProxy) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"X-Version": "2.6.25"}

    with patch.object(proxy.session, "get", return_value=mock_resp) as mock_get:
        ver = proxy.get_system_version()
        assert ver == {"version": "2.6.25"}
        mock_get.assert_called_once_with("http://mock-binner:8090/api/ping", timeout=2.0)


def test_get_summary(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "uniquePartsCount": 150,
        "partsCount": 3200,
        "partsCost": 450.25,
        "lowStockCount": 12,
        "projectsCount": 4,
        "currency": "USD",
    }

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        summary = proxy.get_summary()
        assert isinstance(summary, DashboardSummaryResponse)
        assert summary.unique_parts_count == 150
        assert summary.parts_count == 3200
        assert summary.low_stock_count == 12
        mock_exec.assert_called_once_with("GET", "/api/part/summary")


def test_get_system_logs(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "totalItems": 2,
        "pageSize": 50,
        "totalPages": 1,
        "pageNumber": 1,
        "items": [
            {"logEntry": "[2026-09-13 10:00:00.123] [Binner.Web] Application started"},
            {"logEntry": "[2026-09-13 10:00:01.456] [Binner.Web] Database migrated successfully"},
        ],
    }

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        logs = proxy.get_system_logs(source="binner", page=1, results=50)
        assert isinstance(logs, PaginatedResponse)
        assert logs.total_items == 2
        assert len(logs.items) == 2
        assert "Application started" in logs.items[0].log_entry
        mock_exec.assert_called_once_with(
            "GET",
            "/api/system/logs",
            params={"by": "binner", "page": 1, "results": 50},
        )


def test_get_system_logs_invalid_source(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    with pytest.raises(ValueError) as exc_info:
        proxy.get_system_logs(source="invalid_source")
    assert "Invalid log source 'invalid_source'" in str(exc_info.value)


def test_swarm_testapi(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "apiName": "SwarmApi",
        "success": True,
        "message": None,
    }

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        result = proxy.test_swarm_integration()
        assert isinstance(result, TestApiResponse)
        assert result.api_name == "SwarmApi"
        assert result.success is True
        mock_exec.assert_called_once_with(
            "PUT",
            "/api/settings/testapi",
            json={
                "name": "swarm",
                "configuration": [
                    {"key": "Enabled", "value": "true"},
                    {"key": "ApiUrl", "value": "https://swarm.binner.io"},
                ],
            },
        )
