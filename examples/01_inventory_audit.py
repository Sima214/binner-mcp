#!/usr/bin/env python3
"""
Example 1: Inventory Health Check & Low Stock Monitor.

Queries dashboard metrics and prints an alert table for parts below their reorder threshold.
Prerequisites: A running Binner instance (default: http://localhost:8090).
"""

import sys
from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import BinnerConnectionError


def run_inventory_audit() -> None:
    client = BinnerAPIProxy(base_url="http://localhost:8090", username="admin", password="admin")

    try:
        if not client.ping():
            sys.stderr.write("ERROR: Cannot ping Binner instance at http://localhost:8090\n")
            return

        client.login()
        summary = client.get_summary()
        print(f"=== Inventory Dashboard ({summary.currency}) ===")
        print(f"Unique Components : {summary.unique_parts_count}")
        print(f"Total Parts Stock : {summary.parts_count}")
        print(f"Inventory Value   : ${summary.parts_cost:,.2f}")
        print(f"Low Stock Items   : {summary.low_stock_count}\n")

        if summary.low_stock_count > 0:
            low_parts = client.get_low_stock(results=100)
            print(f"{'Part Number':<20} {'On Hand':<10} {'Threshold':<12} {'Location':<15}")
            print("-" * 60)
            for part in low_parts.items:
                print(
                    f"{part.part_number:<20} {part.quantity:<10} "
                    f"{part.low_stock_threshold:<12} {part.location or 'N/A':<15}"
                )

    except BinnerConnectionError as err:
        sys.stderr.write(f"Connection error: {err}\n")


if __name__ == "__main__":
    run_inventory_audit()
