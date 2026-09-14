"""Unit tests for parts querying, filtering, chunking, and bulk importing in BinnerAPIProxy."""
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.models import (
    AuthenticatedTokens,
    BulkImportItem,
    BulkImportResponse,
    PaginatedResponse,
    PartResponse,
)


def test_get_part_barcode(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    proxy.tokens = AuthenticatedTokens(imagesToken="token_xyz_123")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.content = b"\x89PNG\r\n\x1a\nfake_barcode_data"

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        barcode_bytes = proxy.get_part_barcode("RES-10K")
        assert barcode_bytes == mock_resp.content
        mock_exec.assert_called_once_with(
            "GET",
            "/api/part/barcode",
            params={"partNumber": "RES-10K", "token": "token_xyz_123"},
        )


def test_print_part_label(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    proxy._cache_part(42, "RES-10K")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.content = b"\x89PNG\r\n\x1a\nfake_label_data"

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        label_bytes = proxy.print_part_label(part_id=42, generate_image_only=True)
        assert label_bytes == mock_resp.content
        mock_exec.assert_called_once_with(
            "POST",
            "/api/part/print",
            params={"generateImageOnly": "true", "partNumber": "RES-10K", "partId": 42},
        )


def test_import_parts_csv_mock(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    csv_text = (
        "partNumber,description,quantity,location,binNumber\n"
        "RES-1K,1k resistor,100,Room1,BinA\n"
        "CAP-10UF,10uF capacitor,50,Room1,BinB\n"
    )

    created_mock = [
        PartResponse.model_validate({"partId": 1, "partNumber": "RES-1K", "quantity": 100}),
        PartResponse.model_validate({"partId": 2, "partNumber": "CAP-10UF", "quantity": 50}),
    ]

    with patch.object(proxy, "create_part", side_effect=created_mock) as mock_create:
        parts = proxy.import_parts_csv(csv_text)
        assert len(parts) == 2
        assert parts[0].part_number == "RES-1K"
        assert parts[1].part_number == "CAP-10UF"
        assert mock_create.call_count == 2


def test_list_parts_single_page(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "totalItems": 1,
        "pageSize": 20,
        "totalPages": 1,
        "pageNumber": 1,
        "items": [{"partId": 42, "partNumber": "P-42", "quantity": 10}],
    }

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        result = proxy.list_parts(page=1, results=20)
        assert result.total_items == 1
        assert len(result.items) == 1
        assert result.items[0].part_number == "P-42"
        mock_exec.assert_called_once_with(
            "GET",
            "/api/part/list",
            params={"direction": "Descending", "page": 1, "results": 20},
        )
        assert proxy._part_id_to_number[42] == "P-42"


def test_list_parts_all_inventory_chunking(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True

    def mock_execute(method: str, path: str, params: Optional[Dict[str, Any]] = None, **kwargs: Any) -> MagicMock:
        assert path == "/api/part/list"
        page = params.get("page", 1)
        chunk_results = params.get("results", 1000)
        assert chunk_results == 1000

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True

        if page == 1:
            items = [{"partId": i, "partNumber": f"P-{i}"} for i in range(1, 1001)]
        elif page == 2:
            items = [{"partId": i, "partNumber": f"P-{i}"} for i in range(1001, 2001)]
        elif page == 3:
            items = [{"partId": i, "partNumber": f"P-{i}"} for i in range(2001, 2501)]
        else:
            items = []

        mock_resp.json.return_value = {
            "totalItems": 2500,
            "pageSize": 1000,
            "totalPages": 3,
            "pageNumber": page,
            "items": items,
        }
        return mock_resp

    with patch.object(proxy, "_execute_request", side_effect=mock_execute) as mock_exec:
        result = proxy.list_parts(results=None)
        assert mock_exec.call_count == 3
        assert result.total_items == 2500
        assert len(result.items) == 2500
        assert result.items[0].part_number == "P-1"
        assert result.items[-1].part_number == "P-2500"
        assert proxy._part_id_to_number[1] == "P-1"
        assert proxy._part_id_to_number[2500] == "P-2500"


def test_list_parts_large_limit_chunking(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    requested_chunks = []

    def mock_execute(method: str, path: str, params: Optional[Dict[str, Any]] = None, **kwargs: Any) -> MagicMock:
        page = params.get("page", 1)
        results = params.get("results")
        requested_chunks.append((page, results))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        items = [{"partId": i, "partNumber": f"P-{i}"} for i in range(1, results + 1)]
        mock_resp.json.return_value = {
            "totalItems": 3000,
            "pageSize": results,
            "totalPages": 3,
            "pageNumber": page,
            "items": items,
        }
        return mock_resp

    with patch.object(proxy, "_execute_request", side_effect=mock_execute):
        res = proxy.list_parts(results=1500)
        assert requested_chunks == [(1, 1000), (2, 500)]
        assert len(res.items) == 1500
        assert res.page_size == 1500


def test_list_parts_filter_assembly(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "totalItems": 0,
        "pageSize": 20,
        "totalPages": 0,
        "pageNumber": 1,
        "items": [],
    }

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        proxy.list_parts(
            bin_number="BIN-A1",
            bin_number2="2",
            part_type="Capacitor",
            keyword="0.1uF",
            order_by="PartNumber",
            direction="Ascending",
            filters={"location": "Lab 1", "mounting_type": "SMD"},
        )
        call_params = mock_exec.call_args[1]["params"]
        assert call_params["direction"] == "Ascending"
        assert call_params["orderBy"] == "PartNumber"
        assert call_params["keyword"] == "0.1uF"

        by_fields = call_params["by"].split(",")
        val_fields = call_params["value"].split(",")
        field_map = dict(zip(by_fields, val_fields))

        assert field_map["binNumber"] == "BIN-A1"
        assert field_map["binNumber2"] == "2"
        assert field_map["partType"] == "Capacitor"
        assert field_map["location"] == "Lab 1"
        assert field_map["mountingType"] == "SMD"


def test_get_part_by_id_and_part_number_by_id(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True

    # 1. get_part_by_id on cache miss queries list_parts(by="partId", value=...)
    mock_part = PartResponse.model_validate({"partId": 333, "partNumber": "IC-555"})
    mock_paginated = PaginatedResponse[PartResponse](
        totalItems=1,
        pageSize=1,
        totalPages=1,
        pageNumber=1,
        items=[mock_part],
    )

    with patch.object(proxy, "list_parts", return_value=mock_paginated) as mock_list:
        part = proxy.get_part_by_id(333)
        assert part is not None
        assert part.part_id == 333
        assert part.part_number == "IC-555"
        mock_list.assert_called_once_with(by="partId", value="333", results=1)
        assert proxy._part_id_to_number[333] == "IC-555"

    # 2. get_part_number_by_id on cache hit returns immediately without query
    with patch.object(proxy, "get_part_by_id") as mock_fetch:
        pnum = proxy.get_part_number_by_id(333)
        assert pnum == "IC-555"
        mock_fetch.assert_not_called()

    # 3. get_part_number_by_id on cache miss delegates to get_part_by_id
    with patch.object(proxy, "get_part_by_id", return_value=PartResponse.model_validate({"partId": 444, "partNumber": "RES-444"})):
        pnum = proxy.get_part_number_by_id(444)
        assert pnum == "RES-444"


def test_get_low_stock_filters_and_chunking(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "totalItems": 1,
        "pageSize": 50,
        "totalPages": 1,
        "pageNumber": 1,
        "items": [{"partId": 77, "partNumber": "LOW-01", "quantity": 2, "lowStockThreshold": 5}],
    }

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        result = proxy.get_low_stock(
            bin_number="LOW-BIN-1",
            part_type="Resistor",
            keyword="10K",
            order_by="PartNumber",
            direction="Ascending",
        )
        assert result.total_items == 1
        assert result.items[0].part_number == "LOW-01"
        assert proxy._part_id_to_number[77] == "LOW-01"

        call_params = mock_exec.call_args[1]["params"]
        assert call_params["direction"] == "Ascending"
        assert call_params["orderBy"] == "PartNumber"
        assert call_params["keyword"] == "10K"
        by_fields = call_params["by"].split(",")
        val_fields = call_params["value"].split(",")
        field_map = dict(zip(by_fields, val_fields))
        assert field_map["binNumber"] == "LOW-BIN-1"
        assert field_map["partType"] == "Resistor"


def test_filter_parts_disjunctive(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "totalItems": 2,
        "pageSize": 20,
        "totalPages": 1,
        "pageNumber": 1,
        "items": [
            {"partId": 10, "partNumber": "BIN-A"},
            {"partId": 20, "partNumber": "BIN-B"},
        ],
    }

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        result = proxy.filter_parts(
            bin_numbers=["BIN-A", "BIN-B"],
            part_types=["Resistor", "Capacitor"],
            locations=["Lab 1"],
            keywords="smd",
        )
        assert result.total_items == 2
        assert len(result.items) == 2
        call_params = mock_exec.call_args[1]["params"]
        assert call_params["binNumbers"] == "BIN-A,BIN-B"
        assert call_params["partTypes"] == "Resistor,Capacitor"
        assert call_params["locations"] == "Lab 1"
        assert call_params["keywords"] == "smd"


def test_bulk_import_parts(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "added": [{"partId": 100, "partNumber": "BULK-ADD-01", "quantity": 10}],
        "updated": [{"partId": 101, "partNumber": "BULK-UPD-01", "quantity": 25}],
    }

    items = [
        BulkImportItem(partNumber="BULK-ADD-01", quantity=10, location="Room A"),
        {"partNumber": "BULK-UPD-01", "quantity": 25, "location": "Room B"},
    ]

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        result = proxy.bulk_import_parts(items)
        assert isinstance(result, BulkImportResponse)
        assert len(result.added) == 1
        assert len(result.updated) == 1
        assert result.added[0].part_number == "BULK-ADD-01"
        assert result.updated[0].part_number == "BULK-UPD-01"

        # Cache hydration check
        assert proxy._part_id_to_number[100] == "BULK-ADD-01"
        assert proxy._part_id_to_number[101] == "BULK-UPD-01"
        mock_exec.assert_called_once()
        assert mock_exec.call_args[0] == ("POST", "/api/part/bulk")


def test_get_part_info(proxy: BinnerAPIProxy) -> None:
    proxy._is_logged_in = True
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "partNumber": "NE555P",
        "datasheetUrls": ["https://example.com/ne555.pdf"],
    }

    with patch.object(proxy, "_execute_request", return_value=mock_resp) as mock_exec:
        info = proxy.get_part_info("NE555P", supplier_part_numbers="Digikey:296-1411-5-ND")
        assert info["partNumber"] == "NE555P"
        mock_exec.assert_called_once_with(
            "GET",
            "/api/part/info",
            params={
                "partNumber": "NE555P",
                "partTypeId": "",
                "mountingTypeId": "",
                "supplierPartNumbers": "Digikey:296-1411-5-ND",
            },
        )
