"""Unit tests for projects, BOM, and part categories in BinnerAPIProxy."""
from unittest.mock import MagicMock, patch

import pytest

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.models import (
    AddBomPartRequest,
    BomBasicResponse,
    CreatePartTypeRequest,
    CreateProjectRequest,
    PartTypeResponse,
    ProjectResponse,
    UpdateBomPartRequest,
    UpdatePartTypeRequest,
    UpdateProjectRequest,
)


def test_get_part_types_all(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = [
        {"partTypeId": 1, "name": "Resistors", "parts": 15},
        {"partTypeId": 2, "name": "Capacitors", "parts": 30},
    ]

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        types = proxy.get_part_types()
        assert len(types) == 2
        assert types[0].name == "Resistors"
        assert types[1].parts == 30
        mock_exec.assert_called_once_with("GET", "/api/parttype/all")


def test_get_part_types_parent_filtering(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = [
        {"partTypeId": 10, "name": "Ceramic", "parentPartType": "Capacitors", "parts": 12},
    ]

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        types = proxy.get_part_types(parent="Capacitors")
        assert len(types) == 1
        assert types[0].name == "Ceramic"
        assert types[0].parent_part_type == "Capacitors"
        mock_exec.assert_called_once_with(
            "GET",
            "/api/parttype/list",
            params={"parent": "Capacitors"},
        )


def test_create_and_update_and_delete_part_type(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True

    # 1. Create
    mock_create_resp = MagicMock()
    mock_create_resp.status_code = 200
    mock_create_resp.ok = True
    mock_create_resp.json.return_value = {"partTypeId": 5, "name": "Inductor", "description": "Power coils"}

    with patch.object(proxy, "_execute_request", return_value=mock_create_resp) as mock_exec:
        created = proxy.create_part_type(CreatePartTypeRequest(name="Inductor", description="Power coils"))
        assert created.part_type_id == 5
        assert created.name == "Inductor"
        mock_exec.assert_called_once_with(
            "POST",
            "/api/parttype",
            json={"name": "Inductor", "description": "Power coils"},
        )

    # 2. Update
    mock_update_resp = MagicMock()
    mock_update_resp.status_code = 200
    mock_update_resp.ok = True
    mock_update_resp.json.return_value = {"partTypeId": 5, "name": "Inductors & Coils", "description": "Updated"}

    with patch.object(proxy, "_execute_request", return_value=mock_update_resp) as mock_exec:
        updated = proxy.update_part_type(UpdatePartTypeRequest(partTypeId=5, name="Inductors & Coils", description="Updated"))
        assert updated.part_type_id == 5
        assert updated.name == "Inductors & Coils"
        mock_exec.assert_called_once_with(
            "PUT",
            "/api/parttype",
            json={"name": "Inductors & Coils", "description": "Updated", "partTypeId": 5},
        )

    # 3. Delete
    mock_delete_resp = MagicMock()
    mock_delete_resp.status_code = 200
    mock_delete_resp.ok = True

    with patch.object(proxy, "_execute_request", return_value=mock_delete_resp) as mock_exec:
        assert proxy.delete_part_type(5) is True
        mock_exec.assert_called_once_with("DELETE", "/api/parttype", json={"partTypeId": 5})


def test_get_projects_pascal_case_sorting(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = [
        {"projectId": 1, "name": "Alpha", "partCount": 5},
        {"projectId": 2, "name": "Beta", "partCount": 10},
    ]

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        projects = proxy.get_projects(order_by="name", direction="Descending")
        assert len(projects) == 2
        assert projects[0].name == "Alpha"

        # Verify lowercase "name" was converted to PascalCase "Name" for EF Core
        call_params = mock_exec.call_args[1]["params"]
        assert call_params["orderBy"] == "Name"
        assert call_params["direction"] == "Descending"


def test_create_and_update_and_delete_project(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True

    # 1. Create
    mock_create_resp = MagicMock()
    mock_create_resp.status_code = 200
    mock_create_resp.ok = True
    mock_create_resp.json.return_value = {"projectId": 12, "name": "Drone V2", "archived": False}

    with patch.object(proxy, "_execute_request", return_value=mock_create_resp) as mock_exec:
        proj = proxy.create_project(CreateProjectRequest(name="Drone V2"))
        assert proj.project_id == 12
        assert proj.name == "Drone V2"
        mock_exec.assert_called_once_with("POST", "/api/project", json={"name": "Drone V2", "archived": False})

    # 2. Update
    mock_update_resp = MagicMock()
    mock_update_resp.status_code = 200
    mock_update_resp.ok = True
    mock_update_resp.json.return_value = {"projectId": 12, "name": "Drone V2 Pro", "archived": False}

    with patch.object(proxy, "_execute_request", return_value=mock_update_resp) as mock_exec:
        updated_proj = proxy.update_project(UpdateProjectRequest(projectId=12, name="Drone V2 Pro"))
        assert updated_proj.project_id == 12
        assert updated_proj.name == "Drone V2 Pro"
        mock_exec.assert_called_once_with("PUT", "/api/project", json={"name": "Drone V2 Pro", "archived": False, "projectId": 12})

    # 3. Delete
    mock_delete_resp = MagicMock()
    mock_delete_resp.status_code = 200
    mock_delete_resp.ok = True

    with patch.object(proxy, "_execute_request", return_value=mock_delete_resp) as mock_exec:
        assert proxy.delete_project(12) is True
        mock_exec.assert_called_once_with("DELETE", "/api/project", json={"projectId": 12})


def test_get_bom_by_name_and_id(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {"projectId": 12, "name": "Drone V2", "parts": []}

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        bom1 = proxy.get_bom(project_id=12)
        assert bom1["name"] == "Drone V2"
        mock_exec.assert_called_with("GET", "/api/bom", params={"projectId": 12})

        bom2 = proxy.get_bom(name="Drone V2")
        assert bom2["projectId"] == 12
        mock_exec.assert_called_with("GET", "/api/bom", params={"name": "Drone V2"})


def test_bom_part_operations(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True

    # 1. Add BOM part
    mock_add_resp = MagicMock()
    mock_add_resp.status_code = 200
    mock_add_resp.ok = True
    mock_add_resp.json.return_value = {"projectPartAssignmentId": 99, "partNumber": "IC-NE555", "quantity": 2}

    with patch.object(proxy, "_execute_request", return_value=mock_add_resp) as mock_exec:
        add_res = proxy.add_bom_part(AddBomPartRequest(partNumber="IC-NE555", projectId=12, quantity=2))
        assert add_res["projectPartAssignmentId"] == 99
        mock_exec.assert_called_once_with(
            "POST",
            "/api/bom/part",
            json={"partNumber": "IC-NE555", "projectId": 12, "cost": 0.0, "quantity": 2, "quantityAvailable": 0},
        )

    # 2. Update BOM part
    mock_update_resp = MagicMock()
    mock_update_resp.status_code = 200
    mock_update_resp.ok = True
    mock_update_resp.json.return_value = {"projectPartAssignmentId": 99, "quantity": 4}

    with patch.object(proxy, "_execute_request", return_value=mock_update_resp) as mock_exec:
        upd_res = proxy.update_bom_part(UpdateBomPartRequest(projectPartAssignmentId=99, projectId=12, quantity=4))
        assert upd_res["quantity"] == 4
        mock_exec.assert_called_once_with(
            "PUT",
            "/api/bom/part",
            json={"projectPartAssignmentId": 99, "projectId": 12, "cost": 0.0, "quantity": 4, "quantityAvailable": 0},
        )

    # 3. Delete BOM part
    mock_del_resp = MagicMock()
    mock_del_resp.status_code = 200
    mock_del_resp.ok = True

    with patch.object(proxy, "_execute_request", return_value=mock_del_resp) as mock_exec:
        del_res = proxy.delete_bom_part(ids=99, project_id=12)
        assert del_res is True
        mock_exec.assert_called_once_with(
            "DELETE",
            "/api/bom/part",
            json={"projectId": 12, "ids": [99]},
        )
