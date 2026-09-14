#!/usr/bin/env python3
"""
Example 6: Querying Cloud Schematics, Datasheets & Pinouts (Binner Swarm).

Searches the Binner Swarm cloud service (https://swarm.binner.io) for pinout maps
and direct PDF datasheet links.
Prerequisites: Outbound internet connectivity to swarm.binner.io.
"""

import sys
from binner_mcp.swarmer.client import SwarmClient
from binner_mcp.swarmer.exceptions import SwarmError, SwarmRateLimitError


def lookup_cloud_component(part_query: str = "LM358") -> None:
    swarm = SwarmClient()

    try:
        status = swarm.get_status()
        print(f"Swarm Service Online: {status.is_up}")

        result = swarm.search_parts(part_number=part_query)

        if not result.is_success or not result.response:
            print(f"No Swarm results found for '{part_query}'. Errors: {result.errors}")
            return

        for part in result.response.parts:
            print(f"\n=== {part.name} ({part.part_type or 'Electronic Component'}) ===")
            print(f"Description: {part.description}")

            for mfg in part.part_number_manufacturers:
                print(f"  Manufacturer: {mfg.manufacturer_name}")

                for ds in mfg.datasheets:
                    print(f"    Datasheet: {ds.title}")
                    print(f"      PDF Link: {ds.direct_pdf_url}")

                for po in mfg.pinouts:
                    print(f"    Pinout: {po.package_name} ({po.pin_count} pins)")
                    if po.export_image and po.export_image.url:
                        print(f"      Diagram: {po.export_image.url}")

                for supp in mfg.suppliers:
                    print(
                        f"    Supplier: {supp.supplier_name} | "
                        f"Stock: {supp.quantity_available} | Cost: ${supp.cost}"
                    )

        if swarm.last_rate_limit:
            rl = swarm.last_rate_limit
            print(f"\nRate Limit Quota: {rl.remaining} remaining of {rl.limit}")

    except SwarmRateLimitError as rle:
        sys.stderr.write(f"Rate limit exceeded: {rle}\n")
    except SwarmError as se:
        sys.stderr.write(f"Swarm request error: {se}\n")


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "LM358"
    lookup_cloud_component(query)
