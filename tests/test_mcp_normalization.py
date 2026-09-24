"""Unit tests for MCP payload normalization and change diff generation."""

from binner_mcp.mcp.normalization import compact_payload, format_lean_bom, generate_change_diff


def test_compact_payload_prunes_none_and_empty() -> None:
    data = {
        "id": 42,
        "part_number": "NE555P",
        "description": "",
        "empty_list": [],
        "empty_dict": {},
        "none_field": None,
        "nested": {
            "valid": "ok",
            "empty": "",
            "inner_none": None,
        },
        "list_of_dicts": [
            {"keep": 1, "drop": None},
            {"drop_all": ""},
        ],
    }
    cleaned = compact_payload(data)
    assert cleaned == {
        "id": 42,
        "part_number": "NE555P",
        "nested": {"valid": "ok"},
        "list_of_dicts": [{"keep": 1}],
    }


def test_compact_payload_preserves_zero_and_false() -> None:
    data = {
        "quantity": 0,
        "is_admin": False,
        "cost": 0.0,
        "name": "Component",
    }
    cleaned = compact_payload(data)
    assert cleaned == {
        "quantity": 0,
        "is_admin": False,
        "cost": 0.0,
        "name": "Component",
    }


def test_generate_change_diff_strict_null_trimming() -> None:
    old_data = {
        "part_number": "NE555P",
        "quantity": 10,
        "bin_number": "A1-02",
        "location": "Shelf 1",
    }
    new_data = {
        "part_number": "NE555P",
        "quantity": 15,
        "bin_number": "A1-02",  # unchanged
        "package_type": "DIP-8",  # new field (old was None)
        "location": "",  # cleared
    }

    diff = generate_change_diff(old_data, new_data)

    # 1. Unchanged fields omitted
    assert "part_number" not in diff
    assert "bin_number" not in diff

    # 2. Numeric delta computed
    assert diff["quantity"] == {"from": 10, "to": 15, "delta": 5}

    # 3. New field: NO "from": null emitted
    assert diff["package_type"] == {"to": "DIP-8"}
    assert "from" not in diff["package_type"]

    # 4. Cleared field
    assert diff["location"] == {"from": "Shelf 1", "cleared": True}


def test_compact_payload_prunes_sentinel_strings() -> None:
    data = {
        "id": 100,
        "created_date": "0001-01-01T00:00:00Z",
        "updated_date": "0001-01-01T00:00:00",
        "short_date": "0001-01-01",
        "guid": "00000000-0000-0000-0000-000000000000",
        "valid_date": "2026-09-23T12:00:00Z",
        "valid_guid": "12345678-1234-1234-1234-123456789abc",
    }
    cleaned = compact_payload(data)
    assert cleaned == {
        "id": 100,
        "valid_date": "2026-09-23T12:00:00Z",
        "valid_guid": "12345678-1234-1234-1234-123456789abc",
    }


def test_format_lean_bom_flattens_and_normalizes() -> None:
    raw_bom = {
        "parts": [
            {
                "projectPartAssignmentId": 56,
                "partId": 913,
                "partNumber": "QA_BOM_TEST_LED",
                "quantity": 2,
                "notes": "D1, D2",
                "part": {
                    "partId": 913,
                    "partNumber": "QA_BOM_TEST_LED",
                    "quantity": 100,
                    "packageType": "0805",
                    "dateCreated": "0001-01-01T00:00:00Z",
                    "customId": "00000000-0000-0000-0000-000000000000",
                },
            },
            {
                "projectPartAssignmentId": 57,
                "partId": 914,
                "partName": "10k Resistor",
                "quantity": 4,
                "referenceDesignator": "R1-R4",
                "part": {
                    "quantity": 500,
                    "packageType": "0603",
                },
            },
        ]
    }
    lean = format_lean_bom(raw_bom)
    assert len(lean) == 2
    assert lean[0] == {
        "assignment_id": 56,
        "part_id": 913,
        "part_number": "QA_BOM_TEST_LED",
        "quantity": 2,
        "reference_designator": "D1, D2",
        "stock_on_hand": 100,
        "package_type": "0805",
    }
    assert lean[1] == {
        "assignment_id": 57,
        "part_id": 914,
        "part_number": "10k Resistor",
        "quantity": 4,
        "reference_designator": "R1-R4",
        "stock_on_hand": 500,
        "package_type": "0603",
    }
