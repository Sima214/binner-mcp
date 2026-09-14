"""Part types / category taxonomy management endpoints for Binner API."""

from typing import Any, Dict, List, Optional, Union

from binner_mcp.api.models import (
    CreatePartTypeRequest,
    PartTypeResponse,
    UpdatePartTypeRequest,
)


class PartTypesMixin:
    """Mixin implementing Binner part type taxonomy REST endpoints."""

    def get_part_types(self, parent: Optional[str] = None) -> List[PartTypeResponse]:
        """
        Fetch part types (categories).

        If parent is provided, calls GET /api/parttype/list?parent=... to get subcategories with recursive part counts.
        Otherwise, calls GET /api/parttype/all.
        """
        if parent:
            resp = self._execute_request("GET", "/api/parttype/list", params={"parent": parent})
        else:
            resp = self._execute_request("GET", "/api/parttype/all")
        data = resp.json()
        return [PartTypeResponse.model_validate(item) for item in data]

    def create_part_type(
        self,
        part_type: Union[CreatePartTypeRequest, Dict[str, Any]],
    ) -> PartTypeResponse:
        """Create a new part category (POST /api/parttype)."""
        if isinstance(part_type, CreatePartTypeRequest):
            payload = part_type.model_dump(by_alias=True, exclude_none=True)
        else:
            validated = CreatePartTypeRequest.model_validate(part_type)
            payload = validated.model_dump(by_alias=True, exclude_none=True)

        resp = self._execute_request("POST", "/api/parttype", json=payload)
        return PartTypeResponse.model_validate(resp.json())

    def update_part_type(
        self,
        part_type: Union[UpdatePartTypeRequest, Dict[str, Any]],
    ) -> PartTypeResponse:
        """Update an existing part category (PUT /api/parttype)."""
        if isinstance(part_type, UpdatePartTypeRequest):
            payload = part_type.model_dump(by_alias=True, exclude_none=True)
        else:
            validated = UpdatePartTypeRequest.model_validate(part_type)
            payload = validated.model_dump(by_alias=True, exclude_none=True)

        resp = self._execute_request("PUT", "/api/parttype", json=payload)
        return PartTypeResponse.model_validate(resp.json())

    def delete_part_type(self, part_type_id: int) -> bool:
        """Delete an existing part type by ID."""
        resp = self._execute_request(
            "DELETE",
            "/api/parttype",
            json={"partTypeId": part_type_id},
        )
        return resp.status_code == 200
