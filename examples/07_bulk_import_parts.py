#!/usr/bin/env python3
"""
Example 7: Bulk Ingestion via Free Batch Endpoint.

Imports multiple components in a single HTTP POST request using POST /api/part/bulk.
Prerequisites: A running Binner instance (default: http://localhost:8090).
"""

import sys
from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import BinnerAPIError, BinnerConnectionError
from binner_mcp.api.models import BulkImportItem


def bulk_import_components() -> None:
    client = BinnerAPIProxy()

    try:
        client.login()

        items = [
            BulkImportItem(
                part_number="RES-10K-0805",
                description="10k Ohm 1% 0805 SMD Resistor",
                quantity=1000,
                location="SMD Resistor Book",
                bin_number="Page 3",
                cost=0.005,
                package_type="0805",
            ),
            BulkImportItem(
                part_number="CAP-100NF-0805",
                description="100nF (0.1uF) 50V X7R 0805 SMD Capacitor",
                quantity=500,
                location="SMD Capacitor Book",
                bin_number="Page 1",
                cost=0.01,
                package_type="0805",
            ),
            BulkImportItem(
                part_number="LED-RED-0805",
                description="Red SMD Indicator LED 20mA",
                quantity=200,
                location="LED Bin",
                bin_number="Box 12",
                cost=0.03,
                package_type="0805",
            ),
        ]

        response = client.bulk_import_parts(items)
        print("Bulk Import Complete:")
        print(f"  Added   : {len(response.added)} parts")
        print(f"  Updated : {len(response.updated)} parts")

        for part in response.added:
            print(f"  - Created: {part.part_number} (ID: {part.part_id}) at {part.location}")

    except BinnerConnectionError as ce:
        sys.stderr.write(f"Connection failed: {ce}\n")
    except BinnerAPIError as ae:
        sys.stderr.write(f"API error: {ae}\n")


if __name__ == "__main__":
    bulk_import_components()
