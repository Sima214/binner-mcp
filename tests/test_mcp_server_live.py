"""Live integration test for BinnerMCPServer against running Binner instance."""

import json
import uuid
import pytest
from mcp import Client

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.mcp.server import BinnerMCPServer
from binner_mcp.swarmer.client import SwarmClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_live_mcp_get_system_status(live_proxy: BinnerAPIProxy) -> None:
    server = BinnerMCPServer(proxy=live_proxy, swarm=SwarmClient())

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool("get_system_status", {"check_cloud": False})
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "connected"
        assert data["backend_url"] == live_proxy.base_url
        assert data["binner_version"] is not None
        assert data["user"]["name"] == "Admin"
        assert data["inventory"]["unique_parts"] >= 0
        assert "swarm_cloud" not in data


@pytest.mark.anyio
async def test_live_mcp_get_system_status_with_cloud(live_proxy: BinnerAPIProxy) -> None:
    server = BinnerMCPServer(proxy=live_proxy, swarm=SwarmClient())

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool("get_system_status", {"check_cloud": True})
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "connected"
        assert "swarm_cloud" in data
        assert data["swarm_cloud"]["status"] in ("online", "unreachable")


@pytest.mark.anyio
async def test_live_mcp_get_system_status_connection_refused_port() -> None:
    # Use an unassigned localhost port to verify real TCP ConnectionRefused handling
    offline_proxy = BinnerAPIProxy(base_url="http://127.0.0.1:59999")
    server = BinnerMCPServer(proxy=offline_proxy, swarm=SwarmClient())

    async with Client(server.mcp, raise_exceptions=True) as client:
        result = await client.call_tool("get_system_status", {"check_cloud": False})
        assert not result.is_error
        data = result.structured_content["result"]

        assert data["status"] == "offline"
        assert data["backend_url"] == "http://127.0.0.1:59999"
        assert "Connection refused" in data["detail"]


def test_live_mcp_connect_offline_port() -> None:
    # Verify that connect() gracefully enters degraded mode on a real socket failure
    offline_proxy = BinnerAPIProxy(base_url="http://127.0.0.1:59999")
    server = BinnerMCPServer(proxy=offline_proxy, swarm=SwarmClient())
    assert server.connect() is False


@pytest.mark.anyio
async def test_live_mcp_batched_parts_lifecycle(live_proxy: BinnerAPIProxy) -> None:
    """Exercise live batched inventory operations: save_parts, list_parts, get_parts, delete_parts."""
    server = BinnerMCPServer(proxy=live_proxy, swarm=SwarmClient())
    server.connect()

    suffix = uuid.uuid4().hex[:6]
    pn_1 = f"TEST_MCP_A_{suffix}"
    pn_2 = f"TEST_MCP_B_{suffix}"

    async with Client(server.mcp, raise_exceptions=True) as client:
        # 1. Zero-side-effects test: pass 1 valid and 1 invalid item (negative quantity)
        fail_res = await client.call_tool(
            "save_parts",
            {
                "parts": [
                    {"part_number": pn_1, "quantity": 10},
                    {"part_number": pn_2, "quantity": -5},
                ]
            },
        )
        assert not fail_res.is_error
        fail_data = fail_res.structured_content["result"]
        assert fail_data["status"] == "error"
        assert fail_data["error"] == "Validation failed"

        # Verify pn_1 was NOT created in DB
        check_p1 = live_proxy.get_part_by_number(pn_1)
        assert check_p1 is None

        # 2. Batch Creation: Create both parts
        create_res = await client.call_tool(
            "save_parts",
            {
                "parts": [
                    {"part_number": pn_1, "quantity": 10, "bin_number": "A1-01", "location": "Lab 1"},
                    {"part_number": pn_2, "quantity": 25, "bin_number": "B2-02", "location": "Lab 2"},
                ]
            },
        )
        assert not create_res.is_error
        create_data = create_res.structured_content["result"]
        assert create_data["status"] == "success"
        assert create_data["created_count"] == 2
        p1_id = create_data["created"][0]["part_id"]
        p2_id = create_data["created"][1]["part_id"]

        try:
            # 3. list_parts (minimal default)
            list_res = await client.call_tool("list_parts", {"query": suffix})
            assert not list_res.is_error
            list_data = list_res.structured_content["result"]
            assert list_data["total_items"] >= 2
            found_pns = {p["part_number"] for p in list_data["parts"]}
            assert pn_1 in found_pns
            assert pn_2 in found_pns

            # 4. get_parts (batch inspection by part_number and part_id)
            get_res = await client.call_tool(
                "get_parts",
                {"part_numbers": [pn_1], "part_ids": [p2_id]},
            )
            assert not get_res.is_error
            get_data = get_res.structured_content["result"]
            assert len(get_data["parts"]) == 2
            item1 = next(p for p in get_data["parts"] if p["part_number"] == pn_1)
            item2 = next(p for p in get_data["parts"] if p["part_number"] == pn_2)
            assert item1["quantity"] == 10
            assert item2["quantity"] == 25

            # 5. Batch update with diff tracking
            update_res = await client.call_tool(
                "save_parts",
                {
                    "parts": [
                        {"part_number": pn_1, "quantity": 15, "bin_number": "A1-99"},
                    ]
                },
            )
            assert not update_res.is_error
            update_data = update_res.structured_content["result"]
            assert update_data["status"] == "success"
            assert update_data["updated_count"] == 1
            changes = update_data["updated"][0]["changes"]
            assert changes["quantity"]["from"] == 10
            assert changes["quantity"]["to"] == 15
            assert changes["quantity"]["delta"] == 5
            assert changes["bin_number"]["to"] == "A1-99"

        finally:
            # 6. Batch deletion
            del_res = await client.call_tool(
                "delete_parts",
                {"part_numbers": [pn_1, pn_2]},
            )
            assert not del_res.is_error
            del_data = del_res.structured_content["result"]
            assert del_data["status"] == "success"
            assert len(del_data["deleted"]) == 2

            # Verify deletion in database
            assert live_proxy.get_part_by_number(pn_1) is None
            assert live_proxy.get_part_by_number(pn_2) is None


@pytest.mark.anyio
async def test_live_mcp_projects_and_bom_lifecycle(live_proxy: BinnerAPIProxy) -> None:
    """Exercise live maker project lifecycle, batched BOM line items, and stock consumption."""
    server = BinnerMCPServer(proxy=live_proxy, swarm=SwarmClient())
    server.connect()

    suffix = uuid.uuid4().hex[:6]
    proj_name = f"TEST_PROJ_{suffix}"
    pn = f"TEST_BOM_PART_{suffix}"

    # Create part with 10 units
    part = live_proxy.create_part({"part_number": pn, "quantity": 10})
    proj_id = None

    try:
        async with Client(server.mcp, raise_exceptions=True) as client:
            # 1. Create project
            proj_res = await client.call_tool(
                "manage_project",
                {"action": "create", "name": proj_name, "description": "Test maker project"},
            )
            assert not proj_res.is_error
            proj_data = proj_res.structured_content["result"]
            assert proj_data["status"] == "success"
            proj_id = proj_data["project"]["project_id"]

            # 2. Add BOM parts batch
            bom_res = await client.call_tool(
                "manage_bom_parts",
                {
                    "project_id": proj_id,
                    "parts": [
                        {"part_number": pn, "quantity": 2, "reference_designator": "U1"},
                    ],
                },
            )
            assert not bom_res.is_error
            bom_data = bom_res.structured_content["result"]
            assert bom_data["status"] == "success"
            assert bom_data["allocated"] == 1

            # 3. Inspect project BOM
            get_proj_res = await client.call_tool(
                "manage_project",
                {"action": "get", "project_id": proj_id, "include_bom": True},
            )
            assert not get_proj_res.is_error
            get_proj_data = get_proj_res.structured_content["result"]
            assert "bom" in get_proj_data

            # 4. Shortage test: attempt to consume for 10 units (requires 20, but stock is 10)
            shortage_res = await client.call_tool(
                "manage_project",
                {"action": "consume_bom", "project_id": proj_id, "build_quantity": 10},
            )
            assert not shortage_res.is_error
            shortage_data = shortage_res.structured_content["result"]
            assert shortage_data["status"] == "error"
            assert "shortages" in shortage_data
            assert shortage_data["shortages"][0]["part_number"] == pn
            assert shortage_data["shortages"][0]["shortage"] == 10

            # Verify stock remains untouched at 10
            assert live_proxy.get_part_by_number(pn).quantity == 10

            # 5. Success consumption: consume for 2 units (requires 4, stock is 10)
            consume_res = await client.call_tool(
                "manage_project",
                {"action": "consume_bom", "project_id": proj_id, "build_quantity": 2},
            )
            assert not consume_res.is_error
            consume_data = consume_res.structured_content["result"]
            assert consume_data["status"] == "success"
            assert consume_data["deductions"][0]["deducted"] == 4
            assert consume_data["deductions"][0]["remaining_stock"] == 6

            # Verify stock in live DB is now 6
            assert live_proxy.get_part_by_number(pn).quantity == 6

    finally:
        if proj_id:
            live_proxy.delete_project(proj_id)
        live_proxy.delete_part(part.part_id)


@pytest.mark.anyio
async def test_live_mcp_resources(live_proxy: BinnerAPIProxy) -> None:
    """Exercise reading live dynamic resources."""
    server = BinnerMCPServer(proxy=live_proxy, swarm=SwarmClient())
    server.connect()

    async with Client(server.mcp, raise_exceptions=True) as client:
        # Read status resource
        status_res = await client.read_resource("binner://status")
        assert len(status_res.contents) > 0
        status_json = json.loads(status_res.contents[0].text)
        assert status_json["status"] == "connected"

        # Read categories resource
        cat_res = await client.read_resource("binner://categories")
        assert len(cat_res.contents) > 0
        cat_json = json.loads(cat_res.contents[0].text)
        assert "categories" in cat_json

