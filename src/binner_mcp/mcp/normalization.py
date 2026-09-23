"""Context optimization and payload normalization utilities for Binner MCP server."""

from typing import Any, Dict, List, Union


def compact_payload(obj: Any) -> Any:
    """
    Recursively prune None, empty strings, empty lists, and empty dicts from payload.

    Reduces token consumption by 60-75% (allegedly) when returning Binner entities to LLMs.
    """
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(by_alias=False, exclude_none=True)

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
