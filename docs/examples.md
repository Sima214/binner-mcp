# Code Examples & Recipes

Ready-to-use, standalone Python scripts demonstrating common automation workflows using `binner_mcp`.

---

## Example 1: Inventory Health Check & Low Stock Monitor

Queries dashboard metrics and exports an alert table for parts below their reorder threshold:

```python
from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import BinnerConnectionError

def run_inventory_audit():
    client = BinnerAPIProxy(base_url="http://localhost:8090", username="admin", password="admin")

    try:
        if not client.ping():
            print("ERROR: Cannot ping Binner instance.")
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
                print(f"{part.part_number:<20} {part.quantity:<10} {part.low_stock_threshold:<12} {part.location or 'N/A':<15}")

    except BinnerConnectionError as err:
        print(f"Connection error: {err}")

if __name__ == "__main__":
    run_inventory_audit()
```

---

## Example 2: Component Registration with Supplier Numbers & Footprints

Registers an SMD microcontroller with Digi-Key / Mouser part numbers, footprint specifications, and storage coordinates:

```python
from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.models import CreatePartRequest

def register_microcontroller():
    client = BinnerAPIProxy()
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
    )

    created = client.create_part(request)
    print(f"Part registered successfully!")
    print(f"Part ID  : {created.part_id}")
    print(f"Short ID : {created.short_id}")
    print(f"Location : {created.location} -> {created.bin_number}/{created.bin_number2}")

if __name__ == "__main__":
    register_microcontroller()
```

---

## Example 3: Project Bill of Materials (BOM) Allocation

Creates a new maker project, queries available components, and assigns required quantities to the project BOM:

```python
from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.models import AddBomPartRequest, CreateProjectRequest

def setup_project_bom():
    client = BinnerAPIProxy()
    client.login()

    # 1. Create the project
    project = client.create_project(CreateProjectRequest(
        name="LoRa Environmental Sensor Node",
        description="Battery-powered weather telemetry node using RFM95W",
    ))
    print(f"Created project: {project.name} (ID: {project.project_id})")

    # 2. Add components to BOM
    bom_items = [
        {"partNumber": "RP2040", "qty": 1, "ref": "U1", "notes": "Main controller"},
        {"partNumber": "BME280", "qty": 1, "ref": "U2", "notes": "Temp/Humidity/Pressure sensor"},
        {"partNumber": "RFM95W-915S2", "qty": 1, "ref": "MOD1", "notes": "915MHz LoRa transceiver module"},
    ]

    for item in bom_items:
        client.add_bom_part(AddBomPartRequest(
            project_id=project.project_id,
            part_number=item["partNumber"],
            quantity=item["qty"],
            reference_id=item["ref"],
            notes=item["notes"],
        ))
        print(f"Assigned {item['partNumber']} ({item['ref']}) to BOM.")

    # 3. Verify assembled BOM
    bom_data = client.get_bom(project_id=project.project_id)
    print(f"\nFinal BOM Part Count: {len(bom_data.get('parts', []))}")

if __name__ == "__main__":
    setup_project_bom()
```

---

## Example 4: Generating Barcodes and Component Label Images

Generates barcode image data and prints/previews part labels:

```python
from pathlib import Path
from binner_mcp.api.client import BinnerAPIProxy

def export_part_labels(part_number: str, output_dir: str = "./labels"):
    client = BinnerAPIProxy()
    client.login()

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 1. Fetch raw barcode image (PNG)
    barcode_png = client.get_part_barcode(part_number)
    barcode_file = out_path / f"{part_number}_barcode.png"
    barcode_file.write_bytes(barcode_png)
    print(f"Saved barcode to: {barcode_file}")

    # 2. Fetch label print preview image
    label_png = client.print_part_label(
        part_number=part_number,
        generate_image_only=True,
    )
    label_file = out_path / f"{part_number}_label.png"
    label_file.write_bytes(label_png)
    print(f"Saved label preview to: {label_file}")

if __name__ == "__main__":
    export_part_labels("RP2040")
```

---

## Example 5: In-Memory Cache Hydration from Database Export

Downloads a complete database backup ZIP and populates the in-memory cache instantly without triggering hundreds of individual HTTP requests:

```python
from pathlib import Path
from binner_mcp.api.client import BinnerAPIProxy

def backup_and_hydrate():
    client = BinnerAPIProxy()
    client.login()

    # export_data downloads the ZIP archive and automatically hydrates _part_id_to_number
    archive = client.export_data(export_format="csv", populate_cache=True)
    print(f"Archive loaded with {len(archive.files)} database tables.")

    # Save CSV files to disk
    saved_files = archive.save_to_disk("./binner_backups")
    print(f"Exported files to ./binner_backups:")
    for f in saved_files:
        print(f"  - {f.name} ({f.stat().st_size} bytes)")

    # Test cache resolution (executes instantaneously from memory without network calls)
    resolved_id, resolved_pn = client._resolve_part_identity(part_id=1, part_number=None)
    print(f"\nCache test: Part ID 1 resolved to '{resolved_pn}'")

if __name__ == "__main__":
    backup_and_hydrate()
```

---

## Example 6: Querying Cloud Schematics & Pinouts (Binner Swarm)

Searches the Binner Swarm cloud service (`https://swarm.binner.io`) for pinout maps and direct PDF datasheet links:

```python
from binner_mcp.swarmer.client import SwarmClient
from binner_mcp.swarmer.exceptions import SwarmRateLimitError

def lookup_cloud_component(part_query: str):
    swarm = SwarmClient()

    try:
        result = swarm.search_parts(part_number=part_query)

        if not result.is_success or not result.response:
            print(f"No Swarm results found for '{part_query}'. Errors: {result.errors}")
            return

        for part in result.response.parts:
            print(f"\n=== {part.name} ({part.part_type or 'Electronic Component'}) ===")
            print(f"Description: {part.description}")

            for mfg in part.part_number_manufacturers:
                print(f"  Manufacturer: {mfg.manufacturer_name}")

                # Datasheets
                for ds in mfg.datasheets:
                    print(f"    Datasheet: {ds.title}")
                    print(f"      PDF Download: {ds.direct_pdf_url}")

                # Pinouts
                for po in mfg.pinouts:
                    print(f"    Pinout: {po.package_name} ({po.pin_count} pins)")
                    if po.export_image and po.export_image.url:
                        print(f"      Pinout Diagram: {po.export_image.url}")

                # Distributor stock
                for supp in mfg.suppliers:
                    print(f"    Supplier: {supp.supplier_name} | Stock: {supp.quantity_available} | Cost: ${supp.cost}")

    except SwarmRateLimitError as rle:
        print(f"Swarm rate limit exceeded: {rle}")

if __name__ == "__main__":
    lookup_cloud_component("LM358")
```

---

## Example 7: Bulk Ingestion via the Free Batch Endpoint

Imports multiple components in a single HTTP POST request using `POST /api/part/bulk`:

```python
from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.models import BulkImportItem

def bulk_import_components():
    client = BinnerAPIProxy()
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
    print(f"Bulk Import Complete:")
    print(f"  Added   : {len(response.added)} parts")
    print(f"  Updated : {len(response.updated)} parts")

    for part in response.added:
        print(f"  - Created: {part.part_number} (ID: {part.part_id}) at {part.location}")

if __name__ == "__main__":
    bulk_import_components()
```
