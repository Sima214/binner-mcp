"""Unit tests for MCP payload normalization and change diff generation."""

from binner_mcp.mcp.normalization import compact_payload, generate_change_diff


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
