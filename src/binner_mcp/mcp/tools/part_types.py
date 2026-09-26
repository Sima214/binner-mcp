"""Synchronous implementation for part type (category) tree inspection and batch mutations."""

import logging
import time
from typing import Any, Dict, List, Optional, Set

import requests

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import BinnerError
from binner_mcp.api.models import CreatePartTypeRequest, UpdatePartTypeRequest
from binner_mcp.common.exceptions import BaseProxyError
from binner_mcp.common.http import RETRY_DELAY, is_transient_network_error
from binner_mcp.config import DEFAULT_RETRY_DELAY, DEFAULT_RETRY_COUNT
from binner_mcp.mcp.categories import CategoryResolver
from binner_mcp.mcp.normalization import compact_payload
from binner_mcp.mcp.validation import normalize_batch_input, parse_int_id

logger = logging.getLogger("binner_mcp.mcp.tools.part_types")


def list_part_types_sync(
    proxy: BinnerAPIProxy,
    depth: Optional[int] = None,
    root_id: Optional[int] = None,
    root_name: Optional[str] = None,
    include_descriptions: bool = False,
    include_part_counts: bool = False,
    category_resolver: Optional[CategoryResolver] = None,
) -> Dict[str, Any]:
    """
    List all part types structured as a hierarchical tree focusing on part type IDs and names.

    Args:
        proxy: Authenticated Binner API proxy.
        depth: Optional maximum depth of tree recursion (e.g. 1 for top-level only).
        root_id: Optional root category ID to scope the tree to a single subtree.
        root_name: Optional root category name to scope the tree to a single subtree.
        include_descriptions: If True, includes description field per node (default False).
        include_part_counts: If True, includes parts count per part type (default False).
        category_resolver: Optional CategoryResolver for hierarchy lookup and ambiguity detection.
    """
    with proxy._lock:
        all_types = proxy.get_part_types()
        if category_resolver is not None:
            category_resolver.update(all_types)

        type_map: Dict[int, Any] = {}
        children_map: Dict[int, List[int]] = {}
        for pt in all_types:
            if pt.part_type_id is not None:
                type_map[pt.part_type_id] = pt
                children_map.setdefault(pt.part_type_id, [])

        root_ids: List[int] = []
        for pt in all_types:
            if pt.part_type_id is None:
                continue
            parent_id = pt.parent_part_type_id
            if parent_id is not None and parent_id in type_map:
                children_map[parent_id].append(pt.part_type_id)
            else:
                root_ids.append(pt.part_type_id)

        target_roots = root_ids
        if root_id is not None:
            if root_id in type_map:
                target_roots = [root_id]
            else:
                return {
                    "status": "error",
                    "error": "Part type not found",
                    "details": [f"Root part type ID {root_id} does not exist."],
                }
        elif root_name is not None:
            r_name_clean = root_name.strip()
            if category_resolver is not None:
                matches = category_resolver.find_matches(r_name_clean)
            else:
                matches = [
                    (tid, pt.name)
                    for tid, pt in type_map.items()
                    if pt.name and pt.name.lower() == r_name_clean.lower()
                ]

            if len(matches) > 1:
                candidates = ", ".join(f"ID {tid} '{path}'" for tid, path in matches)
                return {
                    "status": "error",
                    "error": "Ambiguous root part type name",
                    "details": [
                        f"Root part type name '{root_name}' is ambiguous. Matches {len(matches)} categories: [{candidates}]. "
                        "Please specify root_id or full category path."
                    ],
                }
            elif len(matches) == 1:
                target_roots = [matches[0][0]]
            else:
                return {
                    "status": "error",
                    "error": "Part type not found",
                    "details": [f"Root part type name '{root_name}' does not exist."],
                }

        def build_node(pt_id: int, current_depth: int) -> Dict[str, Any]:
            pt = type_map[pt_id]
            node: Dict[str, Any] = {
                "id": pt.part_type_id,
                "name": pt.name,
            }
            if include_descriptions and pt.description:
                node["description"] = pt.description
            if include_part_counts and pt.parts is not None:
                node["parts_count"] = pt.parts

            child_ids = children_map.get(pt_id, [])
            if child_ids and (depth is None or current_depth < depth):
                node["children"] = [
                    build_node(cid, current_depth + 1)
                    for cid in child_ids
                ]
            return node

        tree = [build_node(rid, 1) for rid in target_roots]
        return {
            "status": "success",
            "total_types": len(type_map),
            "tree": tree,
        }


def save_part_types_sync(
    proxy: BinnerAPIProxy,
    category_cache: Dict[int, str],
    category_name_to_id: Dict[str, int],
    part_types: List[Dict[str, Any]],
    retry_delay: float = DEFAULT_RETRY_DELAY,
    retry_count: int = DEFAULT_RETRY_COUNT,
    category_resolver: Optional[CategoryResolver] = None,
) -> Dict[str, Any]:
    """
    Batch create or update part types with first-retry-then-report execution semantics (never rollback).

    Args:
        proxy: Authenticated Binner API proxy.
        category_cache: Shared cache mapping part_type_id to name.
        category_name_to_id: Shared cache mapping lowercased name to part_type_id.
        part_types: List of part type records with 'name', optional 'description',
                    optional 'parent_part_type_id', and optional 'part_type_id' (for updates).
        retry_delay: Delay in seconds between retries upon transient network errors.
        retry_count: Maximum number of retries upon transient network errors.
        category_resolver: Optional CategoryResolver for hierarchy lookup and ambiguity detection.
    """
    normalized_types, err_resp = normalize_batch_input(part_types, "part_types")
    if err_resp:
        return err_resp

    with proxy._lock:
        if category_resolver is None:
            category_resolver = CategoryResolver()
        category_resolver.warm_cache(
            proxy,
            category_cache=category_cache,
            category_name_to_id=category_name_to_id,
        )

        # Pre-flight validation
        validation_errors: List[str] = []
        for i, item in enumerate(normalized_types):
            if not isinstance(item, dict):
                validation_errors.append(f"Item {i}: not a valid dictionary.")
                continue
            name = item.get("name")
            ptid = item.get("part_type_id")
            if ptid is None:
                if not name or not str(name).strip():
                    validation_errors.append(f"Item {i}: 'name' is required when creating a new part type.")
                else:
                    name_str = str(name).strip()
                    matches = category_resolver.find_matches(name_str)
                    if len(matches) > 1:
                        candidates = ", ".join(f"ID {tid} '{path}'" for tid, path in matches)
                        validation_errors.append(
                            f"Item {i} ('{name_str}'): part type name is ambiguous. "
                            f"Matches {len(matches)} categories: [{candidates}]. Please specify 'part_type_id' to update."
                        )

        if validation_errors:
            return {
                "status": "error",
                "error": "Validation failed",
                "details": validation_errors,
            }

        created: List[Dict[str, Any]] = []
        updated: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        for i, item in enumerate(normalized_types):
            ptid = item.get("part_type_id")
            name = str(item["name"]).strip() if item.get("name") else None
            desc = item.get("description")
            parent_id = item.get("parent_part_type_id")

            # Check if this is an update or create
            is_update = False
            target_id: Optional[int] = None
            if ptid is not None:
                try:
                    target_id = int(ptid)
                    is_update = True
                except (ValueError, TypeError):
                    failed.append({
                        "item": item,
                        "error": f"Invalid part_type_id: {ptid}",
                        "retries": 0,
                    })
                    continue

                if target_id not in category_cache:
                    all_pts = {pt.part_type_id: pt.name for pt in proxy.get_part_types()}
                    category_cache.update(all_pts)
                    if target_id not in category_cache:
                        failed.append({
                            "item": item,
                            "error": f"Part type ID {target_id} does not exist in inventory",
                            "retries": 0,
                        })
                        continue
            elif name and name.lower() in category_name_to_id:
                target_id = category_name_to_id[name.lower()]
                is_update = True
            elif not name:
                failed.append({
                    "item": item,
                    "error": f"Item {i}: 'name' is required when creating a new part type.",
                    "retries": 0,
                })
                continue

            # Execution with retry-then-report upon transient network failure
            success = False
            last_err: Optional[str] = None
            retries = 0

            for attempt in range(retry_count + 1):
                try:
                    if is_update and target_id is not None:
                        req = UpdatePartTypeRequest(
                            partTypeId=target_id,
                            name=name,
                            description=desc,
                            parentPartTypeId=parent_id,
                        )
                        res = proxy.update_part_type(req)
                        category_cache[res.part_type_id] = res.name
                        category_name_to_id[res.name.lower()] = res.part_type_id
                        updated.append(compact_payload({
                            "part_type_id": res.part_type_id,
                            "name": res.name,
                            "description": res.description,
                        }))
                        success = True
                        break
                    else:
                        req = CreatePartTypeRequest(
                            name=name,
                            description=desc,
                            parentPartTypeId=parent_id,
                        )
                        res = proxy.create_part_type(req)
                        category_cache[res.part_type_id] = res.name
                        category_name_to_id[res.name.lower()] = res.part_type_id
                        created.append(compact_payload({
                            "part_type_id": res.part_type_id,
                            "name": res.name,
                            "description": res.description,
                        }))
                        success = True
                        break
                except (requests.RequestException, BaseProxyError, ValueError, KeyError) as exc:
                    last_err = str(exc)
                    if attempt < retry_count and is_transient_network_error(exc):
                        retries = attempt + 1
                        time.sleep(retry_delay)
                        continue
                    else:
                        retries = attempt
                        break

            if not success:
                failed.append({
                    "item": item,
                    "error": last_err or "Unknown failure",
                    "retries": retries,
                })

        if category_resolver is not None and (created or updated):
            category_resolver.warm_cache(
                proxy,
                category_cache=category_cache,
                category_name_to_id=category_name_to_id,
            )

    status = "success"
    if failed:
        status = "partial_success" if (created or updated) else "error"

    return {
        "status": status,
        "created_count": len(created),
        "updated_count": len(updated),
        "failed_count": len(failed),
        "created": created,
        "updated": updated,
        "failed": failed,
    }


def delete_part_types_sync(
    proxy: BinnerAPIProxy,
    category_cache: Dict[int, str],
    category_name_to_id: Dict[str, int],
    part_type_ids: Optional[List[int]] = None,
    names: Optional[List[str]] = None,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    retry_count: int = DEFAULT_RETRY_COUNT,
    category_resolver: Optional[CategoryResolver] = None,
) -> Dict[str, Any]:
    """
    Batch delete part types by ID or name with first-retry-then-report semantics (never rollback).

    Args:
        proxy: Authenticated Binner API proxy.
        category_cache: Shared cache mapping part_type_id to name.
        category_name_to_id: Shared cache mapping lowercased name to part_type_id.
        part_type_ids: Numeric part type IDs to delete.
        names: Part type names to delete.
        retry_delay: Delay in seconds between retries upon transient network errors.
        retry_count: Maximum number of retries upon transient network errors.
        category_resolver: Optional CategoryResolver for hierarchy lookup and ambiguity detection.
    """
    if not part_type_ids and not names:
        return {
            "status": "error",
            "error": "Validation failed",
            "details": ["At least one of 'part_type_ids' or 'names' must be provided."],
        }

    resolved_targets: List[Dict[str, Any]] = []
    seen_ids: Set[int] = set()

    with proxy._lock:
        if category_resolver is None:
            category_resolver = CategoryResolver()
        category_resolver.warm_cache(
            proxy,
            category_cache=category_cache,
            category_name_to_id=category_name_to_id,
        )

        if part_type_ids:
            for pid in part_type_ids:
                try:
                    pid_int = int(pid)
                except (ValueError, TypeError):
                    continue
                if pid_int not in seen_ids:
                    seen_ids.add(pid_int)
                    name = category_cache.get(pid_int) or category_resolver.get_path(pid_int)
                    resolved_targets.append({"part_type_id": pid_int, "name": name})

        if names:
            for n in names:
                n_str = str(n).strip()
                if not n_str:
                    continue
                matches = category_resolver.find_matches(n_str)
                if len(matches) > 1:
                    candidates = ", ".join(f"ID {tid} '{path}'" for tid, path in matches)
                    return {
                        "status": "error",
                        "error": "Ambiguous part type name",
                        "details": [
                            f"Part type name '{n_str}' is ambiguous. Matches {len(matches)} categories: [{candidates}]. "
                            "Please specify 'part_type_ids' instead."
                        ],
                    }
                elif len(matches) == 1:
                    pid_int = matches[0][0]
                    if pid_int not in seen_ids:
                        seen_ids.add(pid_int)
                        resolved_targets.append({"part_type_id": pid_int, "name": matches[0][1]})
                else:
                    found = proxy.get_part_type_by_name(n_str)
                    if found and found.part_type_id and found.part_type_id not in seen_ids:
                        seen_ids.add(found.part_type_id)
                        resolved_targets.append({"part_type_id": found.part_type_id, "name": n_str})

        if not resolved_targets:
            return {
                "status": "error",
                "error": "Part types not found",
                "details": ["None of the specified part types exist in inventory."],
            }

        deleted: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        for target in resolved_targets:
            pid = target["part_type_id"]
            success = False
            last_err: Optional[str] = None
            retries = 0

            for attempt in range(retry_count + 1):
                try:
                    ok = proxy.delete_part_type(pid)
                    if ok:
                        deleted.append(target)
                        category_cache.pop(pid, None)
                        if target.get("name"):
                            category_name_to_id.pop(target["name"].lower(), None)
                        success = True
                        break
                    else:
                        last_err = "Backend returned unsuccessful status for deletion"
                        retries = 0
                        break
                except (requests.RequestException, BaseProxyError, ValueError, KeyError) as exc:
                    last_err = str(exc)
                    if attempt < retry_count and is_transient_network_error(exc):
                        retries = attempt + 1
                        time.sleep(retry_delay)
                        continue
                    else:
                        retries = attempt
                        break

            if not success:
                failed.append({
                    "target": target,
                    "error": last_err or "Deletion failed",
                    "retries": retries,
                })

        if category_resolver is not None and deleted:
            category_resolver.warm_cache(
                proxy,
                category_cache=category_cache,
                category_name_to_id=category_name_to_id,
            )

    status = "success"
    if failed:
        status = "partial_success" if deleted else "error"

    return {
        "status": status,
        "deleted_count": len(deleted),
        "failed_count": len(failed),
        "deleted": deleted,
        "failed": failed,
    }
