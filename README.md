# Binner MCP Server

A Model Context Protocol (MCP) server and Python API client providing a high-performance proxy to local **Binner** inventory instances (.NET 8 / Kestrel) and the **Binner Swarm** cloud component service (`https://swarm.binner.io`).

---

## Overview

### System Architecture

The codebase implements a decoupled dual-layered architecture with a common foundation core:

```
+-----------------------------------------------------------------------------------+
|                        Layer 2: MCP Protocol Binding Layer                        |
|                                                                                   |
|  - MCP Server Setup (binner_mcp.mcp.server.BinnerMCPServer)                       |
|  - Transports: stdio (JSON-RPC), http (Streamable HTTP), sse (Legacy SSE)         |
|  - 15 Registered Tools (System, Cloud, Inventory, Categories, Projects, BOM)      |
|  - 5 Dynamic Resources (Status, Categories, Low-Stock, Project BOM, Part Details) |
|  - Single-Thread FIFO Task Queue (ThreadPoolExecutor(max_workers=1))              |
|  - Pre-Flight Zero-Side-Effects Validation & extra="forbid" Safety Guard          |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                       Layer 1: Python API Client Interfaces                       |
|                                                                                   |
|  Layer 1A: Local Binner API Client             Layer 1B: Swarmer Cloud Client     |
|  (binner_mcp.api.client.BinnerAPIProxy)        (binner_mcp.swarmer.SwarmClient)   |
|  ├── PartsComp (CRUD, stock deltas, labels)    ├── Pinouts, Footprints, Schematics|
|  ├── ProjectsComp (Maker projects, BOM items)  ├── Direct PDF Datasheet URLs      |
|  ├── PartTypesComp (Category tree management)  └── Quota Rate-Limit Tracking      |
|  ├── DataComp (CSV bulk import, ZIP export)                                       |
|  ├── SystemComp (Ping, version, server logs)                                      |
|  ├── PartCacheComp (Bidirectional ID <-> PN)                                      |
|  └── BaseBinnerClient (JWT + HttpOnly cookie)                                     |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                       Common Core & Upstream Services                             |
|                                                                                   |
|  binner_mcp.common:                                                               |
|  - BaseHttpClient (requests.Session pooling, threading.RLock re-entrant safety)   |
|  - logging (sys.stderr routing, custom TRACE level 5, sensitive data redaction)   |
|  - Pydantic v2 Base Models & Unified Exception Hierarchy                          |
|                                                                                   |
|  Upstream Targets:                                                                |
|  - Local Binner Instance (.NET 8 / Kestrel, default: http://127.0.0.1:8090)       |
|  - Binner Swarm Cloud Service (https://swarm.binner.io)                           |
+-----------------------------------------------------------------------------------+
```

#### Layer Breakdown

1. **Layer 1A: Binner Python API Interface (`binner_mcp.api`)**:
   * Programmatic, MCP-agnostic REST client (`BinnerAPIProxy`) for local Binner instances.
   * Composed from modular domain components (`PartsComp`, `ProjectsComp`, `PartTypesComp`, `DataComp`, `SystemComp`).
   * **In-Memory Identity Cache (`PartCacheComp`)**: Bidirectional mapping (`_part_id_to_number`, `_part_number_to_id`) that automatically resolves missing part numbers or IDs, eliminating upstream EF Core omission bugs.
   * **Dual-Token Authentication (`BaseBinnerClient`)**: Manages JWT Bearer tokens and HttpOnly refresh cookies via `POST /api/authentication/refresh-token`, with 1-second timestamp granularity handling and automatic login fallback.
2. **Layer 1B: Swarmer Cloud API Interface (`binner_mcp.swarmer`)**:
   * Dedicated REST client (`SwarmClient`) for the Binner Swarm cloud service (`https://swarm.binner.io`).
   * Searches and retrieves pinout diagrams, package footprints, and direct PDF datasheets.
   * Automatic rate-limit tracking via response headers (`x-rate-limit-limit`, `x-rate-limit-remaining`, `x-rate-limit-reset`) and error classification (`SwarmRateLimitError`, `SwarmTimeoutError`).
3. **Common Core Foundation (`binner_mcp.common`)**:
   * `BaseHttpClient`: Connection-pooled HTTP session manager guarded by `threading.RLock`, ensuring thread safety for cookie jars and token rotation.
   * `logging`: Stdio transport-safe logging strictly targeting `sys.stderr`, supporting custom `TRACE` level (level 5) and recursive credential/token redaction (`sanitize_for_trace`).
4. **Layer 2: MCP Protocol Binding Layer (`binner_mcp.mcp`)**:
   * `BinnerMCPServer` exposes 15 tools and 5 dynamic resources using Python MCP SDK 2.
   * Multi-transport support: Standard I/O (`stdio`), modern Streamable HTTP (`http`), and legacy Server-Sent Events (`sse`).
   * Single-thread FIFO task queue (`ThreadPoolExecutor(max_workers=1)`) executing sync proxy operations sequentially to eliminate race conditions on session cookies or access tokens.
   * Strict argument validation (`extra="forbid"`) and category path delimiter resolution (e.g. `Passives::Resistors::SMD`).

---

### Key Capabilities

* **Dual Interface**: Operate as a standalone Python library (`BinnerAPIProxy`, `SwarmClient`) or as an autonomous MCP server for AI agents.
* **Component Inventory Lifecycle**: Batch creation/updates (`save_parts`), deletion (`delete_parts`), selective field projection (`fields=['quantity', 'location', 'bin_number']`), and low-stock alerting.
* **Strict Stock Adjustment Semantics**: Explicit separation between absolute on-hand stock counts (`save_parts`, `PUT /api/part`) and additive deltas (`adjust_stock_delta`, `POST /api/part/quantity`, `/increment`, `/decrement`).
* **Hierarchical Category Management**: Configurable delimiter-based category paths (default: `::`, e.g. `Passives::Resistors::SMD`), automatic parent node provisioning, ambiguity detection with candidate suggestions, and lightweight tree inspection (`depth`, `root_id`, `root_name`).
* **Maker Projects & BOM Engineering**: Project registration, Bill of Materials component allocation with silkscreen reference designators (e.g. `R1, R2, C1`), and optional simultaneous stock delta adjustments.
* **Production Batch Deduction with Shortage Circuit Breaker**: Automated component deduction (`consume_project_bom`) for batch assemblies. If on-hand stock is insufficient for any BOM item, execution halts immediately with zero database mutations and returns a detailed shortage matrix.
* **Swarm Cloud Component Enrichment**: Live querying of `swarm.binner.io` for pinouts, package footprints, and manufacturer datasheets via `lookup_cloud_parts`.
* **Pre-Flight Zero-Side-Effects Validation**: In batch operations (`save_parts`, `manage_bom_parts`), full payload validation runs before any mutation executes; an error on any item aborts the entire batch.
* **Strict Parameter Enforcement**: All MCP tools and models reject unknown arguments (`extra="forbid"`), preventing hallucinated arguments or subtle typos from corrupting inventory.
* **Deterministic Part Identity Resolution**: Automatic reconciliation between numeric part IDs and alphanumeric part numbers, circumventing Binner backend query omission bugs.
* **Stdio Transport Safety**: JSON-RPC transport stream protection via strict `sys.stderr` log routing.

---

## Installation

### Prerequisites & Required Packages

* **Python:** Version 3.10 or higher.
* **Binner Instance:** A running local Binner server (default: `http://127.0.0.1:8090`).
* **Core Dependencies:**
  * **`mcp`** (>=1.0.0): Official Model Context Protocol SDK providing tool, resource, and transport implementations.
  * **`requests`** (>=2.31.0): HTTP client managing session connection pooling, cookie jars, and token refreshes.
  * **`pydantic` & `pydantic-settings`** (>=2.0.0): Data validation, model definitions, and typed configuration loading.

### Virtual Environment & Package Setup

Using an isolated virtual environment is recommended to manage dependencies cleanly:

```bash
# 1. Create a virtual environment
python3 -m venv .venv

# 2. Activate the virtual environment
# Linux / macOS:
source .venv/bin/activate
# Windows:
# .venv\Scripts\activate

# 3. Install package and dependencies in editable mode
pip install -e .

# Or install with optional development tools:
pip install -e ".[dev]"
```

---

### Agent Skill Integration (`docs/SKILL.md`)

The repository includes a domain skill conforming to the open **Agent Skills** standard in [`docs/SKILL.md`](docs/SKILL.md). While MCP provides the execution layer (tools and resources), the skill equips AI assistants with procedural knowledge: the 6-step lifecycle workflow, batch schemas, parameter constraints (`extra="forbid"`), and the automated BOM shortage circuit breaker. It leverages **progressive disclosure** (indexing metadata at startup and loading instructions on demand).

#### 1. Native Skill Clients (Antigravity, Claude Code, Cursor, Copilot)

Enables automatic discovery and progressive disclosure without manual prompt injection.

**Installation (Project or Global):**

```bash
# Workspace / Project install (shared with team via version control):
mkdir -p .agents/skills/binner
cp docs/SKILL.md .agents/skills/binner/SKILL.md

# Or Global / User install (available across all local workspaces):
mkdir -p ~/.gemini/config/skills/binner
cp docs/SKILL.md ~/.gemini/config/skills/binner/SKILL.md
```

*Symlinks are also supported: `ln -s "$(pwd)/docs/SKILL.md" ~/.gemini/config/skills/binner/SKILL.md`.*

**Discovery Paths:**
* **Google Antigravity / Gemini CLI:**
  * Workspace: `.agents/skills/binner/SKILL.md` (or `.agent/skills/binner/SKILL.md`)
  * Global: `~/.gemini/config/skills/binner/SKILL.md` (or `~/.gemini/antigravity/skills/binner/SKILL.md`)
* **Claude Code:**
  * Workspace: `.claude/skills/binner/SKILL.md`
  * Global: `~/.claude/skills/binner/SKILL.md`
* **Cursor (Agent Mode):** `.agents/skills/binner/SKILL.md` or `.cursor/skills/binner/SKILL.md`
* **GitHub Copilot (Agent Mode):** `.agents/skills/binner/SKILL.md` or `.github/skills/binner/SKILL.md`

---

#### 2. Instruction & Rule-Based Clients (Claude Desktop, Cursor Rules, Cline / Roo Code)

For clients without native skill discovery directories, reference `docs/SKILL.md` directly in configuration or rule files.

**Configuration Snippet:**

```markdown
# Include in your client instructions / rule file:
Read and adhere to the Binner domain workflows and constraints in docs/SKILL.md
when handling electronic parts, category hierarchies, Maker projects, or BOM assembly.
```

**Configuration Paths:**
* **Cursor:** Add reference or include contents in `.cursorrules` or `.cursor/rules/binner.mdc`.
* **VS Code (Cline / Roo Code):** Include path or content in `.clinerules`.
* **Claude Desktop:** Attach `docs/SKILL.md` to **Project Knowledge** or add reference in Project Custom Instructions.
* **GitHub Copilot:** Add reference to `.github/copilot-instructions.md`.

---

## Configuration

Configuration parameters are evaluated in the following order of precedence (highest to lowest):
1. **Command-Line Arguments**
2. **Environment Variables**
3. **Configuration File (`binnermcp_config.json`)**
4. **Built-in Defaults**

### Configuration Parameters

| Parameter | CLI Flag | Environment Variable | Default | Description |
|---|---|---|---|---|
| `base_url` | — | `BINNER_BASE_URL` | `http://localhost:8090` | Base URL of local Binner instance |
| `username` | — | `BINNER_USERNAME` | `admin` | Username for Binner authentication |
| `password` | — | `BINNER_PASSWORD` | `admin` | Password for Binner authentication |
| `log_level` | `--log-level` | `BINNER_LOG_LEVEL` | `INFO` | Logging level (`TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `transport` | `--transport` | `BINNER_MCP_TRANSPORT` | `stdio` | MCP transport (`stdio`, `http`, or `sse`) |
| `host` | `--host` | `BINNER_MCP_HOST` | `127.0.0.1` | Bind address for HTTP / SSE transport |
| `port` | `--port` | `BINNER_MCP_PORT` | `8000` | Port for HTTP / SSE transport |
| `category_delimiter` | `--category-delimiter` | `BINNER_CATEGORY_DELIMITER` | `::` | Delimiter for category hierarchy paths |
| `log_file` | `--log-file` | `BINNER_LOG_FILE` | `None` | Optional path to write log output in addition to stderr |
| `retry_delay` | `--retry-delay` | `BINNER_RETRY_DELAY` | `3.0` | Delay in seconds between transient retry attempts |
| `retry_count` | `--retry-count` | `BINNER_RETRY_COUNT` | `1` | Max retry attempts for transient network errors |
| *config file* | `--config` | `BINNER_MCP_CONFIG` | `./binnermcp_config.json` | Explicit path to `binnermcp_config.json` |

### Configuration File Resolution (`binnermcp_config.json`)

If no CLI flags or environment variables are provided, values are read from `binnermcp_config.json`. The server searches the following paths in order:
1. Path passed via `--config` or `BINNER_MCP_CONFIG`
2. Current working directory: `./binnermcp_config.json`
3. Project root directory
4. User configuration directory: `~/.config/binnermcp/binnermcp_config.json`
5. System-wide configuration directory: `/etc/binnermcp/binnermcp_config.json`

Example `binnermcp_config.json`:

```json
{
  "base_url": "http://localhost:8090",
  "username": "admin",
  "password": "your-password",
  "log_level": "INFO",
  "transport": "stdio",
  "host": "127.0.0.1",
  "port": 8000,
  "category_delimiter": "::",
  "retry_delay": 3.0,
  "retry_count": 1
}
```

---

## MCP Server Usage

All logging routes strictly to `sys.stderr` to preserve JSON-RPC stream integrity.

```bash
# 1. Run with default stdio transport (local subprocess)
binner-mcp

# 2. Run over modern Streamable HTTP transport on port 8000
binner-mcp --transport http --host 127.0.0.1 --port 8000

# 3. Run over legacy Server-Sent Events (SSE) transport on port 8000
binner-mcp --transport sse --host 127.0.0.1 --port 8000

# 4. Run via Python module with explicit config and TRACE logging
python -m binner_mcp.main --config /path/to/binnermcp_config.json --log-level TRACE
```

### Client Integration

#### 1. Stdio Clients (Gemini / Antigravity, Claude Desktop, Cursor, VS Code)

Launches the server directly as a local subprocess over `stdio`.

**Configuration (`mcpServers` block):**

```json
{
  "mcpServers": {
    "binner": {
      "command": "/path/to/venv/bin/binner-mcp",
      "env": {
        "BINNER_BASE_URL": "http://127.0.0.1:8090",
        "BINNER_USERNAME": "admin",
        "BINNER_PASSWORD": "your-password"
      }
    }
  }
}
```

*If invoking via Python directly, set `"command": "/path/to/venv/bin/python"` with `"args": ["-m", "binner_mcp.main"]`.*

**Configuration Paths:**
* **Gemini / Antigravity:** `~/.gemini/antigravity/mcp_config.json`
* **Claude Desktop:**
  * Linux: `~/.config/Claude/claude_desktop_config.json`
  * macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
  * Windows: `%APPDATA%\Claude\claude_desktop_config.json`
* **VS Code (Cline / Roo Code):** `cline_mcp_settings.json`
* **Cursor:** Under **Settings > Features > MCP**, click **+ Add New MCP Server** (`Name: binner`, `Type: command`, `Command: /path/to/venv/bin/binner-mcp`).

---

#### 2. Local HTTP & SSE Clients

> **Security Notice:** Binner MCP is a local private sidecar. **Never expose this server to external networks or the public internet.**

For web-based or remote interfaces connecting via HTTP instead of a subprocess, run the server bound **strictly to localhost (`127.0.0.1`)**:

```bash
# Modern Streamable HTTP (MCP SDK 2):
binner-mcp --transport http --host 127.0.0.1 --port 8000

# Legacy SSE:
binner-mcp --transport sse --host 127.0.0.1 --port 8000
```

---

## MCP API Reference

### Tools Directory (15 Registered Tools)

All tools enforce strict argument checking (`extra="forbid"`) and execute through a single-thread FIFO proxy queue.

| Tool Name | Domain | Primary Parameters | Summary |
|---|---|---|---|
| `get_system_status` | System | `check_cloud: bool = False` | Probe Binner connectivity, version, identity, and inventory statistics. |
| `lookup_cloud_parts` | Cloud | `part_numbers: str[]` | Query Binner Swarm cloud for pinouts, package footprints, and datasheets. |
| `list_parts` | Inventory | `query`, `part_type`, `bin_number`, `location`, `package_type`, `manufacturer`, `low_stock_only`, `fields`, `page`, `limit`, `sort_by`, `direction` | Paginated component search with metadata filtering and field projection. |
| `get_parts` | Inventory | `part_numbers: str[]`, `part_ids: int[]`, `fields: str[]` | Batch component inspection returning details, bin locations, and datasheets. |
| `save_parts` | Inventory | `parts: PartSaveInput[]` | Batch create or update components with strict pre-flight validation. |
| `delete_parts` | Inventory | `part_numbers: str[]`, `part_ids: int[]` | Batch component deletion by part number or ID. |
| `list_part_types` | Categories | `depth`, `root_id`, `root_name`, `include_descriptions`, `include_part_counts` | Hierarchical category tree optimized for minimal LLM context usage. |
| `save_part_types` | Categories | `part_types: PartTypeSaveInput[]` | Batch create or update category hierarchy nodes. |
| `delete_part_types` | Categories | `part_type_ids: int[]`, `names: str[]` | Batch category deletion by ID or name. |
| `list_projects` | Projects | `query`, `page`, `limit`, `sort_by`, `direction` | Paginated search of maker projects. |
| `get_projects` | Projects | `project_ids: int[]`, `names: str[]`, `include_bom: bool = False` | Batch maker project retrieval with optional normalized BOM breakdown. |
| `save_projects` | Projects | `projects: ProjectSaveInput[]` | Batch create or update maker projects. |
| `delete_projects` | Projects | `project_ids: int[]`, `names: str[]` | Batch project deletion by ID or name. |
| `manage_bom_parts` | BOM | `project_id: int`, `parts: BomPartInput[]` | Batch allocate, modify, or remove BOM line items for a project. |
| `consume_project_bom` | BOM | `project_id: int`, `name: str`, `build_quantity: int = 1` | Deduct component stock for board unit assembly with shortage circuit breaker. |

---

### Dynamic Resources Directory (5 Registered Resources)

| Resource URI | MIME Type | Description |
|---|---|---|
| `binner://status` | `application/json` | System health, version, auth identity, and aggregate inventory summary. |
| `binner://categories` | `application/json` | Hierarchical category tree with resolved category paths. |
| `binner://low-stock` | `application/json` | Filtered snapshot of components at or below low-stock thresholds. |
| `binner://projects/{project_id}/bom` | `application/json` | Complete Bill of Materials item breakdown for a specified project ID. |
| `binner://parts/{identifier}` | `application/json` | Complete specifications and category path for a part (by ID or part number). |

---

## Python API Quickstart

`binner-mcp` can also be used as a standard Python library:

```python
from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.swarmer.client import SwarmClient

# 1. Connect to local Binner instance
client = BinnerAPIProxy(base_url="http://localhost:8090", username="admin", password="admin")
if client.ping():
    client.login()
    print(f"Logged in as: {client.get_identity().name}")

# 2. Query low stock parts
low_stock = client.get_low_stock(results=5)
for part in low_stock.items:
    print(f"Low stock: {part.part_number} (Qty: {part.quantity}, Min: {part.low_stock_threshold})")

# 3. Add additive stock delta
client.increment_quantity(part_number="NE555P", quantity=10)

# 4. Query cloud datasheets & pinouts from Binner Swarm
swarm = SwarmClient()
result = swarm.search_parts(part_number="2N3904")
if result.is_success and result.response:
    for part in result.response.parts:
        print(f"Swarm part: {part.name} - {len(part.part_number_manufacturers)} manufacturers found")
```

---

## Development & Testing

Run tests and linting using the virtual environment:

```bash
# Run full test suite
virtenv/bin/python -m pytest tests/ -v

# Format with Black (100-char line length)
black --line-length 100 src/ tests/
```

---

## License

MIT License - see [LICENSE.txt](LICENSE.txt).
