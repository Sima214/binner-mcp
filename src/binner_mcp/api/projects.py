"""Projects and Bill of Materials (BOM) management endpoints for Binner API."""

from typing import Any, Dict, List, Optional, Union

from binner_mcp.api.exceptions import BinnerNotFoundError
from binner_mcp.api.models import (
    AddBomPartRequest,
    BomBasicResponse,
    CreateProjectRequest,
    ProjectResponse,
    RemoveBomPartRequest,
    UpdateBomPartRequest,
    UpdateProjectRequest,
)


class ProjectsMixin:
    """Mixin implementing Binner projects and BOM REST endpoints."""

    def get_projects(
        self,
        page: int = 1,
        results: Optional[int] = 20,
        order_by: Optional[str] = None,
        direction: Union[str, int] = "Ascending",
    ) -> List[ProjectResponse]:
        """
        Fetch list of maker projects.

        Normalizes order_by to PascalCase (e.g. 'name' -> 'Name', 'project_id' -> 'ProjectId')
        to prevent EF Core InvalidOperationException. Guards against passing 'by' parameter.
        Supports single-lock chunking for large results.
        """
        base_params: Dict[str, Any] = {"direction": direction}
        if order_by:
            parts = order_by.split("_")
            pascal_order = "".join(p[:1].upper() + p[1:] for p in parts if p)
            base_params["orderBy"] = pascal_order

        with self._lock:
            if results is None or results <= 0:
                all_projects: List[ProjectResponse] = []
                curr_page = 1
                while True:
                    p_params = dict(base_params)
                    p_params["page"] = curr_page
                    p_params["results"] = 1000
                    resp = self._execute_request("GET", "/api/project/list", params=p_params)
                    data = resp.json()
                    if not data:
                        break
                    all_projects.extend([ProjectResponse.model_validate(item) for item in data])
                    if len(data) < 1000:
                        break
                    curr_page += 1
                return all_projects

            if results > 1000:
                all_projects = []
                curr_page = page
                remaining = results
                while remaining > 0:
                    chunk = min(1000, remaining)
                    p_params = dict(base_params)
                    p_params["page"] = curr_page
                    p_params["results"] = chunk
                    resp = self._execute_request("GET", "/api/project/list", params=p_params)
                    data = resp.json()
                    if not data:
                        break
                    all_projects.extend([ProjectResponse.model_validate(item) for item in data])
                    remaining -= len(data)
                    if len(data) < chunk:
                        break
                    curr_page += 1
                return all_projects

            p_params = dict(base_params)
            p_params["page"] = page
            p_params["results"] = results
            resp = self._execute_request("GET", "/api/project/list", params=p_params)
            return [ProjectResponse.model_validate(item) for item in resp.json()]

    def get_project(
        self,
        project_id: Optional[int] = None,
        name: Optional[str] = None,
    ) -> Optional[ProjectResponse]:
        """Fetch a single project by ID or name."""
        params: Dict[str, Any] = {}
        if project_id is not None:
            params["projectId"] = project_id
        if name is not None:
            params["name"] = name

        try:
            resp = self._execute_request("GET", "/api/project", params=params)
            return ProjectResponse.model_validate(resp.json())
        except BinnerNotFoundError:
            return None

    def create_project(
        self,
        project: Union[CreateProjectRequest, Dict[str, Any]],
    ) -> ProjectResponse:
        """Create a new maker project."""
        if isinstance(project, CreateProjectRequest):
            payload = project.model_dump(by_alias=True, exclude_none=True)
        else:
            validated = CreateProjectRequest.model_validate(project)
            payload = validated.model_dump(by_alias=True, exclude_none=True)

        resp = self._execute_request("POST", "/api/project", json=payload)
        return ProjectResponse.model_validate(resp.json())

    def update_project(
        self,
        project: Union[UpdateProjectRequest, Dict[str, Any]],
    ) -> ProjectResponse:
        """Update an existing maker project (PUT /api/project)."""
        if isinstance(project, UpdateProjectRequest):
            payload = project.model_dump(by_alias=True, exclude_none=True)
        else:
            validated = UpdateProjectRequest.model_validate(project)
            payload = validated.model_dump(by_alias=True, exclude_none=True)

        resp = self._execute_request("PUT", "/api/project", json=payload)
        return ProjectResponse.model_validate(resp.json())

    def delete_project(self, project_id: int) -> bool:
        """Delete a project by ID."""
        resp = self._execute_request(
            "DELETE",
            "/api/project",
            json={"projectId": project_id},
        )
        return resp.status_code == 200

    def get_bom(
        self,
        project_id: Optional[int] = None,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch Bill of Materials for a project by ID or name (GET /api/bom)."""
        params: Dict[str, Any] = {}
        if project_id is not None:
            params["projectId"] = project_id
        if name is not None:
            params["name"] = name
        resp = self._execute_request("GET", "/api/bom", params=params)
        return resp.json()

    def add_bom_part(
        self,
        req: Union[AddBomPartRequest, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Add a part to a project's BOM (POST /api/bom/part)."""
        if isinstance(req, AddBomPartRequest):
            payload = req.model_dump(by_alias=True, exclude_none=True)
        else:
            validated = AddBomPartRequest.model_validate(req)
            payload = validated.model_dump(by_alias=True, exclude_none=True)

        resp = self._execute_request("POST", "/api/bom/part", json=payload)
        return resp.json()

    def update_bom_part(
        self,
        req: Union[UpdateBomPartRequest, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Update a part within a project's BOM (PUT /api/bom/part)."""
        if isinstance(req, UpdateBomPartRequest):
            payload = req.model_dump(by_alias=True, exclude_none=True)
        else:
            validated = UpdateBomPartRequest.model_validate(req)
            payload = validated.model_dump(by_alias=True, exclude_none=True)

        resp = self._execute_request("PUT", "/api/bom/part", json=payload)
        return resp.json()

    def delete_bom_part(
        self,
        ids: Union[int, List[int]],
        project_id: Optional[int] = None,
        project_name: Optional[str] = None,
    ) -> bool:
        """Remove one or more part assignments from a project's BOM (DELETE /api/bom/part)."""
        id_list = [ids] if isinstance(ids, int) else list(ids)
        req = RemoveBomPartRequest(
            projectId=project_id,
            project=project_name,
            ids=id_list,
        )
        resp = self._execute_request(
            "DELETE",
            "/api/bom/part",
            json=req.model_dump(by_alias=True, exclude_none=True),
        )
        return resp.status_code == 200

    def get_bom_list(
        self,
        page: int = 1,
        results: int = 20,
    ) -> List[BomBasicResponse]:
        """Fetch list of BOM projects with component counts."""
        resp = self._execute_request("GET", "/api/bom/list", params={"page": page, "results": results})
        data = resp.json()
        return [BomBasicResponse.model_validate(item) for item in data]
