"""Integration tests for live Binner instance: authentication, identity, tokens, logs, and Swarm integration."""
import time
import pytest

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.models import BinnerExportArchive, PaginatedResponse, TestApiResponse


def test_live_ping(live_proxy: BinnerAPIProxy) -> None:
    assert live_proxy.ping() is True


def test_live_authentication_and_identity(live_proxy: BinnerAPIProxy) -> None:
    assert live_proxy.is_logged_in is True
    assert live_proxy.jwt_token is not None

    identity = live_proxy.get_identity()
    assert identity.user_id == 1
    assert identity.name == "Admin"
    assert identity.email_address == "admin"
    assert identity.is_admin is True


def test_live_token_refresh(live_proxy: BinnerAPIProxy) -> None:
    old_token = live_proxy.jwt_token
    assert "refreshToken" in live_proxy.session.cookies.get_dict()

    # Sleep briefly so Unix timestamp changes for rotated JWT iat
    time.sleep(1.1)
    success = live_proxy._handle_token_refresh()
    assert success is True
    assert live_proxy.jwt_token is not None
    assert live_proxy.jwt_token != old_token


def test_live_system_version_and_summary(live_proxy: BinnerAPIProxy) -> None:
    version_data = live_proxy.get_system_version()
    assert isinstance(version_data, dict)
    assert version_data.get("version") is not None
    assert version_data["version"] != "unknown"

    summary = live_proxy.get_summary()
    assert summary.unique_parts_count >= 0
    assert summary.parts_count >= 0
    assert summary.currency is not None


def test_live_export_and_cache_hydration(live_proxy: BinnerAPIProxy) -> None:
    archive = live_proxy.export_data(export_format="csv", populate_cache=True)
    assert isinstance(archive, BinnerExportArchive)
    assert archive.parts_csv is not None
    assert len(archive.parts_csv) > 0
    assert archive.part_types_csv is not None

    # Check that in-memory bidirectional cache was hydrated
    assert len(live_proxy._part_id_to_number) > 50
    assert len(live_proxy._part_number_to_id) > 50


def test_live_system_logs(live_proxy: BinnerAPIProxy) -> None:
    logs = live_proxy.get_system_logs(source="binner", page=1, results=10)
    assert isinstance(logs, PaginatedResponse)
    # Binner's AdminService.GetSystemLogsAsync intentionally returns totalItems = -1 for streaming logs
    assert logs.total_items == -1 or logs.total_items >= 0
    assert isinstance(logs.items, list)
    assert len(logs.items) > 0


def test_live_swarm_testapi(live_proxy: BinnerAPIProxy) -> None:
    result = live_proxy.test_swarm_integration()
    assert isinstance(result, TestApiResponse)
    assert result.api_name == "SwarmApi"
    assert result.success is True
