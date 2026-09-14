#!/usr/bin/env python3
"""
Example 5: In-Memory Cache Hydration from Database Export.

Downloads a complete database backup ZIP and populates the in-memory cache instantly
without triggering hundreds of individual HTTP requests.
Prerequisites: A running Binner instance (default: http://localhost:8090).
"""

from pathlib import Path
import sys
from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import BinnerAPIError, BinnerConnectionError


def backup_and_hydrate(output_dir: str = "./binner_backups") -> None:
    client = BinnerAPIProxy()

    try:
        client.login()

        # export_data downloads the ZIP archive and automatically hydrates _part_id_to_number
        archive = client.export_data(export_format="csv", populate_cache=True)
        print(f"Archive loaded with {len(archive.files)} database tables.")

        # Save CSV files to disk
        saved_files = archive.save_to_disk(output_dir)
        print(f"Exported files to {output_dir}:")
        for f in saved_files:
            print(f"  - {f.name} ({f.stat().st_size} bytes)")

        # Verify cache resolution without additional HTTP calls
        if client._part_id_to_number:
            sample_id = next(iter(client._part_id_to_number))
            sample_pn = client._part_id_to_number[sample_id]
            print(f"\nCache sample: Part ID {sample_id} -> '{sample_pn}' (Cached total: {len(client._part_id_to_number)})")

    except BinnerConnectionError as ce:
        sys.stderr.write(f"Connection failed: {ce}\n")
    except BinnerAPIError as ae:
        sys.stderr.write(f"API error: {ae}\n")


if __name__ == "__main__":
    backup_and_hydrate()
