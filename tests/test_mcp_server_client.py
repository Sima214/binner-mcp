"""In-memory tests for BinnerMCPServer using the official MCP Python SDK Client.

Reference: https://py.sdk.modelcontextprotocol.io/get-started/testing/
"""

import asyncio
import json
import threading
from unittest.mock import MagicMock
import pytest
import requests
from mcp import Client

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import BinnerAuthError, BinnerConnectionError
from binner_mcp.api.models import (
    DashboardSummaryResponse,
    PaginatedResponse,
    PartResponse,
    PartStoredFilesResponse,
    PartTypeResponse,
    ProjectResponse,
    UserContext,
)
from binner_mcp.config import BinnerConfig
from binner_mcp.mcp.server import BinnerMCPServer
from binner_mcp.swarmer.client import SwarmClient
from binner_mcp.swarmer.models import (
    PartNumber,
    Pinout,
    SearchPartResponse,
    ServiceResult,
    StatusResponse,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_proxy() -> MagicMock:
    proxy = MagicMock()
    proxy.base_url = "http://localhost:8090"
    proxy.is_logged_in = True
    proxy.ping.return_value = True
    proxy.get_system_version.return_value = {"version": "2.6.25"}
    proxy.get_identity.return_value = UserContext(
        userId=1,
        name="Admin",
        emailAddress="admin",
        isAdmin=True,
    )
    proxy.get_summary.return_value = DashboardSummaryResponse(
        uniquePartsCount=150,
        partsCount=1200,
        partsCost=450.0,
        lowStockCount=3,
        projectsCount=2,
        currency="USD",
    )
    proxy.timeout = 10.0
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '"pong"'
    mock_resp.headers = {"X-Version": "2.6.25"}
    proxy.session.get.return_value = mock_resp
    proxy._lock = threading.RLock()
    return proxy


@pytest.fixture
def mock_swarm() -> MagicMock:
    swarm = MagicMock(spec=SwarmClient)
    swarm.get_status.return_value = StatusResponse(
        isUp=True,
        isDatabaseUp=True,
        lastCheckedUtc="2026-09-22T12:00:00Z",
    )
    return swarm


# --- System Status Tests ---

@pytest.mark.anyio
async def test_get_system_status_success(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        tools_result = await client.list_tools()
        tool_names = [t.name for t in tools_result.tools]
        assert "get_system_status" in tool_names

        result = await client.call_tool("get_system_status", {"check_cloud": False})
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "connected"
        assert data["binner_version"] == "2.6.25"
        assert data["user"]["name"] == "Admin"
        assert data["inventory"]["unique_parts"] == 150
        assert data["inventory"]["total_quantity"] == 1200
        assert data["inventory"]["valuation"] == 450.0
        assert "swarm_cloud" not in data


@pytest.mark.anyio
async def test_get_system_status_with_cloud(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool("get_system_status", {"check_cloud": True})
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "connected"
        assert "swarm_cloud" in data
        assert data["swarm_cloud"]["status"] == "online"
        assert data["swarm_cloud"]["database_status"] == "online"


@pytest.mark.anyio
async def test_get_system_status_offline(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    import requests
    mock_proxy.session.get.side_effect = requests.exceptions.ConnectionError("Connection refused")
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool("get_system_status", {"check_cloud": False})
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "offline"
        assert "detail" in data
        assert "Connection refused" in data["detail"] or "offline" in data["detail"] or "Unhealthy" in data["detail"]


@pytest.mark.anyio
async def test_get_system_status_auth_error(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    mock_proxy.is_logged_in = False
    mock_proxy.login.side_effect = BinnerAuthError("Invalid credentials")
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool("get_system_status", {"check_cloud": False})
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "connected"
        assert "auth_error" in data
        assert "Invalid credentials" in data["auth_error"]


@pytest.mark.anyio
async def test_get_system_status_concurrency_lock(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        tasks = [
            client.call_tool("get_system_status", {"check_cloud": False})
            for _ in range(10)
        ]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        for r in results:
            assert not r.is_error
            assert r.structured_content["result"]["status"] == "connected"


# --- Protocol Discovery Tests ---

@pytest.mark.anyio
async def test_tool_and_resource_and_prompt_discovery(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        # Tools
        tools_resp = await client.list_tools()
        registered_tools = {t.name for t in tools_resp.tools}
        expected_tools = {
            "get_system_status",
            "list_parts",
            "get_parts",
            "save_parts",
            "delete_parts",
            "list_projects",
            "get_projects",
            "save_projects",
            "delete_projects",
            "consume_project_bom",
            "list_part_types",
            "save_part_types",
            "delete_part_types",
            "manage_bom_parts",
            "lookup_cloud_parts",
        }
        assert expected_tools.issubset(registered_tools)

        # Resources & Templates
        resources_resp = await client.list_resources()
        registered_uris = {r.uri for r in resources_resp.resources}
        assert "binner://status" in registered_uris
        assert "binner://categories" in registered_uris
        assert "binner://low-stock" in registered_uris

        templates_resp = await client.list_resource_templates()
        registered_templates = {t.uri_template for t in templates_resp.resource_templates}
        assert "binner://projects/{project_id}/bom" in registered_templates
        assert "binner://parts/{identifier}" in registered_templates


# --- Batched Inventory Discovery & Inspection Tests ---

@pytest.mark.anyio
async def test_list_parts_default_minimal(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    mock_proxy.list_parts.return_value = PaginatedResponse[PartResponse](
        totalItems=2,
        pageSize=20,
        totalPages=1,
        pageNumber=1,
        items=[
            PartResponse(partId=1, partNumber="NE555P", quantity=10, location="Shelf A", binNumber="B1"),
            PartResponse(partId=2, partNumber="LM358N", quantity=25, location="Shelf B", binNumber="B2"),
        ],
    )
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool("list_parts", {})
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["total_items"] == 2
        parts = data["parts"]
        assert len(parts) == 2
        # Verify minimal payload: only id and part_number
        assert parts[0] == {"id": 1, "part_number": "NE555P"}
        assert parts[1] == {"id": 2, "part_number": "LM358N"}


@pytest.mark.anyio
async def test_list_parts_field_expansion(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    mock_proxy.list_parts.return_value = PaginatedResponse[PartResponse](
        totalItems=1,
        pageSize=20,
        totalPages=1,
        pageNumber=1,
        items=[
            PartResponse(partId=10, partNumber="ESP32-WROOM-32", quantity=15, location="Drawer 1", binNumber="C4"),
        ],
    )
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool(
            "list_parts",
            {"fields": ["quantity", "location", "bin_number"]},
        )
        assert not result.is_error
        data = result.structured_content["result"]

        part = data["parts"][0]
        assert part["id"] == 10
        assert part["part_number"] == "ESP32-WROOM-32"
        assert part["quantity"] == 15
        assert part["location"] == "Drawer 1"
        assert part["bin_number"] == "C4"


@pytest.mark.anyio
async def test_get_parts_batch(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    # Setup category cache
    part1 = PartStoredFilesResponse(
        partId=42,
        partNumber="NE555P",
        quantity=15,
        partTypeId=101,
        binNumber="A1-04",
        packageType="DIP-8",
    )
    part2 = PartResponse(
        partId=108,
        partNumber="LM358N",
        quantity=35,
        partTypeId=102,
        binNumber="B2-15",
    )

    mock_proxy.get_part_by_number.side_effect = lambda pn: part1 if pn == "NE555P" else (part2 if pn == "LM358N" else None)
    mock_proxy.get_part_number_by_id.side_effect = lambda pid: "LM358N" if pid == 108 else None
    mock_proxy.get_part_by_id.side_effect = lambda pid: part2 if pid == 108 else None

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)
    server._category_cache[101] = "Semiconductors::Timers"
    server._category_cache[102] = "Semiconductors::OpAmps"

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_parts",
            {"part_numbers": ["NE555P", "MISSING-1"], "part_ids": [108, 999]},
        )
        assert not result.is_error
        data = result.structured_content["result"]

        parts = data["parts"]
        assert len(parts) == 2
        p1 = next(p for p in parts if p["part_number"] == "NE555P")
        assert p1["id"] == 42
        assert p1["part_type"] == "Semiconductors::Timers"
        assert p1["package_type"] == "DIP-8"

        p2 = next(p for p in parts if p["part_number"] == "LM358N")
        assert p2["id"] == 108
        assert p2["part_type"] == "Semiconductors::OpAmps"

        assert "MISSING-1" in data["not_found"]
        assert "999" in data["not_found"]


@pytest.mark.anyio
async def test_get_parts_with_field_projection(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    part1 = PartStoredFilesResponse(
        partId=42,
        partNumber="NE555P",
        quantity=15,
        partTypeId=101,
        binNumber="A1-04",
        packageType="DIP-8",
        location="Drawer 1",
    )
    mock_proxy.get_part_by_number.side_effect = lambda pn: part1 if pn == "NE555P" else None
    mock_proxy.get_part_number_by_id.return_value = None
    mock_proxy.get_part_by_id.return_value = None

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)
    server._category_cache[101] = "Semiconductors::Timers"

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_parts",
            {"part_numbers": ["NE555P"], "fields": ["quantity", "location"]},
        )
        assert not result.is_error
        data = result.structured_content["result"]
        parts = data["parts"]
        assert len(parts) == 1
        p = parts[0]
        assert p["id"] == 42
        assert p["part_number"] == "NE555P"
        assert p["quantity"] == 15
        assert p["location"] == "Drawer 1"
        assert "package_type" not in p
        assert "bin_number" not in p
        assert "part_type" not in p


# --- Zero-Side-Effects Failure & Mutation Tests ---

@pytest.mark.anyio
async def test_save_parts_batch_upsert(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    existing_lm358 = PartResponse(
        partId=108,
        partNumber="LM358N",
        quantity=20,
        binNumber="A1-02",
    )
    created_stm32 = PartResponse(
        partId=142,
        partNumber="STM32F401RET6",
        quantity=5,
        binNumber="C2-10",
        location="MCU Drawer",
    )
    updated_lm358 = PartResponse(
        partId=108,
        partNumber="LM358N",
        quantity=35,
        binNumber="B2-15",
    )

    mock_proxy.get_part_by_number.side_effect = lambda pn: existing_lm358 if pn == "LM358N" else None
    mock_proxy.get_part_by_id.side_effect = lambda pid: existing_lm358 if pid == 108 else None
    mock_proxy.create_part.return_value = created_stm32
    mock_proxy.update_part.return_value = updated_lm358

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool(
            "save_parts",
            {
                "parts": [
                    {"part_number": "STM32F401RET6", "quantity": 5, "bin_number": "C2-10", "location": "MCU Drawer"},
                    {"part_number": "LM358N", "quantity": 35, "bin_number": "B2-15"},
                ]
            },
        )
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "success"
        assert data["created_count"] == 1
        assert data["updated_count"] == 1
        assert data["created"][0]["part_number"] == "STM32F401RET6"

        updated = data["updated"][0]
        assert updated["part_number"] == "LM358N"
        assert updated["changes"]["quantity"]["from"] == 20
        assert updated["changes"]["quantity"]["to"] == 35
        assert updated["changes"]["quantity"]["delta"] == 15
        assert updated["changes"]["bin_number"]["from"] == "A1-02"
        assert updated["changes"]["bin_number"]["to"] == "B2-15"


@pytest.mark.anyio
async def test_save_parts_fail_has_no_side_effects(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    """If ANY item in batch is invalid, reject immediately. ZERO DB writes."""
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        # Part 1 is valid, but Part 2 has negative quantity
        result = await client.call_tool(
            "save_parts",
            {
                "parts": [
                    {"part_number": "VALID-PART-1", "quantity": 10},
                    {"part_number": "INVALID-PART-2", "quantity": -5},
                ]
            },
        )
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "error"
        assert data["error"] == "Validation failed"
        assert any("quantity" in d for d in data["details"])

        # Invariant check: ZERO calls made to create_part or update_part
        mock_proxy.create_part.assert_not_called()
        mock_proxy.update_part.assert_not_called()


@pytest.mark.anyio
async def test_delete_parts_batch(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    p1 = PartResponse(partId=10, partNumber="P-10")
    p2 = PartResponse(partId=20, partNumber="P-20")

    mock_proxy.get_part_by_number.side_effect = lambda pn: p1 if pn == "P-10" else None
    mock_proxy.get_part_by_id.side_effect = lambda pid: p2 if pid == 20 else None
    mock_proxy.delete_part.return_value = True

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool(
            "delete_parts",
            {"part_numbers": ["P-10"], "part_ids": [20]},
        )
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "success"
        assert len(data["deleted"]) == 2
        assert mock_proxy.delete_part.call_count == 2


@pytest.mark.anyio
async def test_delete_parts_fail_has_no_side_effects(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    """If ANY requested part is missing, abort immediately with zero deletions."""
    p1 = PartResponse(partId=10, partNumber="P-10")
    mock_proxy.get_part_by_number.side_effect = lambda pn: p1 if pn == "P-10" else None
    mock_proxy.get_part_by_id.return_value = None

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool(
            "delete_parts",
            {"part_numbers": ["P-10", "NON-EXISTENT-PART"]},
        )
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "error"
        assert data["error"] == "Validation failed"
        assert any("NON-EXISTENT-PART" in d for d in data["details"])

        # Zero parts deleted
        mock_proxy.delete_part.assert_not_called()


# --- Projects & BOM Tests ---

@pytest.mark.anyio
async def test_consume_project_bom_shortage_has_no_side_effects(
    mock_proxy: MagicMock, mock_swarm: MagicMock
) -> None:
    """When a shortage is detected on 1 line item, zero stock deductions occur."""
    proj = ProjectResponse(projectId=1, name="Sensor Node")
    mock_proxy.get_project.return_value = proj
    mock_proxy.get_bom.return_value = {
        "projectId": 1,
        "parts": [
            {"partNumber": "MCU-1", "quantity": 1, "part": {"quantity": 10}},
            {"partNumber": "CAP-10UF", "quantity": 5, "part": {"quantity": 2}},  # Shortage: requires 5, has 2
        ],
    }
    mock_proxy.get_part_by_number.side_effect = lambda pn: (
        PartResponse(partId=101, partNumber="MCU-1", quantity=10)
        if pn == "MCU-1"
        else PartResponse(partId=102, partNumber="CAP-10UF", quantity=2)
    )

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool(
            "consume_project_bom",
            {"project_id": 1, "build_quantity": 1},
        )
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "error"
        assert "shortages" in data
        assert len(data["shortages"]) == 1
        assert data["shortages"][0]["part_number"] == "CAP-10UF"
        assert data["shortages"][0]["shortage"] == 3

        # Invariant: Zero quantity deductions executed
        mock_proxy.update_quantity.assert_not_called()


@pytest.mark.anyio
async def test_consume_project_bom_success(
    mock_proxy: MagicMock, mock_swarm: MagicMock
) -> None:
    proj = ProjectResponse(projectId=1, name="Sensor Node")
    mock_proxy.get_project.return_value = proj
    mock_proxy.get_bom.return_value = {
        "projectId": 1,
        "parts": [
            {"partNumber": "MCU-1", "quantity": 1, "part": {"quantity": 10}},
        ],
    }
    mock_proxy.get_part_by_number.return_value = PartResponse(partId=101, partNumber="MCU-1", quantity=10)
    mock_proxy.update_quantity.return_value = PartResponse(partId=101, partNumber="MCU-1", quantity=8)

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool(
            "consume_project_bom",
            {"project_id": 1, "build_quantity": 2},
        )
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "success"
        assert data["build_quantity"] == 2
        assert len(data["deductions"]) == 1
        assert data["deductions"][0]["deducted"] == 2
        assert data["deductions"][0]["remaining_stock"] == 8

        mock_proxy.update_quantity.assert_called_once_with(
            part_id=101,
            part_number="MCU-1",
            quantity=-2,
            reason="Consumed for 2 units of project Sensor Node",
        )


@pytest.mark.anyio
async def test_manage_bom_parts_fail_has_no_side_effects(
    mock_proxy: MagicMock, mock_swarm: MagicMock
) -> None:
    proj = ProjectResponse(projectId=1, name="Test Proj")
    mock_proxy.get_project.return_value = proj
    mock_proxy.get_bom.return_value = {"projectId": 1, "parts": []}
    mock_proxy.get_part_by_number.side_effect = lambda pn: (
        PartResponse(partId=1, partNumber="VALID-PART") if pn == "VALID-PART" else None
    )

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool(
            "manage_bom_parts",
            {
                "project_id": 1,
                "parts": [
                    {"part_number": "VALID-PART", "quantity": 2},
                    {"part_number": "UNKNOWN-PART", "quantity": 1},
                ],
            },
        )
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "error"
        assert data["error"] == "Validation failed"
        assert any("UNKNOWN-PART" in d for d in data["details"])

        # Zero BOM operations executed
        mock_proxy.add_bom_part.assert_not_called()
        mock_proxy.update_bom_part.assert_not_called()
        mock_proxy.delete_bom_part.assert_not_called()


@pytest.mark.anyio
async def test_manage_bom_parts_update_preserves_part_info(
    mock_proxy: MagicMock, mock_swarm: MagicMock
) -> None:
    proj = ProjectResponse(projectId=1, name="Test Proj")
    mock_proxy.get_project.return_value = proj
    mock_proxy.get_bom.return_value = {
        "projectId": 1,
        "parts": [
            {
                "projectPartAssignmentId": 101,
                "partId": 42,
                "partNumber": "TEST-PART",
                "quantity": 1,
                "notes": "R1",
            }
        ],
    }
    mock_proxy.get_part_by_number.return_value = PartResponse(partId=42, partNumber="TEST-PART", quantity=100)

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool(
            "manage_bom_parts",
            {
                "project_id": 1,
                "parts": [
                    {"part_number": "TEST-PART", "quantity": 5, "reference_designator": "R1-R5"},
                ],
            },
        )
        assert not result.is_error
        data = result.structured_content["result"]
        assert data["status"] == "success"
        assert data["updated"] == 1

        mock_proxy.update_bom_part.assert_called_once()
        req = mock_proxy.update_bom_part.call_args[0][0]
        assert req.part_id == 42
        assert req.part_name == "TEST-PART"
        assert req.quantity == 5
        assert req.notes == "R1-R5"


# --- Swarm Cloud Intelligence Tests ---

@pytest.mark.anyio
async def test_lookup_cloud_parts_batch(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    part_num = PartNumber(
        name="NE555P",
        description="Precision Timer",
        pinouts=[Pinout(pinoutId=1, partName="NE555P", pinCount=8)],
    )
    mock_swarm.search_parts.side_effect = lambda part_number: (
        ServiceResult[SearchPartResponse](response=SearchPartResponse(parts=[part_num]))
        if part_number == "NE555P"
        else ServiceResult[SearchPartResponse](response=SearchPartResponse(parts=[]))
    )

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool(
            "lookup_cloud_parts",
            {"part_numbers": ["NE555P", "UNKNOWN-PART"]},
        )
        assert not result.is_error
        data = result.structured_content["result"]

        assert len(data["results"]) == 1
        assert data["results"][0]["part_number"] == "NE555P"
        assert data["results"][0]["description"] == "Precision Timer"
        assert "UNKNOWN-PART" in data["not_found"]


# --- Dynamic Resource & Prompt Tests ---

@pytest.mark.anyio
async def test_read_resources(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)
    server._category_cache[1] = "Passives::Resistors"

    mock_proxy.get_low_stock.return_value = PaginatedResponse[PartResponse](
        totalItems=1,
        pageSize=200,
        totalPages=1,
        pageNumber=1,
        items=[PartResponse(partId=5, partNumber="RES-10K", quantity=2, lowStockThreshold=10)],
    )
    mock_proxy.get_part_by_number.return_value = PartStoredFilesResponse(
        partId=5,
        partNumber="RES-10K",
        quantity=2,
        partTypeId=1,
    )
    mock_proxy.get_bom.return_value = {"projectId": 2, "name": "BOM Test", "parts": []}

    async with Client(server.mcp, raise_exceptions=True) as client:
        # 1. Read binner://status
        status_res = await client.read_resource("binner://status")
        status_data = json.loads(status_res.contents[0].text)
        assert status_data["status"] == "connected"

        # 2. Read binner://categories
        cat_res = await client.read_resource("binner://categories")
        cat_data = json.loads(cat_res.contents[0].text)
        assert cat_data["categories"]["1"] == "Passives::Resistors"

        # 3. Read binner://low-stock
        low_res = await client.read_resource("binner://low-stock")
        low_data = json.loads(low_res.contents[0].text)
        assert low_data["total_items"] == 1
        assert low_data["parts"][0]["part_number"] == "RES-10K"

        # 4. Read binner://parts/RES-10K
        part_res = await client.read_resource("binner://parts/RES-10K")
        part_data = json.loads(part_res.contents[0].text)
        assert part_data["part_number"] == "RES-10K"
        assert part_data["part_type"] == "Passives::Resistors"

        # 5. Read binner://projects/2/bom
        bom_res = await client.read_resource("binner://projects/2/bom")
        bom_data = json.loads(bom_res.contents[0].text)
        assert bom_data["projectId"] == 2


@pytest.mark.anyio
async def test_configurable_category_delimiter(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    """Verify that category_delimiter is configurable via BinnerConfig."""
    mock_proxy.get_part_types.return_value = [
        PartTypeResponse(partTypeId=1, name="Passives", parentPartTypeId=None),
        PartTypeResponse(partTypeId=2, name="Resistors", parentPartTypeId=1),
        PartTypeResponse(partTypeId=3, name="SMD", parentPartTypeId=2),
    ]

    # Test custom delimiter "#"
    config_hash = BinnerConfig(category_delimiter="#")
    server_hash = BinnerMCPServer(config=config_hash, proxy=mock_proxy, swarm=mock_swarm)
    server_hash._warm_category_cache()
    assert server_hash._category_cache[3] == "Passives#Resistors#SMD"

    # Test default delimiter "::"
    config_default = BinnerConfig()
    server_default = BinnerMCPServer(config=config_default, proxy=mock_proxy, swarm=mock_swarm)
    server_default._warm_category_cache()
    assert server_default._category_cache[3] == "Passives::Resistors::SMD"


@pytest.mark.anyio
async def test_list_part_types_tree_structure(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    mock_proxy.get_part_types.return_value = [
        PartTypeResponse(partTypeId=1, name="Resistor", parentPartTypeId=None),
        PartTypeResponse(partTypeId=2, name="Through-Hole", parentPartTypeId=1),
        PartTypeResponse(partTypeId=3, name="Capacitor", parentPartTypeId=None),
    ]
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        res = await client.call_tool("list_part_types", {})
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "success"
        assert data["total_types"] == 3
        # Should be rooted at 2 top-level categories: Resistor and Capacitor
        tree = data["tree"]
        assert len(tree) == 2
        resistor_node = next(n for n in tree if n["name"] == "Resistor")
        assert len(resistor_node["children"]) == 1
        assert resistor_node["children"][0]["name"] == "Through-Hole"
        assert resistor_node["children"][0]["id"] == 2


@pytest.mark.anyio
async def test_list_part_types_depth_and_root_scoping(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    mock_proxy.get_part_types.return_value = [
        PartTypeResponse(partTypeId=1, name="Resistor", parentPartTypeId=None),
        PartTypeResponse(partTypeId=2, name="Through-Hole", parentPartTypeId=1),
        PartTypeResponse(partTypeId=3, name="Metal-Film", parentPartTypeId=2),
        PartTypeResponse(partTypeId=4, name="Capacitor", parentPartTypeId=None),
    ]
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        # 1. depth=1 should omit children completely
        res1 = await client.call_tool("list_part_types", {"depth": 1})
        assert not res1.is_error
        tree1 = res1.structured_content["result"]["tree"]
        assert len(tree1) == 2
        assert "children" not in tree1[0]
        assert "children" not in tree1[1]

        # 2. depth=2 should allow 1 level of children
        res2 = await client.call_tool("list_part_types", {"depth": 2})
        assert not res2.is_error
        tree2 = res2.structured_content["result"]["tree"]
        res_node = next(n for n in tree2 if n["name"] == "Resistor")
        assert len(res_node["children"]) == 1
        assert res_node["children"][0]["name"] == "Through-Hole"
        assert "children" not in res_node["children"][0]

        # 3. root_name scoping
        res3 = await client.call_tool("list_part_types", {"root_name": "Resistor"})
        assert not res3.is_error
        tree3 = res3.structured_content["result"]["tree"]
        assert len(tree3) == 1
        assert tree3[0]["name"] == "Resistor"

        # 4. root_id scoping
        res4 = await client.call_tool("list_part_types", {"root_id": 2})
        assert not res4.is_error
        tree4 = res4.structured_content["result"]["tree"]
        assert len(tree4) == 1
        assert tree4[0]["id"] == 2
        assert tree4[0]["name"] == "Through-Hole"
        assert len(tree4[0]["children"]) == 1
        assert tree4[0]["children"][0]["name"] == "Metal-Film"


@pytest.mark.anyio
async def test_save_and_delete_part_types(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    mock_proxy.create_part_type.return_value = PartTypeResponse(partTypeId=10, name="Sensor")
    mock_proxy.delete_part_type.return_value = True

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        # Save
        save_res = await client.call_tool(
            "save_part_types",
            {"part_types": [{"name": "Sensor", "description": "Environmental sensors"}]},
        )
        assert not save_res.is_error
        save_data = save_res.structured_content["result"]
        assert save_data["status"] == "success"
        assert save_data["created_count"] == 1
        assert save_data["created"][0]["part_type_id"] == 10

        # Delete
        del_res = await client.call_tool(
            "delete_part_types",
            {"part_type_ids": [10]},
        )
        assert not del_res.is_error
        del_data = del_res.structured_content["result"]
        assert del_data["status"] == "success"
        assert del_data["deleted_count"] == 1


@pytest.mark.anyio
async def test_projects_crud_tools(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    proj = ProjectResponse(projectId=5, name="Drone Controller", description="Quadcopter FC")
    mock_proxy.get_projects.return_value = [proj]
    mock_proxy.create_project.return_value = proj
    mock_proxy.get_project.side_effect = lambda project_id=None, name=None: proj if project_id == 5 else None
    mock_proxy.get_bom.return_value = {
        "parts": [
            {
                "projectPartAssignmentId": 12,
                "partId": 42,
                "partNumber": "NE555P",
                "quantity": 2,
                "notes": "U1, U2",
                "part": {
                    "quantity": 100,
                    "packageType": "DIP-8",
                    "dateCreated": "0001-01-01T00:00:00Z",
                },
            }
        ]
    }
    mock_proxy.delete_project.return_value = True

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        # 1. List (all)
        list_res = await client.call_tool("list_projects", {})
        assert not list_res.is_error
        assert len(list_res.structured_content["result"]["projects"]) == 1

        # 1b. List (filtered)
        list_matched = await client.call_tool("list_projects", {"query": "Drone"})
        assert not list_matched.is_error
        assert len(list_matched.structured_content["result"]["projects"]) == 1

        list_unmatched = await client.call_tool("list_projects", {"query": "Nonexistent"})
        assert not list_unmatched.is_error
        assert len(list_unmatched.structured_content["result"]["projects"]) == 0

        # 2. Save (create)
        save_res = await client.call_tool(
            "save_projects",
            {"projects": [{"name": "Drone Controller", "description": "Quadcopter FC"}]},
        )
        assert not save_res.is_error
        assert save_res.structured_content["result"]["created_count"] == 1

        # 3. Get with lean BOM
        get_res = await client.call_tool("get_projects", {"project_ids": [5], "include_bom": True})
        assert not get_res.is_error
        proj_entry = get_res.structured_content["result"]["projects"][0]
        assert proj_entry["project"]["project_id"] == 5
        assert "bom" in proj_entry
        assert proj_entry["bom"] == [
            {
                "assignment_id": 12,
                "part_id": 42,
                "part_number": "NE555P",
                "quantity": 2,
                "reference_designator": "U1, U2",
                "stock_on_hand": 100,
                "package_type": "DIP-8",
            }
        ]

        # 4. Delete
        del_res = await client.call_tool("delete_projects", {"project_ids": [5]})
        assert not del_res.is_error
        assert del_res.structured_content["result"]["deleted_count"] == 1


@pytest.mark.anyio
async def test_batch_retry_then_report_never_rollback(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    """Verify that batch mutation retries transient errors, reports failures, and never rolls back."""
    mock_proxy.get_part_by_number.return_value = None

    attempts = {"FAIL-PERMANENT": 0}

    def mock_create(req):
        pn = req.get("part_number")
        if pn == "FAIL-PERMANENT":
            attempts[pn] += 1
            raise requests.exceptions.ConnectionError("Temporary socket timeout")
        return PartResponse(partId=100, partNumber=pn)

    mock_proxy.create_part.side_effect = mock_create

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        res = await client.call_tool(
            "save_parts",
            {
                "parts": [
                    {"part_number": "PART-SUCCESS-1", "quantity": 10},
                    {"part_number": "FAIL-PERMANENT", "quantity": 5},
                    {"part_number": "PART-SUCCESS-2", "quantity": 20},
                ]
            },
        )
        assert not res.is_error
        data = res.structured_content["result"]

        # Status should report partial success
        assert data["status"] == "partial_success"
        assert data["created_count"] == 2
        assert data["failed_count"] == 1

        # Invariant: FAIL-PERMANENT was retried (2 attempts total)
        assert attempts["FAIL-PERMANENT"] == 2

        # Invariant: Both PART-SUCCESS-1 and PART-SUCCESS-2 were committed (no rollback)
        created_pns = [c["part_number"] for c in data["created"]]
        assert "PART-SUCCESS-1" in created_pns
        assert "PART-SUCCESS-2" in created_pns

        # Invariant: Failure was reported with details
        assert data["failed"][0]["part_number"] == "FAIL-PERMANENT"
        assert "Temporary socket timeout" in data["failed"][0]["error"]


@pytest.mark.anyio
async def test_save_projects_invalid_project_detected_no_retry(
    mock_proxy: MagicMock, mock_swarm: MagicMock
) -> None:
    """Verify that an invalid project (non-existent project_id) is detected and not retried."""
    mock_proxy.get_project.return_value = None  # project doesn't exist
    mock_proxy.create_project.return_value = ProjectResponse(projectId=101, name="Valid-Project-1")
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        res = await client.call_tool(
            "save_projects",
            {
                "projects": [
                    {"name": "Valid-Project-1", "description": "Good"},
                    {"project_id": 99999999, "description": "Non-existent project"},
                ]
            },
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "partial_success"
        assert data["created_count"] == 1
        assert data["failed_count"] == 1

        failed_item = data["failed"][0]
        assert "99999999 does not exist" in failed_item["error"]
        assert failed_item["retries"] == 0
        mock_proxy.update_project.assert_not_called()


@pytest.mark.anyio
async def test_save_projects_non_transient_error_not_retried(
    mock_proxy: MagicMock, mock_swarm: MagicMock
) -> None:
    """Verify that a non-transient API error (e.g. 400 Bad Request) is not retried."""
    from binner_mcp.common.exceptions import ProxyAPIError

    mock_proxy.get_project.return_value = None

    def mock_create(req):
        if req.name == "BAD-REQ":
            raise ProxyAPIError("Bad Request", status_code=400)
        return ProjectResponse(projectId=200, name=req.name)

    mock_proxy.create_project.side_effect = mock_create
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        res = await client.call_tool(
            "save_projects",
            {
                "projects": [
                    {"name": "BAD-REQ", "description": "Triggers 400"},
                ]
            },
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert data["failed_count"] == 1
        assert data["failed"][0]["retries"] == 0


@pytest.mark.anyio
async def test_save_parts_comprehensive_validation_failures(
    mock_proxy: MagicMock, mock_swarm: MagicMock
) -> None:
    """Test all validation error conditions for save_parts ensuring zero side effects."""
    mock_proxy.get_part_by_id.return_value = None
    mock_proxy.get_part_by_number.side_effect = lambda pn: (
        PartResponse(partId=50, partNumber="EXISTING-PART", quantity=10)
        if pn.upper() == "EXISTING-PART"
        else None
    )

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        # Case 1: Empty parts list
        res = await client.call_tool("save_parts", {"parts": []})
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert "Validation failed" in data["error"]

        # Case 2: Batch with multiple validation failures
        res = await client.call_tool(
            "save_parts",
            {
                "parts": [
                    {"part_number": ""},  # blank part number
                    {"part_number": "P1", "quantity": -5},  # negative quantity
                    {"part_number": "P2", "low_stock_threshold": -1},  # negative threshold
                    {"part_number": "P3", "cost": -10.0},  # negative cost
                    {"part_number": "P4", "part_id": "not_an_int"},  # invalid part_id type
                    {"part_number": "P5", "part_id": 999999},  # non-existent part_id
                    {"part_number": "DUP", "quantity": 1},
                    {"part_number": "dup", "quantity": 2},  # duplicate part_number in batch
                    {"part_number": "EXISTING-PART", "create_only": True},  # create_only violation
                ]
            },
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert len(data["details"]) >= 8

        # Invariant: Zero mutations executed
        mock_proxy.create_part.assert_not_called()
        mock_proxy.update_part.assert_not_called()


@pytest.mark.anyio
async def test_delete_parts_comprehensive_validation_failures(
    mock_proxy: MagicMock, mock_swarm: MagicMock
) -> None:
    """Test delete_parts validation failures and ensure zero deletions executed."""
    mock_proxy.get_part_by_id.return_value = None
    mock_proxy.get_part_by_number.return_value = None
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        # Case 1: Neither part_numbers nor part_ids provided
        res = await client.call_tool("delete_parts", {})
        assert not res.is_error
        assert res.structured_content["result"]["status"] == "error"

        # Case 2: Non-existent part_id and part_number
        res = await client.call_tool(
            "delete_parts",
            {"part_ids": [999999], "part_numbers": ["NON-EXISTENT-PART"]},
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert len(data["details"]) == 2

        # Invariant: Zero deletions executed
        mock_proxy.delete_part.assert_not_called()


@pytest.mark.anyio
async def test_manage_bom_parts_comprehensive_validation_failures(
    mock_proxy: MagicMock, mock_swarm: MagicMock
) -> None:
    """Test all manage_bom_parts validation failures."""
    # Case 1: Non-existent project
    mock_proxy.get_project.return_value = None
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        res = await client.call_tool(
            "manage_bom_parts",
            {"project_id": 999999, "parts": [{"part_number": "RES-10K", "quantity": 1}]},
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert "Project ID 999999 does not exist" in data["details"][0]

        # Case 2: Project exists, but empty parts list
        proj = ProjectResponse(projectId=10, name="Maker Drone")
        mock_proxy.get_project.return_value = proj
        mock_proxy.get_bom.return_value = {"projectId": 10, "parts": []}

        res = await client.call_tool("manage_bom_parts", {"project_id": 10, "parts": []})
        assert not res.is_error
        assert res.structured_content["result"]["status"] == "error"

        # Case 3: Mixed validation errors in parts batch
        mock_proxy.get_part_by_number.side_effect = lambda pn: (
            PartResponse(partId=101, partNumber="IN-STOCK", quantity=5)
            if pn == "IN-STOCK"
            else None
        )

        res = await client.call_tool(
            "manage_bom_parts",
            {
                "project_id": 10,
                "parts": [
                    {"quantity": 1},  # missing both part_number and part_id
                    {"part_number": "NOT-IN-INVENTORY", "quantity": 1},  # component missing
                    {"part_number": "IN-STOCK", "quantity": 0},  # quantity < 1
                    {"part_number": "IN-STOCK", "adjust_stock_delta": -10},  # stock shortage
                    {"part_number": "IN-STOCK", "remove": True},  # removing part not in BOM
                ],
            },
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert len(data["details"]) == 5

        # Invariant: Zero mutations executed
        mock_proxy.add_bom_part.assert_not_called()
        mock_proxy.update_bom_part.assert_not_called()
        mock_proxy.delete_bom_part.assert_not_called()
        mock_proxy.update_quantity.assert_not_called()


@pytest.mark.anyio
async def test_consume_project_bom_comprehensive_validation_failures(
    mock_proxy: MagicMock, mock_swarm: MagicMock
) -> None:
    """Test all consume_project_bom validation failures."""
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        # Case 1: build_quantity < 1
        res = await client.call_tool("consume_project_bom", {"project_id": 1, "build_quantity": 0})
        assert not res.is_error
        assert res.structured_content["result"]["status"] == "error"

        # Case 2: Neither project_id nor name provided
        res = await client.call_tool("consume_project_bom", {"build_quantity": 1})
        assert not res.is_error
        assert res.structured_content["result"]["status"] == "error"

        # Case 3: Non-existent project
        mock_proxy.get_project.return_value = None
        res = await client.call_tool("consume_project_bom", {"project_id": 999999})
        assert not res.is_error
        assert res.structured_content["result"]["status"] == "error"

        # Case 4: Project with empty BOM
        proj = ProjectResponse(projectId=20, name="Empty Proj")
        mock_proxy.get_project.return_value = proj
        mock_proxy.get_bom.return_value = {"projectId": 20, "parts": []}

        res = await client.call_tool("consume_project_bom", {"project_id": 20})
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert "BOM has no assigned components" in data["details"][0]


@pytest.mark.anyio
async def test_save_and_delete_part_types_validation_failures(
    mock_proxy: MagicMock, mock_swarm: MagicMock
) -> None:
    """Test save_part_types and delete_part_types validation error paths."""
    mock_proxy.get_part_types.return_value = []
    mock_proxy.get_part_type_by_name.return_value = None
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        # save_part_types: empty list
        res = await client.call_tool("save_part_types", {"part_types": []})
        assert not res.is_error
        assert res.structured_content["result"]["status"] == "error"

        # save_part_types: missing name for create
        res = await client.call_tool("save_part_types", {"part_types": [{"description": "No name"}]})
        assert not res.is_error
        assert res.structured_content["result"]["status"] == "error"

        # save_part_types: non-existent part_type_id
        res = await client.call_tool("save_part_types", {"part_types": [{"part_type_id": 999999}]})
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert data["failed_count"] == 1
        assert data["failed"][0]["retries"] == 0

        # delete_part_types: missing both IDs and names
        res = await client.call_tool("delete_part_types", {})
        assert not res.is_error
        assert res.structured_content["result"]["status"] == "error"

        # delete_part_types: non-existent target
        res = await client.call_tool("delete_part_types", {"names": ["NonExistentCategory"]})
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert "None of the specified part types exist" in data["details"][0]


@pytest.mark.anyio
async def test_ambiguous_part_types_rejected_across_tools(
    mock_proxy: MagicMock, mock_swarm: MagicMock
) -> None:
    """Verify that ambiguous part types and category inputs are strictly rejected across all MCP tools."""
    category_tree = [
        PartTypeResponse(partTypeId=1, name="Passives", parentPartTypeId=None),
        PartTypeResponse(partTypeId=2, name="Resistors", parentPartTypeId=1),
        PartTypeResponse(partTypeId=3, name="SMD", parentPartTypeId=2),
        PartTypeResponse(partTypeId=4, name="Capacitors", parentPartTypeId=1),
        PartTypeResponse(partTypeId=5, name="SMD", parentPartTypeId=4),
        PartTypeResponse(partTypeId=6, name="Active", parentPartTypeId=None),
    ]
    mock_proxy.get_part_types.return_value = category_tree
    mock_proxy.get_part_by_number.return_value = None
    mock_proxy.get_part_by_id.return_value = None

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        # --- 1. save_parts: Rejection of non-existent part_type_id ---
        res = await client.call_tool(
            "save_parts",
            {"parts": [{"part_number": "R1", "part_type_id": 999999}]},
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert "Validation failed" in data["error"]
        assert any("Part type ID 999999 does not exist" in d for d in data["details"])
        mock_proxy.create_part.assert_not_called()

        # --- 2. save_parts: Rejection of ambiguous leaf name 'SMD' ---
        res = await client.call_tool(
            "save_parts",
            {"parts": [{"part_number": "R1", "part_type": "SMD"}]},
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert any("Ambiguous part type 'SMD'" in d for d in data["details"])
        assert any("Matches 2 categories" in d for d in data["details"])
        mock_proxy.create_part.assert_not_called()

        # --- 3. save_parts: Rejection of ambiguous partial path 'Passives::SMD' ---
        res = await client.call_tool(
            "save_parts",
            {"parts": [{"part_number": "R1", "part_type": "Passives::SMD"}]},
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert any("Ambiguous part type 'Passives::SMD'" in d for d in data["details"])
        mock_proxy.create_part.assert_not_called()

        # --- 4. save_parts: Rejection of non-existent numeric part_type ---
        res = await client.call_tool(
            "save_parts",
            {"parts": [{"part_number": "R1", "part_type": 999999}]},
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert any("Part type ID 999999 does not exist" in d for d in data["details"])
        mock_proxy.create_part.assert_not_called()

        # --- 5. save_parts: Rejection of blank part_type ---
        res = await client.call_tool(
            "save_parts",
            {"parts": [{"part_number": "R1", "part_type": "   "}]},
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert any("cannot be blank" in d for d in data["details"])
        mock_proxy.create_part.assert_not_called()

        # --- 6. save_parts: Rejection of ambiguous parent in new path 'SMD::0805' ---
        res = await client.call_tool(
            "save_parts",
            {"parts": [{"part_number": "R1", "part_type": "SMD::0805"}]},
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert any("Ambiguous parent category in path 'SMD::0805'" in d for d in data["details"])
        mock_proxy.create_part.assert_not_called()

        # --- 7. list_parts: Rejection of ambiguous part_type filter ---
        res = await client.call_tool(
            "list_parts",
            {"part_type": "SMD"},
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert data["error"] == "Ambiguous part type"
        assert any("Matches 2 categories" in d for d in data["details"])
        mock_proxy.list_parts.assert_not_called()

        # --- 8. list_part_types: Rejection of ambiguous root_name ---
        res = await client.call_tool(
            "list_part_types",
            {"root_name": "SMD"},
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert data["error"] == "Ambiguous root part type name"
        assert any("Matches 2 categories" in d for d in data["details"])

        # --- 9. save_part_types: Rejection of ambiguous name update without part_type_id ---
        res = await client.call_tool(
            "save_part_types",
            {"part_types": [{"name": "SMD", "description": "Updated SMD"}]},
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert any("part type name is ambiguous" in d for d in data["details"])
        mock_proxy.update_part_type.assert_not_called()
        mock_proxy.create_part_type.assert_not_called()

        # --- 10. delete_part_types: Rejection of ambiguous name in names ---
        res = await client.call_tool(
            "delete_part_types",
            {"names": ["SMD"]},
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "error"
        assert data["error"] == "Ambiguous part type name"
        assert any("Matches 2 categories" in d for d in data["details"])
        mock_proxy.delete_part_type.assert_not_called()


@pytest.mark.anyio
async def test_overloaded_part_type_acceptance(
    mock_proxy: MagicMock, mock_swarm: MagicMock
) -> None:
    """Verify that save_parts accepts integer ID, numeric string ID, leaf name, and full path when unambiguous."""
    category_tree = [
        PartTypeResponse(partTypeId=1, name="Passives", parentPartTypeId=None),
        PartTypeResponse(partTypeId=2, name="Resistors", parentPartTypeId=1),
        PartTypeResponse(partTypeId=3, name="SMD", parentPartTypeId=2),
    ]
    mock_proxy.get_part_types.return_value = category_tree
    mock_proxy.get_part_by_number.return_value = None
    mock_proxy.get_part_by_id.return_value = None
    mock_proxy.create_part.side_effect = lambda req: PartResponse(
        partId=101,
        partNumber=req["part_number"],
        partTypeId=int(req["part_type_id"]) if req.get("part_type_id") else None,
    )

    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=True) as client:
        # 1. Unambiguous integer ID (3)
        res1 = await client.call_tool(
            "save_parts",
            {"parts": [{"part_number": "R_INT", "part_type": 3}]},
        )
        assert not res1.is_error
        assert res1.structured_content["result"]["status"] == "success"
        assert res1.structured_content["result"]["created_count"] == 1

        # 2. Unambiguous digit string ID ("3")
        res2 = await client.call_tool(
            "save_parts",
            {"parts": [{"part_number": "R_STR_ID", "part_type": "3"}]},
        )
        assert not res2.is_error
        assert res2.structured_content["result"]["status"] == "success"
        assert res2.structured_content["result"]["created_count"] == 1

        # 3. Unambiguous leaf name ("Resistors" -> ID 2)
        res3 = await client.call_tool(
            "save_parts",
            {"parts": [{"part_number": "R_LEAF", "part_type": "Resistors"}]},
        )
        assert not res3.is_error
        assert res3.structured_content["result"]["status"] == "success"
        assert res3.structured_content["result"]["created_count"] == 1

        # 4. Unambiguous full path ("Passives::Resistors::SMD" -> ID 3)
        res4 = await client.call_tool(
            "save_parts",
            {"parts": [{"part_number": "R_PATH", "part_type": "Passives::Resistors::SMD"}]},
        )
        assert not res4.is_error
        assert res4.structured_content["result"]["status"] == "success"
        assert res4.structured_content["result"]["created_count"] == 1

        # 5. Fallback numeric part_type_id (3) when part_type is omitted
        res5 = await client.call_tool(
            "save_parts",
            {"parts": [{"part_number": "R_FALLBACK_ID", "part_type_id": 3}]},
        )
        assert not res5.is_error
        assert res5.structured_content["result"]["status"] == "success"
        assert res5.structured_content["result"]["created_count"] == 1


@pytest.mark.anyio
async def test_mcp_sdk_tool_schemas_published(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    """Verify that MCP tools declare rich Pydantic schemas with properties and descriptions to the SDK."""
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    save_parts_tool = server.mcp._tool_manager.get_tool("save_parts")
    assert save_parts_tool is not None
    params = save_parts_tool.parameters
    assert "$defs" in params
    assert "PartSaveInput" in params["$defs"]
    part_props = params["$defs"]["PartSaveInput"]["properties"]
    assert "part_number" in part_props
    assert "part_type" in part_props
    assert "quantity" in part_props
    assert "cost" in part_props
    assert "description" in part_props["part_type"]

    save_projects_tool = server.mcp._tool_manager.get_tool("save_projects")
    assert save_projects_tool is not None
    proj_params = save_projects_tool.parameters
    assert "ProjectSaveInput" in proj_params["$defs"]

    save_part_types_tool = server.mcp._tool_manager.get_tool("save_part_types")
    assert save_part_types_tool is not None
    pt_params = save_part_types_tool.parameters
    assert "PartTypeSaveInput" in pt_params["$defs"]

    manage_bom_tool = server.mcp._tool_manager.get_tool("manage_bom_parts")
    assert manage_bom_tool is not None
    bom_params = manage_bom_tool.parameters
    assert "BomPartInput" in bom_params["$defs"]


@pytest.mark.anyio
async def test_unknown_fields_and_arguments_rejected(mock_proxy: MagicMock, mock_swarm: MagicMock) -> None:
    """Verify that unknown fields in input structures and unknown tool arguments are strictly rejected."""
    server = BinnerMCPServer(proxy=mock_proxy, swarm=mock_swarm)

    async with Client(server.mcp, raise_exceptions=False) as client:
        # 1. Unknown field in PartSaveInput
        res = await client.call_tool("save_parts", {"parts": [{"part_number": "R1", "unknown_field": 123}]})
        assert res.is_error
        assert "Extra inputs are not permitted" in res.content[0].text
        assert "parts.0.unknown_field" in res.content[0].text

        # 2. Unknown top-level argument in save_parts
        res = await client.call_tool("save_parts", {"parts": [{"part_number": "R1"}], "bogus_arg": "invalid"})
        assert res.is_error
        assert "Extra inputs are not permitted" in res.content[0].text
        assert "bogus_arg" in res.content[0].text

        # 3. Unknown field in ProjectSaveInput
        res = await client.call_tool("save_projects", {"projects": [{"name": "Proj", "invalid_key": True}]})
        assert res.is_error
        assert "Extra inputs are not permitted" in res.content[0].text
        assert "projects.0.invalid_key" in res.content[0].text

        # 4. Unknown field in PartTypeSaveInput
        res = await client.call_tool("save_part_types", {"part_types": [{"name": "Type", "bad_attr": "val"}]})
        assert res.is_error
        assert "Extra inputs are not permitted" in res.content[0].text
        assert "part_types.0.bad_attr" in res.content[0].text

        # 5. Unknown field in BomPartInput
        res = await client.call_tool("manage_bom_parts", {"project_id": 1, "parts": [{"part_number": "R1", "extra": 1}]})
        assert res.is_error
        assert "Extra inputs are not permitted" in res.content[0].text
        assert "parts.0.extra" in res.content[0].text

        # 6. Unknown top-level argument in get_parts
        res = await client.call_tool("get_parts", {"part_numbers": ["R1"], "unknown_param": 10})
        assert res.is_error
        assert "Extra inputs are not permitted" in res.content[0].text
        assert "unknown_param" in res.content[0].text







