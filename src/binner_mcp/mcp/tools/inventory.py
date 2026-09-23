"""Synchronous implementation for inventory discovery, batched inspection, and mutation MCP tools."""

import logging
import time
from typing import Any, Dict, List, Optional, Set
import requests

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import BinnerError
from binner_mcp.mcp.normalization import compact_payload, generate_change_diff

logger = logging.getLogger("binner_mcp.mcp.tools.inventory")


def list_parts_sync(
    proxy: BinnerAPIProxy,
    query: Optional[str] = None,
    part_type: Optional[str] = None,
    bin_number: Optional[str] = None,
    location: Optional[str] = None,
    package_type: Optional[str] = None,
    manufacturer: Optional[str] = None,
    low_stock_only: bool = False,
    fields: Optional[List[str]] = None,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "DateCreatedUtc",
    direction: str = "Descending",
) -> Dict[str, Any]:
    """
    Search and filter parts inventory with selective field expansion.

    Default output returns only 'id' and 'part_number' (~6 tokens/part) to minimize LLM context.
    Additional fields are included only when explicitly requested in 'fields'.
    """
    limit = min(max(1, limit), 500)
    field_set = set(fields) if fields else set()

    with proxy._lock:
        if low_stock_only:
            paginated = proxy.get_low_stock(
                page=page,
                results=limit,
                order_by=sort_by,
                direction=direction,
                keyword=query,
                part_type=part_type,
                bin_number=bin_number,
                location=location,
                manufacturer=manufacturer,
                package_type=package_type,
            )
        else:
            paginated = proxy.list_parts(
                page=page,
                results=limit,
                order_by=sort_by,
                direction=direction,
                keyword=query,
                part_type=part_type,
                bin_number=bin_number,
                location=location,
                manufacturer=manufacturer,
                package_type=package_type,
            )

        formatted_parts: List[Dict[str, Any]] = []
        for item in paginated.items:
            part_dict: Dict[str, Any] = {
                "id": item.part_id,
                "part_number": item.part_number,
            }
            if "quantity" in field_set:
                part_dict["quantity"] = item.quantity
            if "low_stock_threshold" in field_set:
                part_dict["low_stock_threshold"] = item.low_stock_threshold
            if "description" in field_set:
                part_dict["description"] = item.description
            if "bin_number" in field_set:
                part_dict["bin_number"] = item.bin_number
            if "bin_number2" in field_set:
                part_dict["bin_number2"] = item.bin_number2
            if "location" in field_set:
                part_dict["location"] = item.location
            if "cost" in field_set:
                part_dict["cost"] = item.cost
            if "currency" in field_set:
                part_dict["currency"] = item.currency
            if "package_type" in field_set:
                part_dict["package_type"] = item.package_type
            if "part_type" in field_set:
                part_dict["part_type"] = item.part_type
            if "manufacturer" in field_set:
                part_dict["manufacturer"] = item.manufacturer
            if "manufacturer_part_number" in field_set:
                part_dict["manufacturer_part_number"] = item.manufacturer_part_number
            if "datasheet_url" in field_set:
                part_dict["datasheet_url"] = item.datasheet_url

            formatted_parts.append(compact_payload(part_dict))

        result = {
            "total_items": paginated.total_items,
            "page": paginated.page_number,
            "page_size": paginated.page_size,
            "total_pages": paginated.total_pages,
            "parts": formatted_parts,
        }
        return compact_payload(result)


def get_parts_sync(
    proxy: BinnerAPIProxy,
    category_cache: Dict[int, str],
    part_numbers: Optional[List[str]] = None,
    part_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Batched component inspection for 1 to N components.

    Retrieves full specifications, datasheets, supplier SKUs, and hierarchical category paths.
    """
    if not part_numbers and not part_ids:
        return {"parts": [], "not_found": []}

    parts_found: List[Dict[str, Any]] = []
    not_found: List[str] = []
    seen_ids: Set[int] = set()

    with proxy._lock:
        if part_numbers:
            for pn in part_numbers:
                pn_clean = str(pn).strip()
                if not pn_clean:
                    continue
                part = proxy.get_part_by_number(pn_clean)
                if not part:
                    not_found.append(pn_clean)
                else:
                    seen_ids.add(part.part_id)
                    category_path = category_cache.get(part.part_type_id) or part.part_type
                    rec = {
                        "id": part.part_id,
                        "part_number": part.part_number,
                        "quantity": part.quantity,
                        "low_stock_threshold": part.low_stock_threshold,
                        "cost": part.cost,
                        "currency": part.currency,
                        "bin_number": part.bin_number,
                        "bin_number2": part.bin_number2,
                        "location": part.location,
                        "package_type": part.package_type,
                        "part_type": category_path,
                        "manufacturer": part.manufacturer,
                        "manufacturer_part_number": part.manufacturer_part_number,
                        "description": part.description,
                        "datasheet_url": part.datasheet_url,
                        "product_url": part.product_url,
                    }
                    parts_found.append(compact_payload(rec))

        if part_ids:
            for pid in part_ids:
                try:
                    pid_int = int(pid)
                except (ValueError, TypeError):
                    not_found.append(str(pid))
                    continue

                if pid_int in seen_ids:
                    continue

                pn = proxy.get_part_number_by_id(pid_int)
                part = (proxy.get_part_by_number(pn) if pn else None) or proxy.get_part_by_id(pid_int)
                if not part:
                    not_found.append(str(pid_int))
                else:
                    seen_ids.add(part.part_id)
                    category_path = category_cache.get(part.part_type_id) or part.part_type
                    rec = {
                        "id": part.part_id,
                        "part_number": part.part_number,
                        "quantity": part.quantity,
                        "low_stock_threshold": part.low_stock_threshold,
                        "cost": part.cost,
                        "currency": part.currency,
                        "bin_number": part.bin_number,
                        "bin_number2": part.bin_number2,
                        "location": part.location,
                        "package_type": part.package_type,
                        "part_type": category_path,
                        "manufacturer": part.manufacturer,
                        "manufacturer_part_number": part.manufacturer_part_number,
                        "description": part.description,
                        "datasheet_url": part.datasheet_url,
                        "product_url": part.product_url,
                    }
                    parts_found.append(compact_payload(rec))

    return {
        "parts": parts_found,
        "not_found": not_found,
    }


def save_parts_sync(
    proxy: BinnerAPIProxy,
    category_cache: Dict[int, str],
    category_name_to_id: Dict[str, int],
    parts: List[Dict[str, Any]],
    category_delimiter: str = "::",
) -> Dict[str, Any]:
    """
    Batched component persistence (upsert) for 1 to N components with Zero-Side-Effects failure policy.

    Enforces pre-flight validation up front. If ANY item fails validation, ZERO mutations occur.
    """
    if not parts or not isinstance(parts, list):
        return {
            "status": "error",
            "error": "Validation failed",
            "details": ["'parts' must be a non-empty list of part records."],
        }

    errors: List[str] = []
    seen_pns: Set[str] = set()
    preflight_existing: Dict[Any, Any] = {}

    with proxy._lock:
        # --- Pre-Flight Validation Phase ---
        for i, item in enumerate(parts):
            if not isinstance(item, dict):
                errors.append(f"Item {i} is not a valid dictionary.")
                continue

            raw_pn = item.get("part_number")
            if not raw_pn or not str(raw_pn).strip():
                errors.append(f"Item {i}: 'part_number' is required and cannot be blank.")
                continue

            pn = str(raw_pn).strip()
            pn_lower = pn.lower()
            if pn_lower in seen_pns:
                errors.append(f"Item {i}: duplicate part_number '{pn}' in batch.")
            seen_pns.add(pn_lower)

            # Check numeric constraints
            qty = item.get("quantity")
            if qty is not None and (not isinstance(qty, int) or qty < 0):
                errors.append(f"Item {i} ('{pn}'): 'quantity' must be an integer >= 0.")

            threshold = item.get("low_stock_threshold")
            if threshold is not None and (not isinstance(threshold, int) or threshold < 0):
                errors.append(f"Item {i} ('{pn}'): 'low_stock_threshold' must be an integer >= 0.")

            cost = item.get("cost")
            if cost is not None and (not isinstance(cost, (int, float)) or cost < 0):
                errors.append(f"Item {i} ('{pn}'): 'cost' must be a number >= 0.")

            # Check part_id validity if provided
            pid = item.get("part_id")
            if pid is not None:
                try:
                    pid_int = int(pid)
                except (ValueError, TypeError):
                    errors.append(f"Item {i} ('{pn}'): 'part_id' must be an integer.")
                else:
                    existing_by_id = proxy.get_part_by_id(pid_int)
                    if not existing_by_id:
                        errors.append(f"Item {i} ('{pn}'): part_id {pid_int} does not exist in inventory.")
                    else:
                        preflight_existing[pid_int] = existing_by_id
                        preflight_existing[pn_lower] = existing_by_id

            # Check create_only invariant
            if item.get("create_only", False):
                existing = preflight_existing.get(pn_lower) or proxy.get_part_by_number(pn)
                if existing:
                    preflight_existing[pn_lower] = existing
                    errors.append(f"Item {i} ('{pn}'): part already exists and create_only is True.")

        if errors:
            return {
                "status": "error",
                "error": "Validation failed",
                "details": errors,
            }

        # --- Mutation Phase (Reached only if 100% of pre-flight checks pass) ---
        created_list: List[Dict[str, Any]] = []
        updated_list: List[Dict[str, Any]] = []
        failed_list: List[Dict[str, Any]] = []
        warnings: List[str] = []

        for item in parts:
            pn = str(item["part_number"]).strip()
            pn_lower = pn.lower()
            pid = item.get("part_id")

            existing = preflight_existing.get(pid) if pid is not None else preflight_existing.get(pn_lower)
            if existing is None:
                existing = proxy.get_part_by_number(pn)

            # Resolve category ID: support direct part_type_id first
            part_type_id: Optional[str] = None
            raw_ptid = item.get("part_type_id")
            if raw_ptid is not None:
                ptid_str = str(raw_ptid).strip()
                if ptid_str.isdigit():
                    part_type_id = ptid_str

            part_type_str = item.get("part_type")
            if part_type_id is None and part_type_str is not None:
                pts = str(part_type_str).strip()
                if pts.isdigit():
                    part_type_id = pts
                elif pts.lower() in category_name_to_id:
                    part_type_id = str(category_name_to_id[pts.lower()])
                else:
                    import re
                    delims = {category_delimiter, "::", "#", ">"}
                    pattern = "|".join(re.escape(d) for d in delims if d)
                    last_seg = re.split(pattern, pts)[-1].strip().lower()
                    if last_seg in category_name_to_id:
                        part_type_id = str(category_name_to_id[last_seg])
                    else:
                        try:
                            new_cat = proxy.create_part_type({"name": pts})
                            part_type_id = str(new_cat.part_type_id)
                            category_cache[new_cat.part_type_id] = new_cat.name
                            category_name_to_id[new_cat.name.lower()] = new_cat.part_type_id
                            warnings.append(f"Created category '{pts}' for part {pn}.")
                        except (requests.RequestException, BinnerError, ValueError, KeyError) as exc:
                            warnings.append(f"Could not create category '{pts}' for part {pn}: {exc}")

            success = False
            last_err: Optional[str] = None
            retries = 0

            for attempt in range(2):
                try:
                    if existing is None:
                        # CREATE
                        create_req = {
                            "part_number": pn,
                            "quantity": item.get("quantity", 0),
                            "low_stock_threshold": item.get("low_stock_threshold", 0),
                            "cost": float(item.get("cost", 0.0)),
                            "currency": item.get("currency") or "USD",
                            "bin_number": item.get("bin_number"),
                            "bin_number2": item.get("bin_number2"),
                            "location": item.get("location"),
                            "description": item.get("description"),
                            "package_type": item.get("package_type"),
                            "manufacturer": item.get("manufacturer"),
                            "manufacturer_part_number": item.get("manufacturer_part_number"),
                            "datasheet_url": item.get("datasheet_url"),
                            "part_type_id": part_type_id,
                        }
                        created_part = proxy.create_part(create_req)
                        cat_desc = category_cache.get(created_part.part_type_id, pts if part_type_str else None)
                        created_list.append({
                            "part_id": created_part.part_id,
                            "part_number": created_part.part_number,
                            "initial_values": compact_payload({
                                "quantity": created_part.quantity,
                                "bin_number": created_part.bin_number,
                                "location": created_part.location,
                                "package_type": created_part.package_type,
                                "cost": created_part.cost,
                                "currency": created_part.currency,
                                "part_type": cat_desc,
                            }),
                        })
                    else:
                        # UPDATE
                        old_vals = {
                            "quantity": existing.quantity,
                            "low_stock_threshold": existing.low_stock_threshold,
                            "cost": existing.cost,
                            "currency": existing.currency,
                            "bin_number": existing.bin_number,
                            "bin_number2": existing.bin_number2,
                            "location": existing.location,
                            "description": existing.description,
                            "package_type": existing.package_type,
                            "manufacturer": existing.manufacturer,
                            "manufacturer_part_number": existing.manufacturer_part_number,
                            "datasheet_url": existing.datasheet_url,
                            "part_type": category_cache.get(existing.part_type_id, existing.part_type),
                        }

                        update_req = {
                            "part_id": existing.part_id,
                            "part_number": pn,
                            "quantity": item["quantity"] if "quantity" in item else existing.quantity,
                            "low_stock_threshold": item["low_stock_threshold"] if "low_stock_threshold" in item else existing.low_stock_threshold,
                            "cost": float(item["cost"]) if "cost" in item else existing.cost,
                            "currency": item.get("currency") or existing.currency or "USD",
                            "bin_number": item["bin_number"] if "bin_number" in item else existing.bin_number,
                            "bin_number2": item["bin_number2"] if "bin_number2" in item else existing.bin_number2,
                            "location": item["location"] if "location" in item else existing.location,
                            "description": item["description"] if "description" in item else existing.description,
                            "package_type": item["package_type"] if "package_type" in item else existing.package_type,
                            "manufacturer": item["manufacturer"] if "manufacturer" in item else existing.manufacturer,
                            "manufacturer_part_number": item["manufacturer_part_number"] if "manufacturer_part_number" in item else existing.manufacturer_part_number,
                            "datasheet_url": item["datasheet_url"] if "datasheet_url" in item else existing.datasheet_url,
                            "part_type_id": part_type_id if part_type_id is not None else (str(existing.part_type_id) if existing.part_type_id else None),
                        }
                        updated_part = proxy.update_part(update_req)
                        new_vals = {
                            "quantity": updated_part.quantity,
                            "low_stock_threshold": updated_part.low_stock_threshold,
                            "cost": updated_part.cost,
                            "currency": updated_part.currency,
                            "bin_number": updated_part.bin_number,
                            "bin_number2": updated_part.bin_number2,
                            "location": updated_part.location,
                            "description": updated_part.description,
                            "package_type": updated_part.package_type,
                            "manufacturer": updated_part.manufacturer,
                            "manufacturer_part_number": updated_part.manufacturer_part_number,
                            "datasheet_url": updated_part.datasheet_url,
                            "part_type": category_cache.get(updated_part.part_type_id, updated_part.part_type),
                        }

                        diff = generate_change_diff(compact_payload(old_vals), compact_payload(new_vals))
                        updated_list.append({
                            "part_id": updated_part.part_id,
                            "part_number": updated_part.part_number,
                            "changes": diff,
                        })
                    success = True
                    break
                except (requests.RequestException, BinnerError, ValueError, KeyError) as exc:
                    last_err = str(exc)
                    retries = attempt + 1
                    if attempt == 0:
                        time.sleep(0.2)
                        continue

            if not success:
                failed_list.append({
                    "part_number": pn,
                    "error": last_err or "Mutation failed",
                    "retries": retries,
                })

        status = "success"
        if failed_list:
            status = "partial_success" if (created_list or updated_list) else "error"

        return {
            "status": status,
            "created_count": len(created_list),
            "updated_count": len(updated_list),
            "failed_count": len(failed_list),
            "created": created_list,
            "updated": updated_list,
            "failed": failed_list,
            "warnings": warnings,
        }


def delete_parts_sync(
    proxy: BinnerAPIProxy,
    part_numbers: Optional[List[str]] = None,
    part_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Batched component deletion with Zero-Side-Effects pre-flight validation.

    If ANY requested part does not exist, ZERO deletions are executed.
    """
    if not part_numbers and not part_ids:
        return {
            "status": "error",
            "error": "Validation failed",
            "details": ["At least one of 'part_numbers' or 'part_ids' must be provided."],
        }

    errors: List[str] = []
    to_delete: List[Dict[str, Any]] = []
    seen_pids: Set[int] = set()

    with proxy._lock:
        if part_ids:
            for pid in part_ids:
                try:
                    pid_int = int(pid)
                except (ValueError, TypeError):
                    errors.append(f"Invalid part ID: {pid}")
                    continue

                existing = proxy.get_part_by_id(pid_int)
                if not existing:
                    errors.append(f"Part ID {pid_int} not found in inventory.")
                else:
                    if existing.part_id not in seen_pids:
                        seen_pids.add(existing.part_id)
                        to_delete.append({"part_id": existing.part_id, "part_number": existing.part_number})

        if part_numbers:
            for pn in part_numbers:
                pn_clean = str(pn).strip()
                if not pn_clean:
                    continue

                existing = proxy.get_part_by_number(pn_clean)
                if not existing:
                    errors.append(f"Part number '{pn_clean}' not found in inventory.")
                else:
                    if existing.part_id not in seen_pids:
                        seen_pids.add(existing.part_id)
                        to_delete.append({"part_id": existing.part_id, "part_number": existing.part_number})

        if errors:
            return {
                "status": "error",
                "error": "Validation failed",
                "details": errors,
            }

        deleted_list: List[Dict[str, Any]] = []
        failed_list: List[Dict[str, Any]] = []

        for item in to_delete:
            success = False
            last_err: Optional[str] = None
            retries = 0

            for attempt in range(2):
                try:
                    proxy.delete_part(item["part_id"])
                    deleted_list.append(item)
                    success = True
                    break
                except (requests.RequestException, BinnerError, ValueError, KeyError) as exc:
                    last_err = str(exc)
                    retries = attempt + 1
                    if attempt == 0:
                        time.sleep(0.2)
                        continue

            if not success:
                failed_list.append({
                    "item": item,
                    "error": last_err or "Deletion failed",
                    "retries": retries,
                })

        status = "success"
        if failed_list:
            status = "partial_success" if deleted_list else "error"

        return {
            "status": status,
            "deleted_count": len(deleted_list),
            "failed_count": len(failed_list),
            "deleted": deleted_list,
            "failed": failed_list,
        }
