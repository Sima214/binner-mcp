"""Integration tests for live Binner instance: projects, BOM, and part categories."""
import uuid
import pytest

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.models import (
    AddBomPartRequest,
    CreatePartTypeRequest,
    CreateProjectRequest,
    UpdateBomPartRequest,
    UpdatePartTypeRequest,
    UpdateProjectRequest,
)


def test_live_part_types(live_proxy: BinnerAPIProxy) -> None:
    part_types = live_proxy.get_part_types()
    assert isinstance(part_types, list)
    assert len(part_types) > 0

    # 1. Test hierarchical query with parent
    parent_category = next((pt.name for pt in part_types if pt.name in ("Capacitor", "Resistor", "Inductor", "IC")), None)
    if parent_category:
        subtypes = live_proxy.get_part_types(parent=parent_category)
        assert isinstance(subtypes, list)

    # 2. Test create, update, delete temporary category
    unique_suffix = uuid.uuid4().hex[:6]
    temp_type_name = f"TEST_TYPE_{unique_suffix}"

    created = live_proxy.create_part_type(
        CreatePartTypeRequest(
            name=temp_type_name,
            description="Temporary test category",
        )
    )
    assert created.part_type_id > 0
    assert created.name == temp_type_name

    try:
        updated = live_proxy.update_part_type(
            UpdatePartTypeRequest(
                partTypeId=created.part_type_id,
                name=f"{temp_type_name}_UPDATED",
                description="Updated test category",
            )
        )
        assert updated.name == f"{temp_type_name}_UPDATED"
    finally:
        deleted = live_proxy.delete_part_type(created.part_type_id)
        assert deleted is True


def test_live_projects_and_bom(live_proxy: BinnerAPIProxy) -> None:
    # 1. Test projects listing with lowercase order_by (verifying PascalCase normalization)
    projects = live_proxy.get_projects(order_by="name", page=1, results=20)
    assert isinstance(projects, list)

    bom_list = live_proxy.get_bom_list(page=1, results=20)
    assert isinstance(bom_list, list)

    # 2. Create a temporary project
    unique_suffix = uuid.uuid4().hex[:6]
    temp_project_name = f"TEST_PROJ_{unique_suffix}"

    created_proj = live_proxy.create_project(
        CreateProjectRequest(
            name=temp_project_name,
            description="Temporary test maker project",
        )
    )
    assert created_proj.project_id > 0
    assert created_proj.name == temp_project_name
    proj_id = created_proj.project_id

    try:
        # 3. Update project
        updated_proj = live_proxy.update_project(
            UpdateProjectRequest(
                projectId=proj_id,
                name=f"{temp_project_name}_UPDATED",
                description="Updated description",
            )
        )
        assert updated_proj.name == f"{temp_project_name}_UPDATED"

        # 4. Retrieve project by ID and by name
        by_id = live_proxy.get_project(project_id=proj_id)
        assert by_id is not None
        assert by_id.project_id == proj_id

        by_name = live_proxy.get_project(name=f"{temp_project_name}_UPDATED")
        assert by_name is not None
        assert by_name.project_id == proj_id

        # 5. Retrieve BOM by ID and by name
        bom_by_id = live_proxy.get_bom(project_id=proj_id)
        assert bom_by_id["projectId"] == proj_id

        bom_by_name = live_proxy.get_bom(name=f"{temp_project_name}_UPDATED")
        assert bom_by_name["projectId"] == proj_id

        # 6. Add BOM part
        bom_part = live_proxy.add_bom_part(
            AddBomPartRequest(
                projectId=proj_id,
                partNumber="GENERIC-10K",
                quantity=3,
                notes="Pull-up resistor",
            )
        )
        assert bom_part is not None
        assignment_id = bom_part.get("projectPartAssignmentId")
        assert assignment_id is not None

        # 7. Update BOM part
        upd_bom = live_proxy.update_bom_part(
            UpdateBomPartRequest(
                projectPartAssignmentId=assignment_id,
                projectId=proj_id,
                quantity=5,
                notes="Updated pull-up",
            )
        )
        assert upd_bom is not None

        # 8. Delete BOM part
        del_bom = live_proxy.delete_bom_part(ids=assignment_id, project_id=proj_id)
        assert del_bom is True

    finally:
        # 9. Delete temporary project
        deleted = live_proxy.delete_project(proj_id)
        assert deleted is True
