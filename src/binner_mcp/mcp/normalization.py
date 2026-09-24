"""Context optimization and payload normalization utilities for Binner MCP server."""

from typing import Any, Dict, List, Union


_SENTINEL_STRINGS = {
    "0001-01-01T00:00:00Z",
    "0001-01-01T00:00:00",
    "0001-01-01",
    "00000000-0000-0000-0000-000000000000",
}


def compact_payload(obj: Any) -> Any:
    """
    Recursively prune None, empty strings, empty lists, empty dicts,
    uninitialized C# dates (DateTime.MinValue), and empty GUIDs from payload.

    Reduces token consumption significantly when returning Binner entities to LLMs.
    """
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(by_alias=False, exclude_none=True)

    if isinstance(obj, str):
        if obj in _SENTINEL_STRINGS:
            return None
        return obj

    if isinstance(obj, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in obj.items():
            compacted_v = compact_payload(v)
            if (
                compacted_v is not None
                and compacted_v != ""
                and compacted_v != []
                and compacted_v != {}
            ):
                cleaned[k] = compacted_v
        return cleaned

    if isinstance(obj, list):
        cleaned_list: List[Any] = []
        for item in obj:
            compacted_item = compact_payload(item)
            if (
                compacted_item is not None
                and compacted_item != ""
                and compacted_item != []
                and compacted_item != {}
            ):
                cleaned_list.append(compacted_item)
        return cleaned_list

    return obj


def format_lean_bom(bom_raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Normalize raw Binner Bill of Materials into lean, non-redundant line items.

    Eliminates duplicated nested part records, uninitialized dates, and conflicting
    quantity fields, delivering an ~75% context reduction.
    """
    if not isinstance(bom_raw, dict):
        return []

    raw_parts = bom_raw.get("parts") or bom_raw.get("Parts") or []
    lean_items: List[Dict[str, Any]] = []

    for assignment in raw_parts:
        if not isinstance(assignment, dict):
            continue

        part_obj = assignment.get("part") or assignment.get("Part") or {}
        pn = assignment.get("partNumber") or part_obj.get("partNumber") or assignment.get("partName")
        pid = assignment.get("partId") or part_obj.get("partId")
        assign_id = assignment.get("projectPartAssignmentId")
        qty = assignment.get("quantity") or 1
        ref_des = assignment.get("notes") or assignment.get("referenceDesignator")
        on_hand = part_obj.get("quantity")
        pkg = part_obj.get("packageType")

        item = {
            "assignment_id": assign_id,
            "part_id": pid,
            "part_number": pn,
            "quantity": qty,
            "reference_designator": ref_des,
            "stock_on_hand": on_hand,
            "package_type": pkg,
        }
        compacted = compact_payload(item)
        if compacted:
            lean_items.append(compacted)

    return lean_items


def generate_change_diff(
    old_data: Dict[str, Any],
    new_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Generate a concise change diff summary between two dictionaries.

    Adheres strictly to the lean null-trimming rule:
      - Never emits 'from': null when a property was previously unset.
      - Emits 'cleared': True if a property was emptied or removed.
      - Includes 'delta' for numeric value changes.
    """
    changes: Dict[str, Any] = {}
    all_keys = set(old_data.keys()).union(new_data.keys())

    for key in sorted(all_keys):
        old_val = old_data.get(key)
        new_val = new_data.get(key)

        if old_val == new_val:
            continue

        entry: Dict[str, Any] = {}
        if old_val is not None and old_val != "":
            entry["from"] = old_val

        if new_val is not None and new_val != "":
            entry["to"] = new_val
        else:
            entry["cleared"] = True

        if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
            entry["delta"] = round(new_val - old_val, 4)

        changes[key] = entry

    return changes
