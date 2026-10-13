---
name: binner
description: Binner MCP Server interfaces with local Binner instances to manage electronic component inventory, category hierarchies, Maker projects, and Bill of Materials (BOM).
---

# Binner Domain & Workflow Guide

## 1. Core Task Workflows

### When Searching or Inspecting Components
- Search inventory via `list_parts` with query keywords, category paths/names, bin numbers, locations, packages, manufacturers, low-stock filters, and explicit projected `fields` (e.g. `fields=['quantity', 'location', 'bin_number']`). Avoid unprojected dumps.
- Inspect category hierarchy via `list_part_types` using `depth` (`depth=1` for root categories, `depth=2` for families) or `root_id`/`root_name` with `include_part_counts=True`.
- Retrieve full component specifications, KiCad symbols, bin locations, and datasheets via `get_parts`.
- Audit co-located items: Retrieve a component's `bin_number` and `bin_number2`, then query `list_parts(bin_number=...)` to view co-located parts in the same container.

### When Cataloging New Components
- **Container Typology Routing**: Route components to target containers using `references/bin_content_typology.md`. Update this file whenever container structures change. Assign containers autonomously based on form factor without interrogating the user.
- **Pre-Ingestion Duplicate & Stock Check**: Query `list_parts(bin_number="<bin_number>", bin_number2="<bin_number2>", fields=['quantity'])` in the resolved target container before adding.
  - If a matching part already exists: Update its stock additively (`quantity = existing + added`) using minimal patch `save_parts(parts=[{"part_id": id, "quantity": new_qty}])`.
  - If no match exists: Persist the new part via `save_parts`.
- **Part Number Formatting Invariant**: Standardize `part_number` into a natural Title Case phrase optimized for substring queries: `[Size/Value/ID] [Noun] [Secondary Specs]` (regex: `^([A-Za-z0-9\.\/Ωμx-]+)\s+([A-Za-z]+)\s+(.*)$`). E.g. `56kΩ Resistor 1/8W Axial`, `M3 Screw 8mm DIN 7985 Black`, `7x10mm Tube Silicone Clear 1m`.
- **Category Hierarchy Resolution**: Pass category paths (`Passives::Resistors::SMD`), leaf names, or numeric IDs (`part_type: <int>`). Missing parent nodes in valid path strings are created automatically. If a name is ambiguous, resolve with a full path or ID.
- **Creation Validation**: Satisfy creation fields: `part_number`, `part_type`, `quantity` ($\ge 0$), `location` (default storage room or rack name, e.g. `"MAIN"`), and storage bins. Omit `cost` and `currency` by default when unpriced or 0.
- **Zero-Side-Effects Validation**: `save_parts` validates the entire batch before writing (`extra="forbid"`). If any item fails validation, mutation halts immediately with zero database changes.

### When Auditing or Updating Stock
- **Anti-Breakdown Scope Repetition**: When proposing stock adjustments or container reconciliations, explicitly list every line item in the container scope (both modified and unmodified) to prevent communication breakdown. Never present sparse delta-only listings.
- **Minimal Patch Semantics**: When updating existing components, pass only `part_id`/`part_number` and the modified fields. Never echo back unmodified fields (prevents token bloat, unwanted defaults, and concurrency overwrites). No preparatory pre-fetching required.
- Decommission obsolete stock in bulk via `delete_parts` (`part_numbers` or `part_ids`).
- Remove obsolete categories via `delete_part_types` (`ids` or `names`).

### When Managing Projects & BOMs
- Initialize or update maker projects via `save_projects` (`name`, `description`, optional `id`, `archived`).
- Query maker projects via `list_projects` or `get_projects`.
- Allocate and edit BOM line items via `manage_bom_parts`, linking components with per-board required quantities, reference designators (e.g. `R1, R2`), and optional stock adjustments (`adjust_stock_delta`).
- Delete obsolete projects via `delete_projects`.

### When Deducting Stock for Production Builds
- Verify project readiness via `get_projects(project_ids=[...], include_bom=True)`.
- Deduct stock for production units via `consume_project_bom(project_id=..., build_quantity=N)`.
- **Automated BOM Shortage Circuit Breaker**: Pre-flight checks on-hand stock across all BOM items before executing deductions. If stock is insufficient for any item, execution aborts immediately, returns a shortage breakdown matrix, and leaves inventory untouched.

---

## 2. MCP Tool Directory

| Tool | Primary Parameters | Description |
| :--- | :--- | :--- |
| `get_system_status` | `check_cloud: bool = False` | Probe connectivity, version, identity, and inventory statistics. |
| `list_parts` | `query`, `part_type`, `bin_number`, `bin_number2`, `location`, `package_type`, `manufacturer`, `low_stock_only`, `fields`, `page`, `limit`, `sort_by`, `direction` | Paginated component search with metadata filtering and field projection. |
| `get_parts` | `part_numbers: str[]`, `part_ids: int[]`, `fields: str[]` | Batch component inspection returning details, bin locations, and datasheets. |
| `save_parts` | `parts: PartSaveInput[]` | Batch create or update components with strict pre-flight validation. |
| `delete_parts` | `part_numbers: str[]`, `part_ids: int[]` | Batch component deletion by part number or ID. |
| `list_projects` | `query`, `page`, `limit`, `sort_by`, `direction` | Paginated search of maker projects. |
| `get_projects` | `project_ids: int[]`, `names: str[]`, `include_bom: bool = False` | Batch maker project retrieval with optional normalized BOM breakdown. |
| `save_projects` | `projects: ProjectSaveInput[]` | Batch create or update maker projects. |
| `delete_projects` | `project_ids: int[]`, `names: str[]` | Batch project deletion by ID or name. |
| `consume_project_bom` | `project_id: int`, `name: str`, `build_quantity: int = 1` | Deduct component stock for board unit assembly with shortage circuit breaker. |
| `list_part_types` | `depth`, `root_id`, `root_name`, `include_descriptions`, `include_part_counts` | Hierarchical category tree optimized for minimal LLM context usage. |
| `save_part_types` | `part_types: PartTypeSaveInput[]` | Batch create or update category nodes. |
| `delete_part_types` | `ids: int[]`, `names: str[]` | Batch category deletion by ID or name. |
| `manage_bom_parts` | `project_id: int`, `parts: BomPartInput[]` | Batch allocate, modify, or remove BOM line items for a project. |
| `lookup_cloud_parts` | `part_numbers: str[]` | Query Binner Swarm cloud for pinouts, package footprints, and datasheets. |

---

## 3. Structured Batch Input Schemas

All models enforce `extra="forbid"` (`additionalProperties: false`). Unknown fields are strictly rejected.

### 3.1 `PartSaveInput` (`save_parts`)

| Field Name | Type | Default | Description & Constraints |
| :--- | :--- | :--- | :--- |
| `part_number` | `string` | **Required** | Standardized Value/Size-first natural phrase (`[Size/Value] [Noun] [Specs]`). Non-empty. |
| `part_type` | `string` \| `int` | `None` | Overloaded category identifier: hierarchy path (e.g. `"Passives::Resistors::SMD"`), leaf name, or numeric ID. |
| `quantity` | `int` \| `string` | `0` | Absolute count of physical units in stock ($\ge 0$). |
| `low_stock_threshold` | `int` \| `string` | `0` | Reorder alert threshold ($\ge 0$). |
| `location` | `string` | `None` | Storage location facility (e.g. `"MAIN"`, room, rack, or shelf name). |
| `bin_number` | `string` | `None` | Primary storage bin / drawer identifier (e.g. `"A1-04"`, `"Drawer 12"`). |
| `bin_number2` | `string` | `None` | Secondary storage bin, sub-compartment, or bag label. |
| `cost` | `float` \| `string` | `0.0` | Unit purchase cost ($\ge 0.0$). Omit by default when unpriced or `0.0`. |
| `currency` | `string` | `None` | Currency code (`"USD"`, `"EUR"`). Omit by default when unpriced. |
| `package_type` | `string` | `None` | Component footprint / package (`"0805"`, `"SOIC-8"`, `"1/8W Axial"`). |
| `manufacturer` | `string` | `None` | Component manufacturer name. |
| `manufacturer_part_number` | `string` | `None` | Manufacturer internal part number if different from `part_number`. |
| `description` | `string` | `None` | Free-form technical description or notes. |
| `datasheet_url` | `string` | `None` | Direct HTTP/HTTPS URL to component datasheet PDF. |
| `product_url` | `string` | `None` | Direct URL to distributor or supplier product web page. |
| `part_id` | `int` \| `string` | `None` | Database primary key of existing part. Passed for minimal patch updates. |
| `create_only` | `bool` | `False` | If `True`, halts mutation with an error if the part already exists. |

### 3.2 Other Batch Input Models

* **`ProjectSaveInput` (`save_projects`):** `name` (required for new), `id` (for updates), `description`, `archived` (`bool`).
* **`PartTypeSaveInput` (`save_part_types`):** `name` (required for new), `id` (for updates), `parent_id` (`0`/`null` for root), `description`.
* **`BomPartInput` (`manage_bom_parts`):** `part_number` or `part_id` (required), `quantity` ($\ge 1$), `reference_designator` (e.g. `"R1, C1"`), `notes`, `adjust_stock_delta` (additive stock adjustment), `remove` (`bool`).

---

## 4. Domain Entity Models & Response Shapes

### 4.1 Component Entity (`PartResponse`)
Delivered by `get_parts` and `list_parts`:
* Identifiers: `part_id` (`int`), `part_number` (`str`), `short_id` (`str`), `manufacturer_part_number` (`str`).
* Stock & Location: `quantity` (`int`), `low_stock_threshold` (`int`), `location` (`str`), `bin_number` (`str`), `bin_number2` (`str`).
* Technical Specs: `part_type` (resolved category path), `package_type` (`str`), `value` (`str`), `description` (`str`), `mounting_type_id` (`0`=Unknown, `1`=SMD, `2`=THT).
* Cost & Sourcing: `cost` (`float`), `currency` (`str`), `manufacturer` (`str`), `datasheet_url` (`str`), `product_url` (`str`).
* KiCad Bindings: `symbol_name` (`str`), `footprint_name` (`str`).

### 4.2 Normalized BOM Item (`BomPartResponse`)
Delivered by `get_projects(include_bom=True)`:
* `assignment_id` (`int`), `part_id` (`int`), `part_number` (`str`), `quantity` (required per board), `reference_designator` (`str`), `stock_on_hand` (`int`), `package_type` (`str`).

---

## 5. Cross-Cutting Operational Constraints

1. **System Health & Connectivity Verification:**
   - Call `get_system_status` to probe backend connectivity, retrieve Binner version, and inspect inventory totals (unique parts count, total stock, valuation, low-stock count).
   - Set `check_cloud=True` when cloud connectivity to Binner Swarm needs to be validated.

2. **Direct Native MCP Chunking & Fault Tolerance:**
   - Execute all database mutations via direct native MCP tool calls (`save_parts`, `list_parts`, etc.). Never write or execute ad-hoc external python or shell scripts.
   - Chunk operations into manageable batches (30–40 items) to guarantee atomicity and clear logging.
   - Retries transient network errors (502–504) once after a 3-second delay. Non-transient errors fail immediately with 0 retries. Partial successes persist valid items and report failed ones in `failed`.

3. **Hierarchical Character Page Priority (Unicode Homoglyphs):**
   - **Tier 1 (Base Latin / ASCII `U+0020`–`U+007E`):** Primary authority for text, punctuation, and separators. Use ASCII comma `,` and Latin `M` for metric fasteners.
   - **Tier 2 (Greek & Coptic `U+0370`–`U+03FF`):** Primary authority for SI units. Strictly use Greek Capital Omega `Ω` (`U+03A9`) for ohms (reject `Ω`, `ohm`, `R`) and Small Mu `μ` (`U+03BC`) for micro (reject `µ`, `u`).
   - **Tier 3 (Latin-1 Supplement `U+0080`–`U+00FF`):** Non-Greek engineering symbols (`°`, `±`). Demote characters with Tier 2 equivalents.
   - **Tier 4 (Deprecated / Compatibility Blocks `0x20`–`0x21`, `0xFF`):** General punctuation, letterlike symbols, and fullwidth forms are strictly deprecated; decompose to Tier 1 or Tier 2.

4. **Output Token Efficiency & Response Conciseness:**
   - Never emit tool argument JSON inside `<thought>` or thinking blocks; invoke tools as native structured tool calls.
   - Keep final confirmations concise (1–2 sentences). Do not echo large markdown summary tables or repeat full field lists.
