# Developer Quickstart Guide

This guide demonstrates how to use `binner_mcp` as a Python library to interact with local Binner instances and the Binner Swarm cloud service.

---

## 1. Configuration & Client Initialization

`binner_mcp.config.load_config` resolves configuration from CLI arguments, environment variables, and `binnermcp_config.json`:

```python
from binner_mcp.config import load_config
from binner_mcp.api.client import BinnerAPIProxy

# Load configuration with automated precedence resolution
config = load_config()

# Initialize proxy client
client = BinnerAPIProxy(
    base_url=config.base_url,
    username=config.username,
    password=config.password,
    timeout=15.0,
)
```

Alternatively, instantiate `BinnerAPIProxy` directly with explicit parameters:

```python
from binner_mcp.api.client import BinnerAPIProxy

client = BinnerAPIProxy(
    base_url="http://127.0.0.1:8090",
    username="admin",
    password="my_secure_password",
    timeout=10.0,
)
```

---

## 2. Authentication & Session Lifecycle

The client manages session cookies and JWT Bearer tokens automatically. Explicit login is optional as requests trigger lazy auto-login when unauthenticated:

```python
# 1. Anonymous health check (does not trigger login or database writes)
is_alive = client.ping()
print(f"Binner reachable: {is_alive}")

# 2. Extract installed backend version (from X-Version ping header)
version_info = client.get_system_version()
print(f"Binner Version: {version_info['version']}")

# 3. Explicit login (stores JWT in headers and refreshToken in cookie jar)
tokens = client.login()
print(f"Logged in. JWT Token: {tokens.jwt_token[:15]}...")

# 4. Check user claims and identity
user = client.get_identity()
print(f"User: {user.name} ({user.email_address}), Admin: {user.is_admin}")

# 5. Check session state
print(f"Session active: {client.is_logged_in}")

# 6. Session logout (clears session headers and cookie jar)
# client.logout()
```

---

## 3. Inventory Querying & Filtering

### Paginated Part Listing

Use `list_parts` to query inventory with substring keyword searching, field filters, and sorting:

```python
# Query page 1 (10 parts), ordered by part number
response = client.list_parts(
    page=1,
    results=10,
    order_by="PartNumber",
    direction="Ascending",
    keyword="10k",
)

print(f"Total parts found: {response.total_items}")
for part in response.items:
    print(f"[{part.part_id}] {part.part_number} | Qty: {part.quantity} | Loc: {part.location}")
```

### Deterministic Part Retrieval

```python
# Lookup by exact part number (returns PartStoredFilesResponse with attached files)
part_detail = client.get_part_by_number("NE555P")
if part_detail:
    print(f"Part: {part_detail.part_number}, Package: {part_detail.package_type}")
    for file in part_detail.stored_files:
        print(f"  Attached File: {file.file_name} ({file.file_length} bytes)")

# Lookup by numeric part ID
part_by_id = client.get_part_by_id(42)
if part_by_id:
    print(f"Found part ID 42: {part_by_id.part_number}")
```

### Disjunctive (OR) Multi-Field Filtering

Use `filter_parts` when matching parts across multiple alternative criteria:

```python
# Match parts where manufacturer is TI OR package is SOIC-8 OR location is Drawer-A
filtered = client.filter_parts(
    manufacturers=["Texas Instruments", "Microchip"],
    package_types=["SOIC-8", "DIP-8"],
    locations=["Drawer-A"],
    page=1,
    results=25,
)
for part in filtered.items:
    print(f"{part.part_number} ({part.manufacturer}) at {part.location}")
```

---

## 4. Stock Adjustments: Additive Delta vs Absolute Replacement

> [!IMPORTANT]
> Binner's `POST /api/part/quantity` endpoints apply **additive deltas (`entity.Quantity += request.Quantity`)**, whereas `PUT /api/part` sets the **absolute quantity**.

### Adjusting Stock via Additive Deltas

```python
# Add 5 units to existing stock
res = client.increment_quantity(part_number="NE555P", quantity=5)
print(f"Updated on-hand stock: {res.quantity}")

# Deduct 2 units
res = client.decrement_quantity(part_number="NE555P", quantity=2)
print(f"Updated on-hand stock: {res.quantity}")

# Arbitrary delta with audit reason (negative or positive)
res = client.update_quantity(part_number="NE555P", quantity=-3, reason="Project prototype assembly")
print(f"Final on-hand stock: {res.quantity}")
```

### Setting Absolute Stock Quantity

To set an absolute stock level (e.g. during a physical audit count), use `update_part`:

```python
existing = client.get_part_by_number("NE555P")
if existing:
    # Set exact stock count to 50 units
    updated = client.update_part({
        "partId": existing.part_id,
        "partNumber": existing.part_number,
        "quantity": 50,
        "location": existing.location,
    })
    print(f"Absolute stock count set to: {updated.quantity}")
```

---

## 5. Component Lifecycle (CRUD)

### Create a Part

```python
from binner_mcp.api.models import CreatePartRequest

new_part = client.create_part(CreatePartRequest(
    part_number="STM32F401RE",
    description="ARM Cortex-M4 MCU 84MHz 512KB Flash",
    quantity=15,
    low_stock_threshold=5,
    cost=3.45,
    currency="USD",
    package_type="LQFP-64",
    location="MCU Cabinet",
    bin_number="B3-12",
    manufacturer="STMicroelectronics",
    manufacturer_part_number="STM32F401RET6",
    digi_key_part_number="497-14051-ND",
    keywords=["arm", "cortex-m4", "mcu", "stm32"],
))
print(f"Created part ID: {new_part.part_id}, ShortId: {new_part.short_id}")
```

### Update a Part

```python
from binner_mcp.api.models import UpdatePartRequest

updated_part = client.update_part(UpdatePartRequest(
    part_id=new_part.part_id,
    part_number="STM32F401RE",
    description="ARM Cortex-M4 MCU 84MHz 512KB Flash (Updated)",
    location="MCU Cabinet - Top Drawer",
    bin_number="B3-01",
    quantity=new_part.quantity,
))
print(f"Updated location: {updated_part.location}")
```

### Delete a Part

```python
# Delete by numeric partId (removes part from database and clears internal cache)
success = client.delete_part(new_part.part_id)
print(f"Deleted successfully: {success}")
```

---

## 6. Category Hierarchy & Part Types

```python
# 1. Fetch all top-level categories
categories = client.get_part_types()
for cat in categories:
    print(f"Category: {cat.name} (ID: {cat.part_type_id}, Part Count: {cat.parts})")

# 2. Fetch subcategories for a specific parent
subcategories = client.get_part_types(parent="Integrated Circuits")
for sub in subcategories:
    print(f"  Subcategory: {sub.name}")

# 3. Create a custom category
new_cat = client.create_part_type({
    "name": "FPGA Boards",
    "description": "Custom development and breakout FPGA boards",
})
print(f"Created Part Type ID: {new_cat.part_type_id}")

# 4. Delete category
client.delete_part_type(new_cat.part_type_id)
```

---

## 7. Projects & Bill of Materials (BOM)

```python
# 1. Create a project
project = client.create_project({
    "name": "Robotics Controller v2",
    "description": "Main motor driver and navigation board",
})
print(f"Created project: {project.name} (ID: {project.project_id})")

# 2. Add parts to project BOM
client.add_bom_part({
    "projectId": project.project_id,
    "partNumber": "NE555P",
    "quantity": 2,
    "referenceId": "U1, U2",
    "customDescription": "Timer circuits for watchdog pulse",
})

# 3. Fetch project BOM summary
bom = client.get_bom(project_id=project.project_id)
print(f"BOM Name: {bom.get('name')}, Components: {len(bom.get('parts', []))}")

# 4. Fetch BOM project list with part counts
bom_projects = client.get_bom_list()
for bp in bom_projects:
    print(f"Project '{bp.name}': {bp.part_count} parts, {bp.pcb_count} PCBs")
```

---

## 8. Querying Cloud Component Data (Binner Swarm)

Use `SwarmClient` to fetch schematics, pinouts, and parametric distributor data from `https://swarm.binner.io`:

```python
from binner_mcp.swarmer.client import SwarmClient

swarm = SwarmClient()

# 1. Health check
status = swarm.get_status()
print(f"Swarm online: {status.is_up}, DB online: {status.is_database_up}")

# 2. Search parts for pinouts, packages, and datasheets
result = swarm.search_parts(part_number="2N3904")
if result.is_success and result.response:
    for part in result.response.parts:
        print(f"Found part: {part.name} ({part.description})")
        for mfg in part.part_number_manufacturers:
            print(f"  Manufacturer: {mfg.manufacturer_name}")
            for ds in mfg.datasheets:
                print(f"    Datasheet: {ds.title} -> {ds.direct_pdf_url}")
            for po in mfg.pinouts:
                print(f"    Pinout: {po.package_name} ({po.pin_count} pins)")

# 3. Check rate limits
if swarm.last_rate_limit:
    print(f"Rate Limit: {swarm.last_rate_limit.remaining}/{swarm.last_rate_limit.limit}")
```
