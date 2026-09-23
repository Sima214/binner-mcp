"""Synchronous implementation for Swarm Cloud component intelligence MCP tools."""

import logging
from typing import Any, Dict, List
import requests

from binner_mcp.mcp.normalization import compact_payload
from binner_mcp.swarmer.client import SwarmClient
from binner_mcp.swarmer.exceptions import SwarmError

logger = logging.getLogger("binner_mcp.mcp.tools.cloud")


def lookup_cloud_parts_sync(
    swarm: SwarmClient,
    part_numbers: List[str],
) -> Dict[str, Any]:
    """
    Batched component intelligence lookup via Binner Swarm cloud service.

    Retrieves pinout definitions, package geometry, descriptions, and datasheets
    for 1 to N components in a single turn.
    """
    if not part_numbers or not isinstance(part_numbers, list):
        return {"results": [], "not_found": []}

    results: List[Dict[str, Any]] = []
    not_found: List[str] = []

    for pn in part_numbers:
        pn_clean = str(pn).strip()
        if not pn_clean:
            continue

        try:
            res = swarm.search_parts(part_number=pn_clean)
            if not res.is_success or not res.response or not res.response.parts:
                not_found.append(pn_clean)
                continue

            part_obj = res.response.parts[0]
            description = part_obj.description
            datasheet_url = None
            package_name = None
            pinout_list: List[Dict[str, Any]] = []

            all_pinouts = list(part_obj.pinouts)
            for mfr in part_obj.part_number_manufacturers:
                all_pinouts.extend(mfr.pinouts)
                if not description and mfr.description:
                    description = mfr.description
                if not package_name and mfr.package:
                    package_name = mfr.package[0].name
                if not datasheet_url and mfr.datasheets:
                    datasheet_url = mfr.datasheets[0].direct_pdf_url

            for po in all_pinouts:
                if po.pinout_definition:
                    pinout_list.append({
                        "pinout_id": po.pinout_id,
                        "part_name": po.part_name,
                        "package_name": po.package_name,
                        "definition": po.pinout_definition,
                    })
                elif po.pin_count:
                    pinout_list.append({
                        "pinout_id": po.pinout_id,
                        "part_name": po.part_name,
                        "package_name": po.package_name,
                        "pin_count": po.pin_count,
                    })

            record: Dict[str, Any] = {
                "part_number": part_obj.name or pn_clean,
                "description": description,
                "package": package_name,
                "datasheet_url": datasheet_url,
                "pinout": pinout_list if pinout_list else None,
            }
            results.append(compact_payload(record))

        except (SwarmError, requests.RequestException, ValueError, KeyError) as exc:
            logger.debug("Swarm search failed for %s: %s", pn_clean, exc)
            not_found.append(pn_clean)

    return {
        "results": results,
        "not_found": not_found,
    }
