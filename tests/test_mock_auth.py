"""Unit tests for authentication, sessions, caching, and export in BinnerAPIProxy."""
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import zipfile

import pytest
import requests

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import (
    BinnerAPIError,
    BinnerAuthError,
    BinnerConnectionError,
)
from binner_mcp.api.models import (
    BinnerExportArchive,
    CreatePartRequest,
    PartResponse,
)


def test_ping_success(proxy: BinnerAPIProxy) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '"pong"'

    with patch.object(proxy.session, "get", return_value=mock_resp) as mock_get:
        assert proxy.ping() is True
        mock_get.assert_called_once_with("http://mock-binner:8090/api/ping", timeout=2.0)


def test_ping_failure(proxy: BinnerAPIProxy) -> None:
    with patch.object(proxy.session, "get", side_effect=requests.exceptions.ConnectionError("Failed")):
        assert proxy.ping() is False


def test_login_success(proxy: BinnerAPIProxy) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "id": 1,
        "name": "Admin",
        "isAdmin": True,
        "isAuthenticated": True,
        "jwtToken": "mock_jwt_token_123",
    }

    with patch.object(proxy.session, "post", return_value=mock_resp) as mock_post:
        tokens = proxy.login()
        assert tokens.jwt_token == "mock_jwt_token_123"
        assert proxy.is_logged_in is True
        assert proxy.jwt_token == "mock_jwt_token_123"
        assert proxy.session.headers["Authorization"] == "Bearer mock_jwt_token_123"
        mock_post.assert_called_once()


def test_login_invalid_credentials(proxy: BinnerAPIProxy) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.ok = False
    mock_resp.text = "Unauthorized"

    with patch.object(proxy.session, "post", return_value=mock_resp):
        with pytest.raises(BinnerAuthError) as exc_info:
            proxy.login()
        assert "Invalid credentials" in str(exc_info.value)
        assert proxy.is_logged_in is False


def test_login_connection_error(proxy: BinnerAPIProxy) -> None:
    with patch.object(proxy.session, "post", side_effect=requests.exceptions.ConnectionError("Refused")):
        with pytest.raises(BinnerConnectionError) as exc_info:
            proxy.login()
        assert "Cannot connect to Binner" in str(exc_info.value)
        assert proxy.is_logged_in is False


def test_logout(proxy: BinnerAPIProxy) -> None:
    proxy.jwt_token = "some_token"
    proxy._is_logged_in = True
    proxy.session.headers["Authorization"] = "Bearer some_token"
    proxy.session.cookies.set("refreshToken", "some_cookie")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch.object(proxy.session, "post", return_value=mock_resp):
        assert proxy.logout() is True
        assert proxy.is_logged_in is False
        assert proxy.jwt_token is None
        assert "Authorization" not in proxy.session.headers
        assert len(proxy.session.cookies) == 0


def test_auto_token_refresh_on_401(proxy: BinnerAPIProxy) -> None:
    """Verify that a 401 on an API request triggers refresh-token and retries successfully."""
    proxy._is_logged_in = True
    proxy.jwt_token = "old_token"
    proxy.session.headers["Authorization"] = "Bearer old_token"
    proxy.session.cookies.set("refreshToken", "mock_refresh_cookie")

    # 1st call to /api/part/summary: returns 401
    resp_401 = MagicMock()
    resp_401.status_code = 401
    resp_401.ok = False
    resp_401.text = "Token expired"

    # Call to /api/authentication/refresh-token: returns 200 with new token
    resp_refresh = MagicMock()
    resp_refresh.status_code = 200
    resp_refresh.ok = True
    resp_refresh.json.return_value = {
        "isAuthenticated": True,
        "jwtToken": "new_refreshed_token_456",
    }

    # 2nd call to /api/part/summary (retry): returns 200
    resp_retry = MagicMock()
    resp_retry.status_code = 200
    resp_retry.ok = True
    resp_retry.json.return_value = {
        "uniquePartsCount": 5,
        "partsCount": 100,
        "partsCost": 25.50,
        "lowStockCount": 1,
        "projectsCount": 2,
        "currency": "EUR",
    }

    def mock_request(method: str, url: str, **kwargs):
        if url.endswith("/api/authentication/refresh-token"):
            return resp_refresh
        if url.endswith("/api/part/summary"):
            auth_header = proxy.session.headers.get("Authorization")
            if auth_header == "Bearer new_refreshed_token_456":
                return resp_retry
            return resp_401
        raise ValueError(f"Unexpected URL: {url}")

    with patch.object(proxy.session, "request", side_effect=mock_request):
        summary = proxy.get_summary()
        assert summary.unique_parts_count == 5
        assert summary.parts_count == 100
        assert proxy.jwt_token == "new_refreshed_token_456"
        assert proxy.session.headers["Authorization"] == "Bearer new_refreshed_token_456"


def test_auto_token_refresh_on_user_context_unauthorized_500(proxy: BinnerAPIProxy) -> None:
    """Verify that a 500 containing UserContextUnauthorizedException triggers refresh-token and retries."""
    proxy._is_logged_in = True
    proxy.jwt_token = "expired_token"
    proxy.session.headers["Authorization"] = "Bearer expired_token"
    proxy.session.cookies.set("refreshToken", "mock_refresh_cookie")

    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.ok = False
    resp_500.text = "Unhandled Error! Binner.Global.Common.UserContextUnauthorizedException: Action requires valid user context.. Caller: GetProjectAsync:2035"

    resp_refresh = MagicMock()
    resp_refresh.status_code = 200
    resp_refresh.ok = True
    resp_refresh.json.return_value = {
        "isAuthenticated": True,
        "jwtToken": "refreshed_token_after_500",
    }

    resp_retry = MagicMock()
    resp_retry.status_code = 200
    resp_retry.ok = True
    resp_retry.json.return_value = {
        "projectId": 81,
        "name": "QA_TEST_PROJECT",
    }

    def mock_request(method: str, url: str, **kwargs):
        if url.endswith("/api/authentication/refresh-token"):
            return resp_refresh
        if "/api/project" in url:
            auth_header = proxy.session.headers.get("Authorization")
            if auth_header == "Bearer refreshed_token_after_500":
                return resp_retry
            return resp_500
        raise ValueError(f"Unexpected URL: {url}")

    with patch.object(proxy.session, "request", side_effect=mock_request):
        project = proxy.get_project(project_id=81)
        assert project is not None
        assert project.project_id == 81
        assert proxy.jwt_token == "refreshed_token_after_500"
        assert proxy.session.headers["Authorization"] == "Bearer refreshed_token_after_500"


def test_token_refresh_fallback_to_login(proxy: BinnerAPIProxy) -> None:
    """When refresh cookie is absent, proxy falls back to explicit login credentials."""
    proxy._is_logged_in = True
    proxy.jwt_token = "expired_token"

    resp_401 = MagicMock()
    resp_401.status_code = 401
    resp_401.ok = False
    resp_401.text = "Token expired"

    resp_login = MagicMock()
    resp_login.status_code = 200
    resp_login.ok = True
    resp_login.json.return_value = {
        "isAuthenticated": True,
        "jwtToken": "relogin_jwt_token_789",
    }

    resp_retry = MagicMock()
    resp_retry.status_code = 200
    resp_retry.ok = True
    resp_retry.json.return_value = {
        "uniquePartsCount": 1,
        "partsCount": 1,
        "partsCost": 1.0,
        "lowStockCount": 0,
        "projectsCount": 0,
        "currency": "USD",
    }

    with patch.object(proxy.session, "post", return_value=resp_login) as mock_post:
        with patch.object(proxy.session, "request", side_effect=[resp_401, resp_retry]):
            summary = proxy.get_summary()
            assert summary.parts_count == 1
            assert proxy.jwt_token == "relogin_jwt_token_789"
            mock_post.assert_called_once()


def test_not_found_error_handling(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    resp_404 = MagicMock()
    resp_404.status_code = 404
    resp_404.ok = False
    resp_404.text = "Part not found"

    with patch.object(proxy.session, "request", return_value=resp_404):
        assert proxy.get_part_by_number("NONEXISTENT") is None
        assert proxy.search_parts(keywords="NONEXISTENT", exact_match=True) is None
        assert proxy.search_parts(keywords="NONEXISTENT", exact_match=False) == []


def test_server_error_handling(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.ok = False
    resp_500.text = "Internal Server Error"

    with patch.object(proxy.session, "request", return_value=resp_500):
        with pytest.raises(BinnerAPIError) as exc_info:
            proxy.get_summary()
        assert exc_info.value.status_code == 500


def test_models_serialization() -> None:
    req = CreatePartRequest(
        partNumber="RES-10K-0805",
        quantity=50,
        cost=0.05,
        location="Lab Shelf 1",
        binNumber="A1-02",
        partTypeId="Resistors",
    )
    dumped = req.model_dump(by_alias=True)
    assert dumped["partNumber"] == "RES-10K-0805"
    assert dumped["quantity"] == 50
    assert dumped["binNumber"] == "A1-02"

    part_resp = PartResponse.model_validate({
        "partId": 42,
        "partNumber": "RES-10K-0805",
        "quantity": 50,
        "cost": 0.05,
        "binNumber": "A1-02",
        "partTypeId": 2,
        "partType": "Resistors",
    })
    assert part_resp.part_id == 42
    assert part_resp.part_number == "RES-10K-0805"
    assert part_resp.part_type == "Resistors"


def test_models_json_serialization() -> None:
    req = CreatePartRequest(
        partNumber="RES-10K-0805",
        quantity=50,
        cost=0.05,
        location="Lab Shelf 1",
        binNumber="A1-02",
        partTypeId="Resistors",
    )
    part_resp = PartResponse.model_validate({
        "partId": 42,
        "partNumber": "RES-10K-0805",
        "quantity": 50,
        "cost": 0.05,
        "binNumber": "A1-02",
        "partTypeId": 2,
        "partType": "Resistors",
    })

    # Direct json.dumps compatibility
    json_single = json.dumps(part_resp)
    assert '"partNumber": "RES-10K-0805"' in json_single or '"partNumber":"RES-10K-0805"' in json_single
    assert '"partId": 42' in json_single or '"partId":42' in json_single

    # Iterables and nested structures in json.dumps
    json_list = json.dumps([part_resp, req])
    assert json_list.startswith("[") and json_list.endswith("]")

    json_dict = json.dumps({"part": part_resp})
    assert json_dict.startswith("{") and json_dict.endswith("}")

    # Model convenience methods
    assert "RES-10K-0805" in part_resp.to_json()
    assert part_resp.to_dict()["partNumber"] == "RES-10K-0805"




def test_cache_lifecycle_and_lookup(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True

    # 1. Manual caching
    proxy._cache_part(101, "CAP-100NF")
    assert proxy._part_id_to_number[101] == "CAP-100NF"
    assert proxy._part_number_to_id["CAP-100NF"] == 101

    # 2. Fast resolution from cache
    with patch.object(proxy, "get_part_by_number") as mock_lookup:
        pid, pnum = proxy._resolve_part_identity(part_id=None, part_number="CAP-100NF")
        assert pid == 101
        assert pnum == "CAP-100NF"
        mock_lookup.assert_not_called()

        pid2, pnum2 = proxy._resolve_part_identity(part_id=101, part_number=None)
        assert pid2 == 101
        assert pnum2 == "CAP-100NF"

    # 3. Eviction on uncache
    proxy._uncache_part(101)
    assert 101 not in proxy._part_id_to_number
    assert "CAP-100NF" not in proxy._part_number_to_id


def test_resolve_part_identity_with_get_part_number_by_id(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True

    with patch.object(proxy, "get_part_number_by_id", return_value="TARGET-PART") as mock_lookup:
        pid, pnum = proxy._resolve_part_identity(part_id=999, part_number=None)
        assert pid == 999
        assert pnum == "TARGET-PART"
        mock_lookup.assert_called_once_with(999)

    with patch.object(proxy, "get_part_number_by_id") as mock_lookup:
        pid, pnum = proxy._resolve_part_identity(part_id=123, part_number="DIRECT-PART")
        assert pid == 123
        assert pnum == "DIRECT-PART"
        mock_lookup.assert_not_called()
        assert proxy._part_id_to_number[123] == "DIRECT-PART"


def test_lock_serialization(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {"id": 1}

    with patch.object(proxy.session, "request", return_value=mock_resp):
        assert proxy._lock.acquire(blocking=False)
        proxy._lock.release()
        resp = proxy._execute_request("GET", "/api/system/info")
        assert resp.status_code == 200


def test_export_data_and_cache_hydration(proxy: BinnerAPIProxy, tmp_path: Path) -> None:
    proxy._is_logged_in = True

    zip_buf = io.BytesIO()
    parts_csv_data = (
        "#PartId,ShortId,Quantity,LowStockThreshold,Cost,Currency,PartNumber,Description\n"
        "501,SH-501,10,0,0.1,USD,IC-NE555,Timer IC\n"
        "502,SH-502,25,5,0.25,USD,IC-LM358,OpAmp IC\n"
    )
    part_types_csv_data = "#PartTypeId,Name\n1,ICs\n"

    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("Parts.csv", parts_csv_data)
        zf.writestr("PartTypes.csv", part_types_csv_data)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.content = zip_buf.getvalue()

    with patch.object(proxy, "_execute_request", return_value=mock_resp):
        archive = proxy.export_data(populate_cache=True)
        assert isinstance(archive, BinnerExportArchive)
        assert "Parts.csv" in archive.files
        assert "PartTypes.csv" in archive.files
        assert archive.parts_csv == parts_csv_data
        assert archive.part_types_csv == part_types_csv_data

        assert proxy._part_id_to_number[501] == "IC-NE555"
        assert proxy._part_number_to_id["IC-NE555"] == 501
        assert proxy._part_id_to_number[502] == "IC-LM358"
        assert proxy._part_number_to_id["IC-LM358"] == 502

        saved_files = archive.save_to_disk(tmp_path)
        assert len(saved_files) == 2
        assert (tmp_path / "Parts.csv").exists()
        assert (tmp_path / "PartTypes.csv").exists()


def test_import_data_file_mock(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    proxy.jwt_token = "valid_jwt_token"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {"success": True, "imported": 5}

    with patch.object(proxy.session, "post", return_value=mock_resp) as mock_post:
        res = proxy.import_data_file("Parts.csv", "PartId,PartNumber\n1,TEST-01")
        assert res == {"success": True, "imported": 5}
        mock_post.assert_called_once()
