"""Parts inventory endpoints, pagination chunking, filtering, CRUD, and barcode printing."""

import math
from typing import Any, Dict, List, Literal, Optional, Union, overload
import requests

from binner_mcp.api.exceptions import BinnerNotFoundError
from binner_mcp.api.models import (
    CreatePartRequest,
    DashboardSummaryResponse,
    DeletePartRequest,
    PaginatedResponse,
    PartQuantityRequest,
    PartResponse,
    PartStoredFilesResponse,
    UpdatePartRequest,
)


class PartsMixin:
    """Mixin implementing Binner parts inventory REST endpoints."""

    def get_summary(self) -> DashboardSummaryResponse:
        """Fetch inventory dashboard metrics (unique parts, total parts, total cost, low stock count)."""
        resp = self._execute_request("GET", "/api/part/summary")
        return DashboardSummaryResponse.model_validate(resp.json())

    @overload
    def search_parts(
        self,
        keywords: Optional[str] = None,
        short_id: Optional[str] = None,
        *,
        exact_match: Literal[True],
    ) -> Optional[PartResponse]: ...

    @overload
    def search_parts(
        self,
        keywords: Optional[str] = None,
        short_id: Optional[str] = None,
        *,
        exact_match: Literal[False] = False,
    ) -> List[PartResponse]: ...

    @overload
    def search_parts(
        self,
        keywords: Optional[str] = None,
        short_id: Optional[str] = None,
        exact_match: bool = False,
    ) -> Union[Optional[PartResponse], List[PartResponse]]: ...

    def search_parts(
        self,
        keywords: Optional[str] = None,
        short_id: Optional[str] = None,
        exact_match: bool = False,
    ) -> Union[Optional[PartResponse], List[PartResponse]]:
        """
        Search inventory parts via Binner's legacy search endpoint (GET /api/part/search).

        .. deprecated:: Upstream Binner v2.x
           This endpoint is largely abandoned in upstream development and superseded by
           `list_parts()` (GET /api/part/list) and `filter_parts()` (GET /api/part/filter).

        Known Upstream Backend Deficiencies:
        1. **Broken Relevance Ranking**: Although `EntityFrameworkStorageProvider.cs`
           builds a multi-tier CTE ranking (ExactMatch=10, BeginsWith=100, Any=200),
           line 217 hardcodes the result rank to 0 (`new SearchResult<Part>(..., 0)`).
           As a result, controller sorting `.OrderBy(x => x.Rank)` in `PartController.cs:713`
           is non-functional and results return in arbitrary database storage order.
        2. **No Pagination or Sorting**: Does not support `page`, `results`, `orderBy`,
           or `direction`. Broad keyword queries load the entire matching inventory
           into server memory and return an unbounded payload.
        3. **Polymorphic / Non-Standard HTTP Semantics**:
           - `exact_match=True`: Returns a single JSON `PartResponse` (200 OK).
           - `exact_match=False`: Returns a JSON array `List[PartResponse]` (200 OK).
           - `short_id`: Returns a JSON array `List[PartResponse]` (200 OK).
           - No match found: Returns HTTP 404 NotFound (caught by proxy and returned
             as None or []).

        Recommended Usage & Modern Alternatives:
        - **General / Keyword Search**: Use `list_parts(keyword="...")` for paginated,
          sorted SQL LIKE substring search across all part fields (part number,
          supplier numbers, descriptions, custom fields, footprints, etc.).
        - **Disjunctive Multi-Field Search**: Use `filter_parts(...)` for OR-based
          criteria matching with pagination and sorting support.
        - **Deterministic Part Lookup**: Use `get_part_by_number(part_number)`
          (GET /api/part?partNumber=...) or `get_part_by_id(part_id)`.
        - **ShortId Lookup**: Use this method `search_parts(short_id="...")` if you
          only have a Binner shortId and need to resolve it.

        Args:
            keywords: Keyword substring or exact part number to search.
            short_id: Optional unique short identifier string (e.g. "SH-1234").
            exact_match: If True, performs exact part number lookup and returns
                a single PartResponse (or None). If False, returns List[PartResponse].

        Returns:
            - `Optional[PartResponse]` when `exact_match=True`.
            - `List[PartResponse]` when `exact_match=False` or querying by `short_id`.
        """
        params: Dict[str, Any] = {"exactMatch": exact_match}
        if keywords is not None:
            params["keywords"] = keywords
        if short_id is not None:
            params["shortId"] = short_id

        try:
            resp = self._execute_request("GET", "/api/part/search", params=params)
            data = resp.json()

            if exact_match:
                part = PartResponse.model_validate(data)
                self._cache_part(part.part_id, part.part_number)
                return part

            if isinstance(data, list):
                parts = [PartResponse.model_validate(item) for item in data]
                self._cache_parts(parts)
                return parts

            part = PartResponse.model_validate(data)
            self._cache_part(part.part_id, part.part_number)
            return [part]
        except BinnerNotFoundError:
            if exact_match and keywords:
                return None
            return []

    @staticmethod
    def __build_filter_params(
        order_by: Optional[str] = None,
        direction: Union[str, int] = "Descending",
        keyword: Optional[str] = None,
        by: Optional[Union[str, List[str]]] = None,
        value: Optional[Union[str, List[str], Any]] = None,
        part_type: Optional[str] = None,
        part_type_id: Optional[int] = None,
        bin_number: Optional[str] = None,
        bin_number2: Optional[str] = None,
        location: Optional[str] = None,
        manufacturer: Optional[str] = None,
        package_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        filter_dict: Dict[str, str] = {}

        if by is not None and value is not None:
            by_keys = [b.strip() for b in by.split(",")] if isinstance(by, str) else list(by)
            val_vals = (
                [v.strip() for v in value.split(",")]
                if isinstance(value, str)
                else [str(v) for v in value]
            )
            for k, v in zip(by_keys, val_vals):
                if k:
                    filter_dict[k] = str(v)

        convenience_mappings = [
            ("partType", part_type),
            ("partTypeId", part_type_id),
            ("binNumber", bin_number),
            ("binNumber2", bin_number2),
            ("location", location),
            ("manufacturer", manufacturer),
            ("packageType", package_type),
        ]
        for field_name, field_val in convenience_mappings:
            if field_val is not None and field_name not in filter_dict:
                filter_dict[field_name] = str(field_val)

        if filters:
            for k, v in filters.items():
                if v is not None:
                    parts = k.split("_")
                    camel_k = (
                        parts[0] + "".join(word.capitalize() for word in parts[1:])
                        if len(parts) > 1
                        else k
                    )
                    if camel_k not in filter_dict:
                        filter_dict[camel_k] = str(v)

        base_params: Dict[str, Any] = {"direction": direction}
        if order_by:
            base_params["orderBy"] = order_by
        if keyword:
            base_params["keyword"] = keyword
        if filter_dict:
            base_params["by"] = ",".join(filter_dict.keys())
            base_params["value"] = ",".join(filter_dict.values())

        return base_params

    def __fetch_paginated_parts(
        self,
        endpoint: str,
        base_params: Dict[str, Any],
        page: int = 1,
        results: Optional[int] = 20,
    ) -> PaginatedResponse[PartResponse]:
        with self._lock:
            # Case 1: Fetch all items (results is None or results <= 0)
            if results is None or results <= 0:
                all_items: List[PartResponse] = []
                curr_page = 1
                chunk_size = 1000

                while True:
                    p_params = dict(base_params)
                    p_params["page"] = curr_page
                    p_params["results"] = chunk_size
                    resp = self._execute_request("GET", endpoint, params=p_params)
                    paginated = PaginatedResponse[PartResponse].model_validate(resp.json())
                    all_items.extend(paginated.items)
                    self._cache_parts(paginated.items)

                    if curr_page >= paginated.total_pages or not paginated.items:
                        break
                    curr_page += 1

                total = len(all_items)
                return PaginatedResponse[PartResponse](
                    totalItems=total,
                    pageSize=total,
                    totalPages=1 if total > 0 else 0,
                    pageNumber=1,
                    items=all_items,
                )

            # Case 2: Fetch large specific limit (> 1000)
            if results > 1000:
                all_items = []
                curr_page = page
                remaining = results
                total_reported = 0

                while remaining > 0:
                    chunk_size = min(1000, remaining)
                    p_params = dict(base_params)
                    p_params["page"] = curr_page
                    p_params["results"] = chunk_size
                    resp = self._execute_request("GET", endpoint, params=p_params)
                    paginated = PaginatedResponse[PartResponse].model_validate(resp.json())
                    total_reported = paginated.total_items
                    all_items.extend(paginated.items)
                    self._cache_parts(paginated.items)

                    remaining -= len(paginated.items)
                    if curr_page >= paginated.total_pages or not paginated.items:
                        break
                    curr_page += 1

                return PaginatedResponse[PartResponse](
                    totalItems=total_reported,
                    pageSize=results,
                    totalPages=math.ceil(total_reported / results) if results > 0 else 1,
                    pageNumber=page,
                    items=all_items,
                )

            # Case 3: Standard single-page fetch (1 <= results <= 1000)
            p_params = dict(base_params)
            p_params["page"] = page
            p_params["results"] = results
            resp = self._execute_request("GET", endpoint, params=p_params)
            paginated = PaginatedResponse[PartResponse].model_validate(resp.json())
            self._cache_parts(paginated.items)
            return paginated

    def list_parts(
        self,
        page: int = 1,
        results: Optional[int] = 20,
        order_by: Optional[str] = None,
        direction: Union[str, int] = "Descending",
        keyword: Optional[str] = None,
        by: Optional[Union[str, List[str]]] = None,
        value: Optional[Union[str, List[str], Any]] = None,
        part_type: Optional[str] = None,
        part_type_id: Optional[int] = None,
        bin_number: Optional[str] = None,
        bin_number2: Optional[str] = None,
        location: Optional[str] = None,
        manufacturer: Optional[str] = None,
        package_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> PaginatedResponse[PartResponse]:
        """
        Fetch parts from Binner inventory with comprehensive filtering, sorting, and pagination.

        API Endpoint: GET /api/part/list
        """
        base_params = self.__build_filter_params(
            order_by=order_by,
            direction=direction,
            keyword=keyword,
            by=by,
            value=value,
            part_type=part_type,
            part_type_id=part_type_id,
            bin_number=bin_number,
            bin_number2=bin_number2,
            location=location,
            manufacturer=manufacturer,
            package_type=package_type,
            filters=filters,
        )
        return self.__fetch_paginated_parts("/api/part/list", base_params, page=page, results=results)

    def get_part_by_id(self, part_id: int) -> Optional[PartResponse]:
        """Fetch a part by its unique numeric partId using GET /api/part/list?by=partId&value=<part_id>."""
        with self._lock:
            res = self.list_parts(by="partId", value=str(part_id), results=1)
            if res.items:
                part = res.items[0]
                self._cache_part(part.part_id, part.part_number)
                return part
            return None

    def get_part_number_by_id(self, part_id: int) -> Optional[str]:
        """Lookup the partNumber string for a given numeric partId."""
        with self._lock:
            if part_id in self._part_id_to_number:
                return self._part_id_to_number[part_id]

            part = self.get_part_by_id(part_id)
            if part and part.part_number:
                return part.part_number
            return None

    def get_part_by_number(self, part_number: str) -> Optional[PartStoredFilesResponse]:
        """Fetch part details and attached files by primary part number (GET /api/part?partNumber=<pn>)."""
        try:
            resp = self._execute_request("GET", "/api/part", params={"partNumber": part_number})
            part = PartStoredFilesResponse.model_validate(resp.json())
            self._cache_part(part.part_id, part.part_number)
            return part
        except BinnerNotFoundError:
            return None

    def get_low_stock(
        self,
        page: int = 1,
        results: Optional[int] = 50,
        order_by: Optional[str] = None,
        direction: Union[str, int] = "Descending",
        keyword: Optional[str] = None,
        by: Optional[Union[str, List[str]]] = None,
        value: Optional[Union[str, List[str], Any]] = None,
        part_type: Optional[str] = None,
        part_type_id: Optional[int] = None,
        bin_number: Optional[str] = None,
        bin_number2: Optional[str] = None,
        location: Optional[str] = None,
        manufacturer: Optional[str] = None,
        package_type: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> PaginatedResponse[PartResponse]:
        """Fetch parts currently below their low-stock threshold with comprehensive filtering (GET /api/part/low)."""
        base_params = self.__build_filter_params(
            order_by=order_by,
            direction=direction,
            keyword=keyword,
            by=by,
            value=value,
            part_type=part_type,
            part_type_id=part_type_id,
            bin_number=bin_number,
            bin_number2=bin_number2,
            location=location,
            manufacturer=manufacturer,
            package_type=package_type,
            filters=filters,
        )
        return self.__fetch_paginated_parts("/api/part/low", base_params, page=page, results=results)

    def filter_parts(
        self,
        part_names: Optional[Union[str, List[str]]] = None,
        values: Optional[Union[str, List[str]]] = None,
        part_types: Optional[Union[str, List[str]]] = None,
        keywords: Optional[Union[str, List[str]]] = None,
        manufacturers: Optional[Union[str, List[str]]] = None,
        mounting_types: Optional[Union[str, List[str]]] = None,
        locations: Optional[Union[str, List[str]]] = None,
        bin_numbers: Optional[Union[str, List[str]]] = None,
        bin_numbers2: Optional[Union[str, List[str]]] = None,
        order_by: Optional[str] = "DateCreatedUtc",
        direction: Union[str, int] = "Descending",
        page: int = 1,
        results: Optional[int] = 20,
    ) -> PaginatedResponse[PartResponse]:
        """Fetch parts matching disjunctive (OR) criteria across multiple fields (GET /api/part/filter)."""
        base_params: Dict[str, Any] = {"direction": direction}
        if order_by:
            base_params["orderBy"] = order_by

        param_mappings = [
            ("partNames", part_names),
            ("values", values),
            ("partTypes", part_types),
            ("keywords", keywords),
            ("manufacturers", manufacturers),
            ("mountingTypes", mounting_types),
            ("locations", locations),
            ("binNumbers", bin_numbers),
            ("binNumbers2", bin_numbers2),
        ]
        for param_name, param_val in param_mappings:
            if param_val is not None:
                if isinstance(param_val, str):
                    base_params[param_name] = param_val
                else:
                    base_params[param_name] = ",".join(str(v).strip() for v in param_val if str(v).strip())

        return self.__fetch_paginated_parts("/api/part/filter", base_params, page=page, results=results)

    def create_part(
        self,
        part: Union[CreatePartRequest, Dict[str, Any]],
    ) -> PartResponse:
        """Create a new component in Binner inventory (POST /api/part)."""
        if isinstance(part, CreatePartRequest):
            payload = part.model_dump(by_alias=True, exclude_none=True)
        else:
            validated = CreatePartRequest.model_validate(part)
            payload = validated.model_dump(by_alias=True, exclude_none=True)

        resp = self._execute_request("POST", "/api/part", json=payload)
        created = PartResponse.model_validate(resp.json())
        self._cache_part(created.part_id, created.part_number)
        return created

    def update_part(
        self,
        part: Union[UpdatePartRequest, Dict[str, Any]],
    ) -> PartResponse:
        """Update an existing component and/or set absolute on-hand quantity (PUT /api/part)."""
        if isinstance(part, UpdatePartRequest):
            payload = part.model_dump(by_alias=True, exclude_none=True)
        else:
            validated = UpdatePartRequest.model_validate(part)
            payload = validated.model_dump(by_alias=True, exclude_none=True)

        resp = self._execute_request("PUT", "/api/part", json=payload)
        updated = PartResponse.model_validate(resp.json())
        self._cache_part(updated.part_id, updated.part_number)
        return updated

    def delete_part(self, part_id: int) -> bool:
        """Delete an existing part by ID (DELETE /api/part)."""
        payload = DeletePartRequest(partId=part_id).model_dump(by_alias=True)
        resp = self._execute_request("DELETE", "/api/part", json=payload)
        if resp.status_code == 200:
            self._uncache_part(part_id)
            return True
        return False

    def update_quantity(
        self,
        part_id: Optional[int] = None,
        part_number: Optional[str] = None,
        quantity: int = 1,
        reason: Optional[str] = None,
    ) -> PartResponse:
        """
        Adjust the on-hand inventory quantity by an additive delta (POST /api/part/quantity).

        IMPORTANT: Binner applies an additive delta (entity.Quantity += quantity), NOT an absolute replacement.
        """
        part_id, part_number = self._resolve_part_identity(part_id, part_number)
        req = PartQuantityRequest(
            partId=part_id,
            partNumber=part_number,
            quantity=quantity,
            reason=reason,
        )
        payload = req.model_dump(by_alias=True, exclude_none=True)
        resp = self._execute_request("POST", "/api/part/quantity", json=payload)
        res = PartResponse.model_validate(resp.json())
        self._cache_part(res.part_id, res.part_number)
        return res

    def increment_quantity(
        self,
        part_id: Optional[int] = None,
        part_number: Optional[str] = None,
        quantity: int = 1,
    ) -> PartResponse:
        """Increment on-hand quantity by a positive amount (POST /api/part/quantity/increment)."""
        part_id, part_number = self._resolve_part_identity(part_id, part_number)
        req = PartQuantityRequest(
            partId=part_id,
            partNumber=part_number,
            quantity=quantity,
        )
        payload = req.model_dump(by_alias=True, exclude_none=True)
        resp = self._execute_request("POST", "/api/part/quantity/increment", json=payload)
        res = PartResponse.model_validate(resp.json())
        self._cache_part(res.part_id, res.part_number)
        return res

    def decrement_quantity(
        self,
        part_id: Optional[int] = None,
        part_number: Optional[str] = None,
        quantity: int = 1,
    ) -> PartResponse:
        """Decrement on-hand quantity by a positive amount (POST /api/part/quantity/decrement)."""
        part_id, part_number = self._resolve_part_identity(part_id, part_number)
        req = PartQuantityRequest(
            partId=part_id,
            partNumber=part_number,
            quantity=quantity,
        )
        payload = req.model_dump(by_alias=True, exclude_none=True)
        resp = self._execute_request("POST", "/api/part/quantity/decrement", json=payload)
        res = PartResponse.model_validate(resp.json())
        self._cache_part(res.part_id, res.part_number)
        return res

    def get_part_barcode(self, part_number: str) -> bytes:
        """
        Generate barcode image (PNG) for a given part number (GET /api/part/barcode).

        Requires the session imagesToken to be included in query parameters.
        """
        token = self.tokens.images_token if self.tokens else None
        params: Dict[str, Any] = {"partNumber": part_number}
        if token:
            params["token"] = token

        resp = self._execute_request("GET", "/api/part/barcode", params=params)
        return resp.content

    def print_part_label(
        self,
        part_id: Optional[int] = None,
        part_number: Optional[str] = None,
        printer_name: Optional[str] = None,
        template_name: Optional[str] = None,
        generate_image_only: bool = True,
    ) -> bytes:
        """
        Print or preview a component label (POST /api/part/print).

        Backend requirement: `partNumber` is strictly mandatory.
        """
        part_id, part_number = self._resolve_part_identity(part_id, part_number)
        params: Dict[str, Any] = {}
        if generate_image_only:
            params["generateImageOnly"] = "true"
        if part_number:
            params["partNumber"] = part_number
        if part_id is not None:
            params["partId"] = part_id
        if printer_name:
            params["printer"] = printer_name
        if template_name:
            params["template"] = template_name

        resp = self._execute_request("POST", "/api/part/print", params=params)
        return resp.content

    def get_part_info(
        self,
        part_number: str,
        part_type_id: str = "",
        mounting_type_id: str = "",
        supplier_part_numbers: str = "",
    ) -> Dict[str, Any]:
        """Query part metadata, datasheets, circuits, and distributor pricing (GET /api/part/info)."""
        params = {
            "partNumber": part_number,
            "partTypeId": part_type_id,
            "mountingTypeId": mounting_type_id,
            "supplierPartNumbers": supplier_part_numbers,
        }
        resp = self._execute_request("GET", "/api/part/info", params=params)
        return resp.json()
