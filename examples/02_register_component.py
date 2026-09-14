#!/usr/bin/env python3
"""
Example 2: Component Registration with Supplier Numbers & Footprints.

Registers a new electronic component with footprints, Digi-Key/Mouser part numbers,
and bin matrix storage coordinates.
Prerequisites: A running Binner instance (default: http://localhost:8090).
"""

import sys
from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import BinnerAPIError, BinnerConnectionError
from binner_mcp.api.models import CreatePartRequest


def register_microcontroller() -> None:
    client = BinnerAPIProxy()

    try:
        client.login()

        request = CreatePartRequest(
            part_number="RP2040",
            description="Dual ARM Cortex-M0+ MCU @ 133MHz with 264KB SRAM",
            quantity=50,
            low_stock_threshold=10,
            cost=1.00,
            currency="USD",
            package_type="QFN-56",
            mounting_type_id="SMD",
            location="Lab Bin Matrix",
            bin_number="Drawer-04",
            bin_number2="Sub-Bin-B",
            manufacturer="Raspberry Pi",
            manufacturer_part_number="SC0914(7)",
            digi_key_part_number="2648-SC0914(7)CT-ND",
            mouser_part_number="419-RP2040",
            product_url="https://www.raspberrypi.com/products/rp2040/",
            keywords=["microcontroller", "arm", "cortex-m0", "rp2040", "raspberry pi"],
            allow_potential_duplicate=True,
        )

        created = client.create_part(request)
        print("Part registered successfully!")
        print(f"Part ID  : {created.part_id}")
        print(f"Short ID : {created.short_id}")
        print(f"Location : {created.location} -> {created.bin_number}/{created.bin_number2}")

    except BinnerConnectionError as ce:
        sys.stderr.write(f"Connection failed: {ce}\n")
    except BinnerAPIError as ae:
        sys.stderr.write(f"API error: {ae}\n")


if __name__ == "__main__":
    register_microcontroller()
