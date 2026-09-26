"""Unified argument validation utilities for Binner MCP server."""

from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel

from binner_mcp.mcp.categories import CategoryResolver


def validation_error_response(error_title: str, details: List[str]) -> Dict[str, Any]:
    """Build standardized Zero-Side-Effects pre-flight validation error payload."""
    return {
        "status": "error",
        "error": error_title,
        "details": details,
    }


def normalize_batch_input(
    items: Any,
    param_name: str,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
    """
    Validate that input is a non-empty list and unroll Pydantic models or dictionaries.

    Returns:
        (normalized_items, error_response)
        If validation succeeds, error_response is None.
        If validation fails, normalized_items is None and error_response contains structured details.
    """
    if not items or not isinstance(items, list):
        return None, validation_error_response(
            "Validation failed",
            [f"'{param_name}' must be a non-empty list of records."],
        )

    normalized: List[Dict[str, Any]] = []
    errors: List[str] = []

    for i, item in enumerate(items):
        if isinstance(item, BaseModel):
            normalized.append(item.model_dump(exclude_unset=True))
        elif isinstance(item, dict):
            normalized.append(dict(item))
        else:
            errors.append(f"Item {i} is not a valid record or dictionary.")

    if errors:
        return None, validation_error_response("Validation failed", errors)

    return normalized, None


def parse_int_id(val: Any, name: str = "id") -> Tuple[Optional[int], Optional[str]]:
    """
    Safely parse an integer ID.

    Returns:
        (parsed_id, error_message)
    """
    if val is None:
        return None, None
    try:
        val_int = int(val)
        return val_int, None
    except (ValueError, TypeError):
        return None, f"Invalid {name}: {val}"


def validate_non_negative_number(
    val: Any,
    name: str,
    is_int: bool = False,
) -> Optional[str]:
    """Validate that a numeric value is non-negative."""
    if val is None:
        return None
    if is_int:
        if not isinstance(val, int) or val < 0:
            return f"'{name}' must be an integer >= 0."
    else:
        if not isinstance(val, (int, float)) or val < 0:
            return f"'{name}' must be a number >= 0."
    return None


def resolve_part_category_input(
    raw_pt: Any,
    raw_ptid: Any,
    resolver: CategoryResolver,
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Resolve category assignment for inventory parts.

    Prefers the overloaded 'part_type' parameter (accepting category path strings,
    leaf names, or numeric IDs). Accepts 'part_type_id' as a fallback when 'part_type'
    is omitted.

    Returns:
        (resolved_id, resolved_path, error_str)
    """
    if raw_pt is not None:
        return resolver.resolve(raw_pt)

    if raw_ptid is not None:
        ptid, err = parse_int_id(raw_ptid, "part_type_id")
        if err:
            return None, None, err
        if ptid not in resolver.path_by_id:
            return None, None, f"Part type ID {ptid} does not exist in inventory."
        return ptid, resolver.path_by_id.get(ptid), None

    return None, None, None
