"""Integration tests for live Binner instance: parts CRUD, filtering, barcodes, and bulk import."""
import uuid
import pytest

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import BinnerAPIError, BinnerNotFoundError
from binner_mcp.api.models import (
    BulkImportItem,
    BulkImportResponse,
    CreatePartRequest,
    UpdatePartRequest,
)


def test_live_part_full_lifecycle(live_proxy: BinnerAPIProxy) -> None:
    test_pn = "TEST-MCP-PROXY-TEMP-001"

    # Pre-clean: delete if lingering from prior interrupted run
    existing = live_proxy.get_part_by_number(test_pn)
    if existing:
        live_proxy.delete_part(existing.part_id)

    # 1. Create part
    created = live_proxy.create_part(
        CreatePartRequest(
            partNumber=test_pn,
            quantity=10,
            cost=1.50,
            description="Automated proxy test component",
            location="Room 101",
            binNumber="BIN-A1",
            manufacturer="Texas Instruments",
            manufacturerPartNumber="TI-TEST-001",
        )
    )
    assert created.part_id > 0
    assert created.part_number == test_pn
    assert created.quantity == 10
    part_id = created.part_id

    try:
        # 2. Get part by part number
        fetched = live_proxy.get_part_by_number(test_pn)
        assert fetched is not None
        assert fetched.part_id == part_id
        assert fetched.location == "Room 101"
        assert fetched.bin_number == "BIN-A1"

        # 3. Update quantity (delta adjustment)
        updated_q = live_proxy.update_quantity(part_id=part_id, quantity=5, reason="Stock re-count")
        assert updated_q.quantity == 15

        # 4. Increment quantity
        inc_q = live_proxy.increment_quantity(part_id=part_id, quantity=10)
        assert inc_q.quantity == 25

        # 5. Decrement quantity
        dec_q = live_proxy.decrement_quantity(part_id=part_id, quantity=10)
        assert dec_q.quantity == 15

        # 6. Search exact
        exact_search = live_proxy.search_parts(keywords=test_pn, exact_match=True)
        assert exact_search is not None
        assert exact_search.part_id == part_id

        # 7. Search keyword
        fuzzy_search = live_proxy.search_parts(keywords="TEST-MCP-PROXY", exact_match=False)
        assert isinstance(fuzzy_search, list)
        assert any(p.part_id == part_id for p in fuzzy_search)

        # 8. Update part metadata
        updated_part = live_proxy.update_part(
            UpdatePartRequest(
                partId=part_id,
                partNumber=test_pn,
                description="Updated component description",
                quantity=40,
                location="Room 102",
                binNumber="BIN-A2",
            )
        )
        assert updated_part.location == "Room 102"
        assert updated_part.bin_number == "BIN-A2"
        assert updated_part.description == "Updated component description"

        # 9. Low stock listing
        low_stock = live_proxy.get_low_stock(page=1, results=10)
        assert low_stock.total_items >= 0

        # 10. Paginated part list
        part_list = live_proxy.list_parts(page=1, results=10)
        assert part_list.total_items >= 1

    finally:
        # 11. Clean up temporary test part
        deleted = live_proxy.delete_part(part_id)
        assert deleted is True
        assert live_proxy.get_part_by_number(test_pn) is None


def test_live_barcode_and_label_preview(live_proxy: BinnerAPIProxy) -> None:
    parts = live_proxy.list_parts(results=1)
    assert len(parts.items) > 0
    part = parts.items[0]

    # Barcode PNG generation
    barcode_data = live_proxy.get_part_barcode(part.part_number)
    assert isinstance(barcode_data, bytes)
    assert len(barcode_data) > 0
    assert barcode_data.startswith(b"\x89PNG")

    # Label preview PNG generation
    label_preview = live_proxy.print_part_label(
        part_number=part.part_number,
        part_id=part.part_id,
        generate_image_only=True,
    )
    assert isinstance(label_preview, bytes)
    assert len(label_preview) > 0
    assert label_preview.startswith(b"\x89PNG")


def test_live_cache_resolution_for_quantity(live_proxy: BinnerAPIProxy) -> None:
    live_proxy.export_data(populate_cache=True)
    part_id, part_number = next(iter(live_proxy._part_id_to_number.items()))

    res = live_proxy.update_quantity(part_id=part_id, quantity=0)
    assert res.part_id == part_id
    assert res.part_number == part_number


@pytest.mark.xfail(
    strict=True,
    raises=BinnerNotFoundError,
    reason="Upstream Binner omission: POST /api/part/quantity requires PartNumber when PartId is provided. Fails (XPASS) when upstream omission is resolved.",
)
def test_canary_upstream_omission_quantity_without_part_number(live_proxy: BinnerAPIProxy) -> None:
    parts = live_proxy.list_parts(results=1)
    assert len(parts.items) > 0
    part_id = parts.items[0].part_id

    resp = live_proxy._execute_request(
        "POST",
        "/api/part/quantity",
        json={"partId": part_id, "quantity": 0},
    )
    assert resp.status_code == 200


@pytest.mark.xfail(
    strict=True,
    raises=BinnerNotFoundError,
    reason="Upstream Binner omission: POST /api/part/quantity/increment requires PartNumber when PartId is provided. Fails (XPASS) when upstream omission is resolved.",
)
def test_canary_upstream_omission_increment_without_part_number(live_proxy: BinnerAPIProxy) -> None:
    parts = live_proxy.list_parts(results=1)
    assert len(parts.items) > 0
    part_id = parts.items[0].part_id

    resp = live_proxy._execute_request(
        "POST",
        "/api/part/quantity/increment",
        json={"partId": part_id, "quantity": 1},
    )
    assert resp.status_code == 200


@pytest.mark.xfail(
    strict=True,
    raises=BinnerNotFoundError,
    reason="Upstream Binner omission: POST /api/part/quantity/decrement requires PartNumber when PartId is provided. Fails (XPASS) when upstream omission is resolved.",
)
def test_canary_upstream_omission_decrement_without_part_number(live_proxy: BinnerAPIProxy) -> None:
    parts = live_proxy.list_parts(results=1)
    assert len(parts.items) > 0
    part_id = parts.items[0].part_id

    resp = live_proxy._execute_request(
        "POST",
        "/api/part/quantity/decrement",
        json={"partId": part_id, "quantity": 1},
    )
    assert resp.status_code == 200


@pytest.mark.xfail(
    strict=True,
    raises=BinnerAPIError,
    reason="Upstream Binner omission: POST /api/part/print requires PartNumber even when PartId is provided. Fails (XPASS) when upstream omission is resolved.",
)
def test_canary_upstream_omission_print_without_part_number(live_proxy: BinnerAPIProxy) -> None:
    parts = live_proxy.list_parts(results=1)
    assert len(parts.items) > 0
    part_id = parts.items[0].part_id

    resp = live_proxy._execute_request(
        "POST",
        "/api/part/print",
        params={"partId": part_id, "generateImageOnly": "true"},
    )
    assert resp.status_code == 200


def test_live_list_parts_and_filtering_with_dummy_data(live_proxy: BinnerAPIProxy) -> None:
    unique_suffix = uuid.uuid4().hex[:8]
    dummy_pn = f"TEST-LIST-{unique_suffix}"
    dummy_bin1 = f"BIN1-{unique_suffix[:4]}"
    dummy_bin2 = f"BIN2-{unique_suffix[4:]}"
    dummy_loc = f"Rack-{unique_suffix[:4]}"
    dummy_mfr = f"MfrCorp-{unique_suffix[:4]}"
    dummy_kw = f"KW-{unique_suffix}"

    created = live_proxy.create_part(
        {
            "partNumber": dummy_pn,
            "binNumber": dummy_bin1,
            "binNumber2": dummy_bin2,
            "location": dummy_loc,
            "manufacturer": dummy_mfr,
            "description": f"Dummy part description {dummy_kw}",
            "quantity": 15,
        }
    )
    part_id = created.part_id

    try:
        all_parts = live_proxy.list_parts(results=None)
        assert all_parts.total_items >= 1
        assert len(all_parts.items) == all_parts.total_items
        found_in_all = [p for p in all_parts.items if p.part_id == part_id]
        assert len(found_in_all) == 1
        assert found_in_all[0].part_number == dummy_pn

        filtered_bins = live_proxy.list_parts(bin_number=dummy_bin1, bin_number2=dummy_bin2)
        assert filtered_bins.total_items == 1
        assert filtered_bins.items[0].part_id == part_id

        filtered_loc_mfr = live_proxy.list_parts(location=dummy_loc, manufacturer=dummy_mfr)
        assert filtered_loc_mfr.total_items == 1
        assert filtered_loc_mfr.items[0].part_id == part_id

        filtered_kw = live_proxy.list_parts(keyword=dummy_kw)
        assert filtered_kw.total_items == 1
        assert filtered_kw.items[0].part_id == part_id

        resolved_pn = live_proxy.get_part_number_by_id(part_id)
        assert resolved_pn == dummy_pn

    finally:
        live_proxy.delete_part(part_id)
        assert live_proxy.get_part_by_id(part_id) is None


def test_live_low_stock_filtering(live_proxy: BinnerAPIProxy) -> None:
    unique_suffix = uuid.uuid4().hex[:8]
    dummy_pn = f"TEST-LOW-{unique_suffix}"
    dummy_bin = f"LOW-BIN-{unique_suffix[:4]}"

    created = live_proxy.create_part(
        {
            "partNumber": dummy_pn,
            "binNumber": dummy_bin,
            "quantity": 1,
            "lowStockThreshold": 5,
            "description": "Low stock test part",
        }
    )
    part_id = created.part_id

    try:
        low_stock = live_proxy.get_low_stock(bin_number=dummy_bin)
        assert low_stock.total_items >= 1
        assert any(p.part_id == part_id for p in low_stock.items)
    finally:
        live_proxy.delete_part(part_id)


def test_live_filter_parts_disjunctive(live_proxy: BinnerAPIProxy) -> None:
    unique_suffix = uuid.uuid4().hex[:8]
    dummy_pn = f"TEST-DISJ-{unique_suffix}"
    dummy_bin = f"DISJ-BIN-{unique_suffix[:4]}"

    created = live_proxy.create_part(
        {
            "partNumber": dummy_pn,
            "binNumber": dummy_bin,
            "quantity": 5,
            "description": "Disjunctive filter test part",
        }
    )
    part_id = created.part_id

    try:
        res = live_proxy.filter_parts(bin_numbers=[dummy_bin, "NONEXISTENT_BIN_XYZ"])
        assert res.total_items >= 1
        assert any(p.part_id == part_id for p in res.items)
    finally:
        live_proxy.delete_part(part_id)


def test_live_bulk_import_parts(live_proxy: BinnerAPIProxy) -> None:
    unique_suffix = uuid.uuid4().hex[:8]
    pn1 = f"TEST-BULK1-{unique_suffix}"
    pn2 = f"TEST-BULK2-{unique_suffix}"

    import_items = [
        BulkImportItem(partNumber=pn1, quantity=10, description="Bulk imported item 1"),
        BulkImportItem(partNumber=pn2, quantity=20, description="Bulk imported item 2"),
    ]

    resp = live_proxy.bulk_import_parts(import_items)
    assert isinstance(resp, BulkImportResponse)
    assert len(resp.added) + len(resp.updated) >= 2

    # Clean up both parts
    for pn in (pn1, pn2):
        part = live_proxy.get_part_by_number(pn)
        if part:
            live_proxy.delete_part(part.part_id)
