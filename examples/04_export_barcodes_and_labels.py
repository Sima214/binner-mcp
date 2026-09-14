#!/usr/bin/env python3
"""
Example 4: Generating Barcodes and Component Label Images.

Generates raw barcode images (PNG) and component label previews.
Prerequisites: A running Binner instance (default: http://localhost:8090).
"""

from pathlib import Path
import sys
from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import BinnerAPIError, BinnerConnectionError


def export_part_labels(part_number: str = "NE555P", output_dir: str = "./labels") -> None:
    client = BinnerAPIProxy()

    try:
        client.login()

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        # 1. Fetch raw barcode image (PNG)
        barcode_png = client.get_part_barcode(part_number)
        barcode_file = out_path / f"{part_number}_barcode.png"
        barcode_file.write_bytes(barcode_png)
        print(f"Saved barcode ({len(barcode_png)} bytes) to: {barcode_file}")

        # 2. Fetch label print preview image
        label_png = client.print_part_label(
            part_number=part_number,
            generate_image_only=True,
        )
        label_file = out_path / f"{part_number}_label.png"
        label_file.write_bytes(label_png)
        print(f"Saved label preview ({len(label_png)} bytes) to: {label_file}")

    except BinnerConnectionError as ce:
        sys.stderr.write(f"Connection failed: {ce}\n")
    except BinnerAPIError as ae:
        sys.stderr.write(f"API error: {ae}\n")


if __name__ == "__main__":
    export_part_labels()
