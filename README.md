# Binner MCP Server

## Overview

### System Architecture

### Key Capabilities

## Installation

### Prerequisites & Required Packages

* **Python:** Version 3.10 or higher.
* **Binner Instance:** A running local Binner server (default: `http://127.0.0.1:8090`).
* **Core Dependencies:**
  * **`mcp`** (>=1.0.0): Official Model Context Protocol SDK providing tool, resource, and transport implementations.
  * **`requests`** (>=2.31.0): HTTP client managing session connection pooling, cookie jars, and token refreshes.
  * **`pydantic` & `pydantic-settings`** (>=2.0.0): Data validation, model definitions, and typed configuration loading.

### Virtual Environment & Package Setup

Using an isolated virtual environment (`venv`) is strongly recommended to manage dependencies cleanly without modifying system packages:

```bash
# 1. Create a virtual environment
python3 -m venv .venv

# 2. Activate the virtual environment
# Linux / macOS:
source .venv/bin/activate
# Windows:
# .venv\Scripts\activate

# 3. Install the package and dependencies in editable mode
pip install -e .

# Or install with optional development tools:
pip install -e ".[dev]"
```

## Configuration

Configuration parameters are evaluated in the following order of precedence (highest to lowest):

### 1. Command-Line Arguments (Highest Precedence)

Explicit CLI flags override all environment variables and configuration files:
* `--config <path>`: Explicit path to a `binnermcp_config.json` file.
* `--log-level <level>`: Logging verbosity (`TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`).
* `--transport <mode>`: Protocol transport (`stdio` or `sse`).
* `--host <address>`: Host binding address for SSE transport (default: `127.0.0.1`).
* `--port <number>`: Listening port for SSE transport (default: `8000`).

### 2. Environment Variables

Environment variables override settings in configuration files:

| Variable | Description | Default |
|---|---|---|
| `BINNER_BASE_URL` | Base URL of the Binner backend instance | `http://localhost:8090` |
| `BINNER_USERNAME` | Username for Binner authentication | `admin` |
| `BINNER_PASSWORD` | Password for Binner authentication | `admin` |
| `BINNER_LOG_LEVEL` | Logging level (`TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `BINNER_MCP_TRANSPORT` | Protocol transport (`stdio` or `sse`) | `stdio` |
| `BINNER_MCP_HOST` | Host address for SSE transport (strictly localhost) | `127.0.0.1` |
| `BINNER_MCP_PORT` | Port for SSE transport | `8000` |
| `BINNER_MCP_CONFIG` | Path to a custom configuration JSON file | None |

### 3. Configuration File (`binnermcp_config.json`) (Lowest Precedence)

If no CLI flags or environment variables are provided, values are read from `binnermcp_config.json`. The server searches the following paths in order:
1. Path passed via `--config` or `BINNER_MCP_CONFIG`
2. Current working directory: `./binnermcp_config.json`
3. Script / project root directory
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
  "port": 8000
}
```

*(If no configuration is found, built-in defaults are used: `http://localhost:8090`, user `admin`, password `admin`, log level `INFO`, transport `stdio`).*

## MCP Server Usage

Supports stdio for local assistants and native SSE for local web clients. All logs route to `sys.stderr`.

```bash
# Run with default stdio transport
binner-mcp

# Run with native local SSE transport on port 8000
binner-mcp --transport sse --port 8000

# Run via Python module with custom options
python -m binner_mcp.main --config /path/to/binnermcp_config.json --log-level DEBUG
```

### Client Integration

#### 1. Stdio Clients (Gemini / Antigravity, Claude Desktop, Cursor, VS Code)

Launches the server directly as a local subprocess over `stdio`.

**Configuration (`mcpServers` block):**

```json
{
  "mcpServers": {
    "binner": {
      "command": "/path/to/binner_mcp/virtenv/bin/binner-mcp",
      "env": {
        "BINNER_BASE_URL": "http://127.0.0.1:8090",
        "BINNER_USERNAME": "admin",
        "BINNER_PASSWORD": "your-password"
      }
    }
  }
}
```

*If invoking via Python directly, set `"command": "/path/to/binner_mcp/virtenv/bin/python"` with `"args": ["-m", "binner_mcp.main"]`.*

**Configuration Paths:**
* **Gemini / Antigravity:** `~/.gemini/antigravity/mcp_config.json`
* **Claude Desktop:**
  * Linux: `~/.config/Claude/claude_desktop_config.json`
  * macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
  * Windows: `%APPDATA%\Claude\claude_desktop_config.json`
* **VS Code (Cline / Roo Code):** `cline_mcp_settings.json`
* **Cursor:** Under **Settings > Features > MCP**, click **+ Add New MCP Server** (`Name: binner`, `Type: command`, `Command: /path/to/binner_mcp/virtenv/bin/binner-mcp`).

---

#### 2. Local HTTP / SSE Clients (Local Web UIs)

> **Security Notice:** Binner MCP is a local private sidecar. **Never expose this server to external networks or the public internet.**

For local web-based interfaces that connect via HTTP/SSE instead of a subprocess, run the server natively in SSE mode bound **strictly to localhost (`127.0.0.1`)**:

```bash
binner-mcp --transport sse --host 127.0.0.1 --port 8000
```

* **Transport:** Server-Sent Events (SSE)
* **URL:** `http://127.0.0.1:8000/sse`

## MCP API Reference

### Tools

#### Inventory & Dashboard Queries

#### Component Management

#### Stock Adjustments

### Resources

#### Static State Resources

#### Dynamic Inventory Feeds

#### URI Templates

## Development

### Linting & Formatting

PEP 8 with 100-character line length:

```bash
# Format with Black
black --line-length 100 src/ tests/

```

## License

MIT License - see [LICENSE.txt](LICENSE.txt).
