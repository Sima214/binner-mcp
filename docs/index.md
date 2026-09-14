# Binner Python Library Documentation

`binner_mcp` is a Python library and Model Context Protocol (MCP) server that provides an API client for connecting to local **Binner** inventory instances (.NET 8 / Kestrel) and the **Binner Swarm** cloud component service (`swarm.binner.io`).

---

## Architecture Overview

```
+-----------------------------------------------------------------------------------+
|                                 Client Application                                |
+-----------------------------------------------------------------------------------+
           |                                                       |
           v                                                       v
+---------------------------------------+       +-----------------------------------+
|      binner_mcp.api.BinnerAPIProxy    |       |   binner_mcp.swarmer.SwarmClient  |
|  (Local Binner Inventory Instance)    |       |    (Cloud Component Service)      |
+---------------------------------------+       +-----------------------------------+
           |                                                       |
           +---------------------------+---------------------------+
                                       |
                                       v
                     +-----------------------------------+
                     |   binner_mcp.common.BaseHttpClient|
                     |  (requests.Session, RLock, Hooks) |
                     +-----------------------------------+
                                       |
                   +-------------------+-------------------+
                   |                                       |
                   v                                       v
    +-----------------------------+         +-------------------------------+
    | Local Binner (.NET/Kestrel) |         | Binner Swarm (Cloud CDN / S3) |
    |  Default: 127.0.0.1:8090    |         |   https://swarm.binner.io     |
    +-----------------------------+         +-------------------------------+
```

---

## Module Index

| Module | Responsibility | Key Classes & Functions |
|---|---|---|
| `binner_mcp.config` | Configuration loader of the MCP app | `BinnerConfig`, `load_config`, `find_config_file` |
| `binner_mcp.api` | Programmatic Python API client and data models for Binner | `BinnerAPIProxy`, models, exceptions |
| `binner_mcp.api.client` | Main API client composed from domain components | `BinnerAPIProxy` |
| `binner_mcp.api.base` | Core authentication, session lifecycle, token refresh | `BaseBinnerClient` |
| `binner_mcp.api.parts` | Part inventory CRUD, filtering, pagination, printing | `PartsComp` |
| `binner_mcp.api.part_types` | Part category taxonomy endpoints | `PartTypesComp` |
| `binner_mcp.api.projects` | Maker projects and Bill of Materials (BOM) | `ProjectsComp` |
| `binner_mcp.api.data` | Batch CSV ingestion, ZIP backup/restore, bulk import | `DataComp` |
| `binner_mcp.api.cache` | In-memory bidirectional cache & identity resolution | `PartCacheComp` |
| `binner_mcp.api.system` | Ping, version extraction, server logs, Swarm test | `SystemComp` |
| `binner_mcp.api.models` | Pydantic data schemas for Binner HTTP payloads | `PartResponse`, `CreatePartRequest`, etc. |
| `binner_mcp.api.exceptions` | Binner API specific error hierarchy | `BinnerError`, `BinnerAuthError`, etc. |
| `binner_mcp.swarmer` | Programmatic Python API client and data models for Swarm | `SwarmClient`, models, exceptions |
| `binner_mcp.swarmer.client` | Binner Swarm cloud datasheet & pinout client | `SwarmClient` |
| `binner_mcp.swarmer.models` | Swarm Pydantic data schemas | `PartNumber`, `Pinout`, `Circuit`, etc. |
| `binner_mcp.swarmer.exceptions` | Swarm API error hierarchy & rate limit tracking | `SwarmError`, `SwarmRateLimitError`, etc. |
| `binner_mcp.mcp` | Model Context Protocol server protocol bindings | Server, tools, resources |
| `binner_mcp.common.http` | Base HTTP client with pooling, hooks, and locking | `BaseHttpClient` |
| `binner_mcp.common.logging` | Stdio transport safe stderr logging & TRACE level | `setup_logging`, `log_trace`, `sanitize_for_trace` |
| `binner_mcp.common.exceptions` | Common base exception hierarchy | `BaseProxyError`, `ProxyAPIError`, etc. |
| `binner_mcp.common.models` | Shared Pydantic base configuration | `CommonBaseModel` |

---

## Installation

Requires Python 3.10+:

```bash
# Standard installation
pip install -e .

# Installation with development & test tools
pip install -e ".[dev]"
```

Core dependencies:
* `requests>=2.31.0`: Connection-pooled HTTP session manager with cookie persistence.
* `pydantic>=2.0.0`: Schema validation and bidirectional snake_case / camelCase serialization.
* `pydantic-settings>=2.0.0`: Typed environment variable and settings resolution.
* `mcp>=1.0.0`: Model Context Protocol SDK.

---

## 30-Second Quick Start

```python
from binner_mcp.api.client import BinnerAPIProxy

# 1. Initialize proxy client (credentials optional if using default admin/admin)
client = BinnerAPIProxy(
    base_url="http://localhost:8090",
    username="admin",
    password="admin",
)

# 2. Check health and authenticate
if client.ping():
    client.login()
    print(f"Logged in as: {client.get_identity().name}")

# 3. Query low-stock components
low_stock = client.get_low_stock(results=10)
for part in low_stock.items:
    print(f"[{part.part_number}] Qty: {part.quantity} (Threshold: {part.low_stock_threshold})")

# 4. Increment stock
client.increment_quantity(part_number="NE555P", quantity=10)
```

## Documentation Contents

```{toctree}
:maxdepth: 2
:caption: User Guide & Technical Docs:

quickstart
api_reference
architecture
examples
```

* [Quickstart Guide](quickstart.md): Step-by-step tutorial covering configuration, CRUD, BOM, and cloud lookups.
* [API Reference](api_reference.md): Exhaustive method signatures, parameter tables, schemas, and status code mappings.
* [Architecture Guide](architecture.md): Technical deep-dive on dual-token refresh, thread locking, identity cache, and pagination chunking.
* [Code Examples](examples.md): Standalone, runnable Python recipes for common automation tasks.
