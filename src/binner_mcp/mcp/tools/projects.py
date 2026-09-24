"""Synchronous implementation for Maker Projects, BOM line items, and batch stock consumption MCP tools."""

import logging
import time
from typing import Any, Dict, List, Optional, Set

import requests

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import BinnerError
from binner_mcp.api.models import (
    AddBomPartRequest,
    CreateProjectRequest,
    UpdateBomPartRequest,
    UpdateProjectRequest,
)
from binner_mcp.mcp.normalization import compact_payload, format_lean_bom

logger = logging.getLogger("binner_mcp.mcp.tools.projects")


def list_projects_sync(
    proxy: BinnerAPIProxy,
    page: int = 1,
    limit: int = 50,
    sort_by: str = "DateCreatedUtc",
    direction: str = "Descending",
    query: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search and list maker projects with pagination, keyword search, and metadata.

    Args:
        proxy: Authenticated Binner API proxy.
        page: Page number (1-based).
        limit: Max projects to return (1-500).
        sort_by: Column to sort by (default 'DateCreatedUtc').
        direction: 'Ascending' or 'Descending'.
        query: Optional search keyword to filter projects by name or description.
    """
    limit = min(max(1, limit), 500)
    with proxy._lock:
        projects = proxy.get_projects(
            page=page,
            results=limit,
            order_by=sort_by,
            direction=direction,
        )
        if query:
            q_clean = query.strip().lower()
            projects = [
                p for p in projects
                if (p.name and q_clean in p.name.lower())
                or (p.description and q_clean in p.description.lower())
            ]

        return {
            "status": "success",
            "page": page,
            "page_size": limit,
            "projects": [
                compact_payload({
                    "project_id": p.project_id,
                    "name": p.name,
                    "description": p.description,
                    "part_count": p.part_count,
                    "archived": p.archived,
                })
                for p in projects
            ],
        }


def get_projects_sync(
    proxy: BinnerAPIProxy,
    project_ids: Optional[List[int]] = None,
    names: Optional[List[str]] = None,
    include_bom: bool = False,
) -> Dict[str, Any]:
    """
    Batch inspect maker projects by IDs or names, with optional BOM inclusion.

    Args:
        proxy: Authenticated Binner API proxy.
        project_ids: List of numeric project IDs to inspect.
        names: List of project names to inspect.
        include_bom: If True, includes full Bill of Materials for each project.
    """
    if not project_ids and not names:
        return {
            "status": "error",
            "error": "Validation failed",
            "details": ["At least one of 'project_ids' or 'names' must be provided."],
        }

    projects_found: List[Dict[str, Any]] = []
    not_found: List[str] = []
    seen_ids: Set[int] = set()

    with proxy._lock:
        if project_ids:
            for pid in project_ids:
                try:
                    pid_int = int(pid)
                except (ValueError, TypeError):
                    not_found.append(str(pid))
                    continue

                if pid_int in seen_ids:
                    continue

                project = proxy.get_project(project_id=pid_int)
                if not project:
                    not_found.append(str(pid_int))
                else:
                    seen_ids.add(project.project_id)
                    rec = {
                        "project": compact_payload({
                            "project_id": project.project_id,
                            "name": project.name,
                            "description": project.description,
                            "part_count": project.part_count,
                            "archived": project.archived,
                        }),
                    }
                    if include_bom:
                        rec["bom"] = format_lean_bom(proxy.get_bom(project_id=project.project_id))
                    projects_found.append(rec)

        if names:
            for name in names:
                n_str = str(name).strip()
                if not n_str:
                    continue

                project = proxy.get_project(name=n_str)
                if not project:
                    not_found.append(n_str)
                else:
                    if project.project_id not in seen_ids:
                        seen_ids.add(project.project_id)
                        rec = {
                            "project": compact_payload({
                                "project_id": project.project_id,
                                "name": project.name,
                                "description": project.description,
                                "part_count": project.part_count,
                                "archived": project.archived,
                            }),
                        }
                        if include_bom:
                            rec["bom"] = format_lean_bom(proxy.get_bom(project_id=project.project_id))
                        projects_found.append(rec)

    return {
        "status": "success",
        "projects": projects_found,
        "not_found": not_found,
    }


def save_projects_sync(
    proxy: BinnerAPIProxy,
    projects: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Batch create or update maker projects with first-retry-then-report semantics (never rollback).

    Args:
        proxy: Authenticated Binner API proxy.
        projects: List of project records with 'name', optional 'description',
                  optional 'project_id' (for updates), optional 'archived'.
    """
    if not projects or not isinstance(projects, list):
        return {
            "status": "error",
            "error": "Validation failed",
            "details": ["'projects' must be a non-empty list of project records."],
        }

    validation_errors: List[str] = []
    for i, item in enumerate(projects):
        if not isinstance(item, dict):
            validation_errors.append(f"Item {i}: not a valid dictionary.")
            continue
        pid = item.get("project_id")
        name = item.get("name")
        if pid is None and (not name or not str(name).strip()):
            validation_errors.append(f"Item {i}: 'name' is required when creating a new project.")

    if validation_errors:
        return {
            "status": "error",
            "error": "Validation failed",
            "details": validation_errors,
        }

    created: List[Dict[str, Any]] = []
    updated: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    with proxy._lock:
        for i, item in enumerate(projects):
            pid = item.get("project_id")
            name = str(item["name"]).strip() if item.get("name") else None
            desc = item.get("description")
            archived = bool(item.get("archived", False))

            is_update = False
            target_id: Optional[int] = None
            if pid is not None:
                try:
                    target_id = int(pid)
                    is_update = True
                except (ValueError, TypeError):
                    failed.append({
                        "item": item,
                        "error": f"Invalid project_id: {pid}",
                        "retries": 0,
                    })
                    continue
            elif name:
                existing = proxy.get_project(name=name)
                if existing:
                    target_id = existing.project_id
                    is_update = True

            success = False
            last_err: Optional[str] = None
            retries = 0

            for attempt in range(2):
                try:
                    if is_update and target_id is not None:
                        req = UpdateProjectRequest(
                            projectId=target_id,
                            name=name,
                            description=desc,
                            archived=archived,
                        )
                        res = proxy.update_project(req)
                        updated.append(compact_payload({
                            "project_id": res.project_id,
                            "name": res.name,
                            "description": res.description,
                            "archived": res.archived,
                        }))
                        success = True
                        break
                    else:
                        req_c = CreateProjectRequest(
                            name=name,
                            description=desc,
                        )
                        res_c = proxy.create_project(req_c)
                        created.append(compact_payload({
                            "project_id": res_c.project_id,
                            "name": res_c.name,
                            "description": res_c.description,
                        }))
                        success = True
                        break
                except (requests.RequestException, BinnerError, ValueError, KeyError) as exc:
                    last_err = str(exc)
                    retries = attempt + 1
                    if attempt == 0:
                        time.sleep(0.2)
                        continue

            if not success:
                failed.append({
                    "item": item,
                    "error": last_err or "Unknown failure",
                    "retries": retries,
                })

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


def delete_projects_sync(
    proxy: BinnerAPIProxy,
    project_ids: Optional[List[int]] = None,
    names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Batch delete maker projects by ID or name with first-retry-then-report semantics (never rollback).

    Args:
        proxy: Authenticated Binner API proxy.
        project_ids: Numeric project IDs to delete.
        names: Project names to delete.
    """
    if not project_ids and not names:
        return {
            "status": "error",
            "error": "Validation failed",
            "details": ["At least one of 'project_ids' or 'names' must be provided."],
        }

    resolved_targets: List[Dict[str, Any]] = []
    seen_ids: Set[int] = set()

    with proxy._lock:
        if project_ids:
            for pid in project_ids:
                try:
                    pid_int = int(pid)
                except (ValueError, TypeError):
                    continue
                if pid_int not in seen_ids:
                    seen_ids.add(pid_int)
                    proj = proxy.get_project(project_id=pid_int)
                    if proj:
                        resolved_targets.append({"project_id": proj.project_id, "name": proj.name})

        if names:
            for n in names:
                n_str = str(n).strip()
                if not n_str:
                    continue
                proj = proxy.get_project(name=n_str)
                if proj and proj.project_id not in seen_ids:
                    seen_ids.add(proj.project_id)
                    resolved_targets.append({"project_id": proj.project_id, "name": proj.name})

        if not resolved_targets:
            return {
                "status": "error",
                "error": "Projects not found",
                "details": ["None of the specified projects exist in inventory."],
            }

        deleted: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        for target in resolved_targets:
            pid = target["project_id"]
            success = False
            last_err: Optional[str] = None
            retries = 0

            for attempt in range(2):
                try:
                    ok = proxy.delete_project(pid)
                    if ok:
                        deleted.append(target)
                        success = True
                        break
                    else:
                        last_err = "Backend returned unsuccessful status for deletion"
                        retries = attempt + 1
                        if attempt == 0:
                            time.sleep(0.2)
                            continue
                except (requests.RequestException, BinnerError, ValueError, KeyError) as exc:
                    last_err = str(exc)
                    retries = attempt + 1
                    if attempt == 0:
                        time.sleep(0.2)
                        continue

            if not success:
                failed.append({
                    "target": target,
                    "error": last_err or "Deletion failed",
                    "retries": retries,
                })

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


def consume_project_bom_sync(
    proxy: BinnerAPIProxy,
    project_id: Optional[int] = None,
    name: Optional[str] = None,
    build_quantity: int = 1,
) -> Dict[str, Any]:
    """
    Deduct inventory stock for assembling board units of a maker project's BOM.

    Enforces pre-flight shortage check across all BOM line items (circuit breaker).
    Executes stock deductions with first-retry-then-report semantics (never rollback).

    Args:
        proxy: Authenticated Binner API proxy.
        project_id: Numeric project ID to consume for.
        name: Project name to consume for.
        build_quantity: Number of complete board units to assemble (>= 1).
    """
    if build_quantity < 1:
        return {
            "status": "error",
            "error": "Validation failed",
            "details": ["'build_quantity' must be an integer >= 1."],
        }

    if project_id is None and name is None:
        return {
            "status": "error",
            "error": "Validation failed",
            "details": ["Either 'project_id' or 'name' must be provided."],
        }

    with proxy._lock:
        project = proxy.get_project(project_id=project_id, name=name)
        if not project:
            return {
                "status": "error",
                "error": "Project not found",
                "details": [f"Project '{project_id or name}' was not found."],
            }

        bom = proxy.get_bom(project_id=project.project_id)
        bom_parts = bom.get("parts") or bom.get("Parts") or []
        if not bom_parts:
            return {
                "status": "error",
                "error": "Validation failed",
                "details": [f"Project '{project.name}' BOM has no assigned components."],
            }

        # Pre-flight stock availability check across all BOM items
        shortages: List[Dict[str, Any]] = []
        planned_deductions: List[Dict[str, Any]] = []

        for assignment in bom_parts:
            req_qty = assignment.get("quantity") or 1
            total_needed = req_qty * build_quantity
            part_info = assignment.get("part") or assignment.get("Part") or {}
            pn = assignment.get("partNumber") or part_info.get("partNumber") or assignment.get("partName")
            pid = assignment.get("partId") or part_info.get("partId")

            live_part = None
            if pn:
                live_part = proxy.get_part_by_number(pn)
            if not live_part and pid:
                live_part = proxy.get_part_by_id(pid)

            on_hand = live_part.quantity if live_part else (part_info.get("quantity", 0))
            if on_hand < total_needed:
                shortages.append({
                    "part_number": pn or f"PartId:{pid}",
                    "required": total_needed,
                    "on_hand": on_hand,
                    "shortage": total_needed - on_hand,
                })
            else:
                planned_deductions.append({
                    "part_id": pid or (live_part.part_id if live_part else None),
                    "part_number": pn or (live_part.part_number if live_part else None),
                    "total_needed": total_needed,
                })

        # Circuit breaker: halt immediately if shortages exist (zero mutations)
        if shortages:
            return {
                "status": "error",
                "error": "BOM consumption halted due to inventory shortages",
                "project": project.name,
                "build_quantity": build_quantity,
                "shortages": shortages,
            }

        # Mutation phase: execute deductions with retry-then-report (never rollback)
        deductions: List[Dict[str, Any]] = []
        failed_deductions: List[Dict[str, Any]] = []

        for item in planned_deductions:
            success = False
            last_err: Optional[str] = None
            retries = 0

            for attempt in range(2):
                try:
                    updated = proxy.update_quantity(
                        part_id=item["part_id"],
                        part_number=item["part_number"],
                        quantity=-item["total_needed"],
                        reason=f"Consumed for {build_quantity} units of project {project.name}",
                    )
                    deductions.append({
                        "part_number": item["part_number"],
                        "deducted": item["total_needed"],
                        "remaining_stock": updated.quantity,
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
                failed_deductions.append({
                    "part_number": item["part_number"],
                    "error": last_err or "Deduction failed",
                    "retries": retries,
                })

        status = "success"
        if failed_deductions:
            status = "partial_success" if deductions else "error"

        return {
            "status": status,
            "project": project.name,
            "build_quantity": build_quantity,
            "deductions": deductions,
            "failed_deductions": failed_deductions,
        }


def manage_bom_parts_sync(
    proxy: BinnerAPIProxy,
    project_id: int,
    parts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Batched BOM line item operations for a project with first-retry-then-report semantics (never rollback).

    Allows allocating, updating, or removing multiple components with optional linked stock adjustments.

    Args:
        proxy: Authenticated Binner API proxy.
        project_id: Target project ID.
        parts: BOM items with 'part_number'/'part_id', 'quantity', 'reference_designator', optional 'remove'.
    """
    with proxy._lock:
        project = proxy.get_project(project_id=project_id)
        if not project:
            return {
                "status": "error",
                "error": "Validation failed",
                "details": [f"Project ID {project_id} does not exist."],
            }

        if not parts or not isinstance(parts, list):
            return {
                "status": "error",
                "error": "Validation failed",
                "details": ["'parts' must be a non-empty list of BOM items."],
            }

        bom = proxy.get_bom(project_id=project_id)
        assignments = bom.get("parts") or bom.get("Parts") or []

        assign_by_pn: Dict[str, Dict[str, Any]] = {}
        assign_by_pid: Dict[int, Dict[str, Any]] = {}
        for a in assignments:
            part_obj = a.get("part") or a.get("Part") or {}
            pn = a.get("partNumber") or part_obj.get("partNumber") or a.get("partName")
            pid = a.get("partId") or part_obj.get("partId")
            if pn:
                assign_by_pn[str(pn).strip().lower()] = a
            if pid:
                assign_by_pid[int(pid)] = a

        errors: List[str] = []
        planned_ops: List[Dict[str, Any]] = []

        for i, item in enumerate(parts):
            if not isinstance(item, dict):
                errors.append(f"Item {i} is not a valid dictionary.")
                continue

            pn = item.get("part_number")
            pid = item.get("part_id")
            remove = item.get("remove", False)
            qty = item.get("quantity", 1)
            delta = item.get("adjust_stock_delta")
            ref_des = item.get("reference_designator")

            pn_str = str(pn).strip() if pn else None
            pid_int = int(pid) if pid is not None else None

            if not pn_str and pid_int is None:
                errors.append(f"Item {i}: must specify either 'part_number' or 'part_id'.")
                continue

            matching_assign = None
            if pn_str and pn_str.lower() in assign_by_pn:
                matching_assign = assign_by_pn[pn_str.lower()]
            elif pid_int is not None and pid_int in assign_by_pid:
                matching_assign = assign_by_pid[pid_int]

            if remove:
                if not matching_assign:
                    errors.append(f"Item {i} ('{pn_str or pid_int}'): cannot remove, part is not in project BOM.")
                else:
                    assign_id = matching_assign.get("projectPartAssignmentId")
                    planned_ops.append({
                        "op": "remove",
                        "assignment_id": assign_id,
                        "part_number": pn_str,
                        "part_id": pid_int,
                        "delta": delta,
                    })
            else:
                if not isinstance(qty, int) or qty < 1:
                    errors.append(f"Item {i} ('{pn_str or pid_int}'): 'quantity' must be an integer >= 1.")

                live_part = None
                if pn_str:
                    live_part = proxy.get_part_by_number(pn_str)
                if not live_part and pid_int is not None:
                    live_part = proxy.get_part_by_id(pid_int)

                if not live_part:
                    errors.append(f"Item {i} ('{pn_str or pid_int}'): component does not exist in inventory.")
                else:
                    resolved_pn = live_part.part_number
                    resolved_pid = live_part.part_id

                    if delta is not None and delta < 0:
                        if live_part.quantity + delta < 0:
                            errors.append(
                                f"Item {i} ('{resolved_pn}'): insufficient stock (on hand {live_part.quantity}, "
                                f"requested deduction {abs(delta)})."
                            )

                    if matching_assign:
                        assign_id = matching_assign.get("projectPartAssignmentId")
                        planned_ops.append({
                            "op": "update",
                            "assignment_id": assign_id,
                            "part_number": resolved_pn,
                            "part_id": resolved_pid,
                            "quantity": qty,
                            "reference_designator": ref_des,
                            "delta": delta,
                        })
                    else:
                        planned_ops.append({
                            "op": "add",
                            "part_number": resolved_pn,
                            "part_id": resolved_pid,
                            "quantity": qty,
                            "reference_designator": ref_des,
                            "delta": delta,
                        })

        if errors:
            return {
                "status": "error",
                "error": "Validation failed",
                "details": errors,
            }

        # Mutation phase with retry-then-report (never rollback)
        allocated = 0
        updated = 0
        removed = 0
        failed: List[Dict[str, Any]] = []

        for op in planned_ops:
            op_success = False
            last_err: Optional[str] = None
            retries = 0

            for attempt in range(2):
                try:
                    if op["op"] == "remove":
                        proxy.delete_bom_part(ids=op["assignment_id"], project_id=project_id)
                        removed += 1
                    elif op["op"] == "update":
                        proxy.update_bom_part(
                            UpdateBomPartRequest(
                                projectPartAssignmentId=op["assignment_id"],
                                projectId=project_id,
                                quantity=op["quantity"],
                                notes=op["reference_designator"],
                            )
                        )
                        updated += 1
                    elif op["op"] == "add":
                        proxy.add_bom_part(
                            AddBomPartRequest(
                                projectId=project_id,
                                partNumber=op["part_number"],
                                quantity=op["quantity"],
                                notes=op["reference_designator"],
                            )
                        )
                        allocated += 1

                    if op.get("delta"):
                        proxy.update_quantity(
                            part_id=op.get("part_id"),
                            part_number=op.get("part_number"),
                            quantity=op["delta"],
                            reason=f"BOM allocation adjustment for project {project_id}",
                        )
                    op_success = True
                    break
                except (requests.RequestException, BinnerError, ValueError, KeyError) as exc:
                    last_err = str(exc)
                    retries = attempt + 1
                    if attempt == 0:
                        time.sleep(0.2)
                        continue

            if not op_success:
                failed.append({
                    "op": op,
                    "error": last_err or "BOM mutation failed",
                    "retries": retries,
                })

        status = "success"
        if failed:
            status = "partial_success" if (allocated or updated or removed) else "error"

        return {
            "status": status,
            "project_id": project_id,
            "allocated": allocated,
            "updated": updated,
            "removed": removed,
            "failed": failed,
        }
