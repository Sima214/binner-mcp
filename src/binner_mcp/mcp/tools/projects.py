"""Synchronous implementation for Maker Projects, BOM line items, and batch stock consumption MCP tools."""

import logging
from typing import Any, Dict, List, Optional
import requests

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.models import (
    AddBomPartRequest,
    CreateProjectRequest,
    UpdateBomPartRequest,
)
from binner_mcp.mcp.normalization import compact_payload

logger = logging.getLogger("binner_mcp.mcp.tools.projects")


def manage_project_sync(
    proxy: BinnerAPIProxy,
    action: str = "list",
    project_id: Optional[int] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    include_bom: bool = False,
    build_quantity: int = 1,
) -> Dict[str, Any]:
    """
    Manage maker project lifecycle, BOM inspection, and batch stock consumption with Zero-Side-Effects.

    Supported actions:
      - 'list': List all projects with part counts and metadata.
      - 'get': Fetch single project details with optional embedded BOM shortage matrix.
      - 'create': Create a new project (pre-flights name uniqueness).
      - 'consume_bom': Deduct inventory stock for assembling 'build_quantity' board units.
                      Halts with zero deductions if any part is under-stocked.
    """
    with proxy._lock:
        if action == "list":
            projects = proxy.get_projects(results=100)
            return {
                "status": "success",
                "action": "list",
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

        elif action == "get":
            if project_id is None and name is None:
                return {
                    "status": "error",
                    "error": "Validation failed",
                    "details": ["Either 'project_id' or 'name' must be provided for action='get'."],
                }

            project = proxy.get_project(project_id=project_id, name=name)
            if not project:
                return {
                    "status": "error",
                    "error": "Project not found",
                    "details": [f"Project '{project_id or name}' was not found."],
                }

            result: Dict[str, Any] = {
                "status": "success",
                "action": "get",
                "project": compact_payload({
                    "project_id": project.project_id,
                    "name": project.name,
                    "description": project.description,
                    "part_count": project.part_count,
                    "archived": project.archived,
                }),
            }

            if include_bom:
                bom = proxy.get_bom(project_id=project.project_id)
                result["bom"] = compact_payload(bom)

            return result

        elif action == "create":
            if not name or not str(name).strip():
                return {
                    "status": "error",
                    "error": "Validation failed",
                    "details": ["Project 'name' is required for action='create' and cannot be blank."],
                }

            clean_name = str(name).strip()
            existing = proxy.get_project(name=clean_name)
            if existing:
                return {
                    "status": "error",
                    "error": "Validation failed",
                    "details": [f"Project with name '{clean_name}' already exists."],
                }

            created = proxy.create_project(CreateProjectRequest(name=clean_name, description=description))
            return {
                "status": "success",
                "action": "create",
                "project": compact_payload({
                    "project_id": created.project_id,
                    "name": created.name,
                    "description": created.description,
                }),
            }

        elif action == "consume_bom":
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
                    "details": ["Either 'project_id' or 'name' must be provided for action='consume_bom'."],
                }

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

            # Pre-flight stock availability across all BOM items
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

            # Circuit breaker: halt immediately if shortages exist
            if shortages:
                return {
                    "status": "error",
                    "error": "BOM consumption halted due to inventory shortages",
                    "project": project.name,
                    "build_quantity": build_quantity,
                    "shortages": shortages,
                }

            # All items in stock: execute deductions
            deductions: List[Dict[str, Any]] = []
            for item in planned_deductions:
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

            return {
                "status": "success",
                "action": "consume_bom",
                "project": project.name,
                "build_quantity": build_quantity,
                "deductions": deductions,
            }

        else:
            return {
                "status": "error",
                "error": "Validation failed",
                "details": [f"Unknown action '{action}'. Valid actions are 'list', 'get', 'create', 'consume_bom'."],
            }


def manage_bom_parts_sync(
    proxy: BinnerAPIProxy,
    project_id: int,
    parts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Batched BOM line item operations for a project with Zero-Side-Effects pre-flight validation.

    Allows allocating, updating, or removing multiple components simultaneously with optional linked stock adjustments.
    """
    with proxy._lock:
        # Pre-flight 1: verify project exists
        project = proxy.get_project(project_id=project_id)
        if not project:
            return {
                "status": "error",
                "error": "Validation failed",
                "details": [f"Project ID {project_id} does not exist."],
            }

        # Pre-flight 2: verify parts non-empty list
        if not parts or not isinstance(parts, list):
            return {
                "status": "error",
                "error": "Validation failed",
                "details": ["'parts' must be a non-empty list of BOM items."],
            }

        bom = proxy.get_bom(project_id=project_id)
        assignments = bom.get("parts") or bom.get("Parts") or []

        # Index existing assignments by assignment_id, part_number, and part_id
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

            # Find matching assignment in current BOM
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

                # Verify part exists in inventory
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

                    # If negative stock delta requested, verify on-hand stock
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

        # Mutation phase
        allocated = 0
        updated = 0
        removed = 0

        for op in planned_ops:
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

        return {
            "status": "success",
            "project_id": project_id,
            "allocated": allocated,
            "updated": updated,
            "removed": removed,
        }
