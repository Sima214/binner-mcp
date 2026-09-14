#!/usr/bin/env python3
"""
Example 3: Project Bill of Materials (BOM) Allocation.

Creates a maker project, queries available components, and assigns required
quantities to the project BOM.
Prerequisites: A running Binner instance (default: http://localhost:8090).
"""

import sys
from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import BinnerAPIError, BinnerConnectionError
from binner_mcp.api.models import AddBomPartRequest, CreateProjectRequest


def setup_project_bom() -> None:
    client = BinnerAPIProxy()

    try:
        client.login()

        # 1. Create the project
        project = client.create_project(
            CreateProjectRequest(
                name="LoRa Environmental Sensor Node",
                description="Battery-powered weather telemetry node using RFM95W",
            )
        )
        print(f"Created project: {project.name} (ID: {project.project_id})")

        # 2. Add components to BOM
        bom_items = [
            {"partNumber": "RP2040", "qty": 1, "ref": "U1", "notes": "Main controller"},
            {"partNumber": "NE555P", "qty": 1, "ref": "U2", "notes": "Watchdog pulse generator"},
        ]

        for item in bom_items:
            client.add_bom_part(
                AddBomPartRequest(
                    project_id=project.project_id,
                    part_number=item["partNumber"],
                    quantity=item["qty"],
                    reference_id=item["ref"],
                    notes=item["notes"],
                )
            )
            print(f"Assigned {item['partNumber']} ({item['ref']}) to BOM.")

        # 3. Verify assembled BOM
        bom_data = client.get_bom(project_id=project.project_id)
        parts_list = bom_data.get("parts", []) if isinstance(bom_data, dict) else []
        print(f"\nFinal BOM Part Count: {len(parts_list)}")

    except BinnerConnectionError as ce:
        sys.stderr.write(f"Connection failed: {ce}\n")
    except BinnerAPIError as ae:
        sys.stderr.write(f"API error: {ae}\n")


if __name__ == "__main__":
    setup_project_bom()
