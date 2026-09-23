"""In-memory tests for BinnerMCPServer using the official MCP Python SDK Client.

Reference: https://py.sdk.modelcontextprotocol.io/get-started/testing/
"""

import asyncio
import json
import threading
from unittest.mock import MagicMock
import pytest
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
            "manage_project",
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
async def test_manage_project_consume_bom_shortage_has_no_side_effects(
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
            "manage_project",
            {"action": "consume_bom", "project_id": 1, "build_quantity": 1},
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
async def test_manage_project_consume_bom_success(
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
            "manage_project",
            {"action": "consume_bom", "project_id": 1, "build_quantity": 2},
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
