# Agent Guidelines: Binner MCP Server (`binner-mcp`)

This document provides guidelines, constraints, and architecture instructions for AI coding assistants working in this repository.

---

## 1. Project Overview & Architecture

`binner-mcp` is a Python-based **Model Context Protocol (MCP)** server providing an intelligent proxy to local **Binner** inventory instances (.NET 8 / Kestrel).

The codebase adheres to a clean, decoupled dual-layered architecture nested inside `src/`:

```
src/binner_mcp/
├── __init__.py
├── main.py                  # CLI entrypoint & stderr logging setup
├── config.py                # Single-config loader (binnermcp_config.json + env overrides)
├── api/                     # Layer 1: MCP-Agnostic REST Proxy Client
│   ├── __init__.py
│   ├── client.py            # BinnerAPIProxy (requests session, token refresh, CRUD)
│   └── models.py            # Pydantic models for Binner requests & responses
└── mcp/                     # Layer 2: Protocol Binding Layer
    ├── __init__.py
    ├── server.py            # MCP server setup & lifecycle
    ├── tools.py             # Registered MCP Tools (actions)
    ├── resources.py         # Registered MCP Resources (data streams)
    └── prompts.py           # Curated prompt templates
```

* **`reference/` Directory:** Contains reference documentation and upstream Binner C# source code (`Binner.Web`, `Binner-Backend`). **Treat `reference/` as read-only**. Do not edit reference files unless explicitly instructed to update the design doc.
* **`virtenv/` Directory:** Local virtual environment (ignored by Git).

---

## 2. Inviolable Operational Rules

### Rule 1: Stdio Transport Safety & Lean Logging Policy
* **Never write logs, print statements, or diagnostics to `sys.stdout`**. All logging must strictly target `sys.stderr` to prevent JSON-RPC transport stream corruption.
* **Never print credentials, tokens, or masked asterisks (`password="******"`)** in log messages.
* **Logging Level Disciplines**:
  * **`INFO`**: High-level application lifecycle events only (server startup, shutdown, successful backend connection, MCP client ready).
  * **`DEBUG`**: Internal state transitions, configuration file resolution path, and **every time an access token is refreshed**.
  * **`WARNING`**: Ignored, missing, or unmapped fields and non-critical fallbacks (e.g., defaulting to part type `Other`).
  * **`ERROR`**: Unexpected API responses, HTTP 4xx/5xx errors, unrecoverable connection drops, or failed authentication.
  * **`TRACE` (level 5)**: Verbose execution logging every raw API call, including HTTP method, URL, and payloads.

### Rule 2: Ground Truth API Verification (No Hallucinations)
* Binner is an ASP.NET Core application. **Never invent endpoints or parameters**. Always reference [reference/binner-mcp-design-doc.md](reference/binner-mcp-design-doc.md) and [`reference/Binner.Web/Controllers/`](reference/Binner.Web/Controllers/).
* **Key verified facts**:
  * **Token Refresh:** Endpoint is `POST /api/authentication/refresh-token` (NOT `/api/authentication/refresh`). The server expects `Request.Cookies["refreshToken"]` and delivers the rotated token in `Set-Cookie`.
  * **Part Lookup:** There is **no** `GET /api/part/{id}` endpoint. Part retrieval by number is `GET /api/part?partNumber=<pn>`. Multi-criteria search is `GET /api/part/search?keywords=...&exactMatch=...&shortId=...`.
  * **Part Creation:** `POST /api/part` requires `partNumber` (string). `location` is a `string` (room/shelf name), and `binNumber` / `binNumber2` are `string` labels (e.g. `"A1-04"`), **not** integer foreign keys.
  * **Part Deletion:** `DELETE /api/part` takes a JSON body `{"partId": <int>}`.
  * **Health Check:** `GET /api/ping` returns `"pong"` without requiring authentication.
  * **Hardware Reality:** There are **no** WLED smart-bin locator endpoints in Binner. Hardware capabilities center around label printers (`/api/print`) and barcode generators (`/api/part/barcode`).

### Rule 3: Single Hardcoded Configuration File
* Only one configuration filename is recognized: **`binnermcp_config.json`**. Do not create or look for alternative names like `binner_private_config.json`.
* Search order:
  1. Explicit `--config` CLI argument
  2. `BINNER_MCP_CONFIG` environment variable
  3. Current working directory (`./binnermcp_config.json`)
  4. Script / project directory
  5. User config path (`~/.config/binnermcp/binnermcp_config.json`)
  6. System-wide path (`/etc/binnermcp/binnermcp_config.json`)
* Environment variables (`BINNER_BASE_URL`, `BINNER_USERNAME`, `BINNER_PASSWORD`, `BINNER_LOG_LEVEL`) override configuration file values.

### Rule 4: No Silent Errors (No Catch-All Try/Except)
* **Never write bare `except:`, `except Exception: pass`, or broad catch-alls that suppress failures**.
* Always catch specific, expected exception types (`requests.RequestException`, `json.JSONDecodeError`, `KeyError`, `ValueError`, `FileNotFoundError`).
* **Fail fast**: If a configuration file is missing when explicitly requested, or contains malformed JSON, raise an explicit error immediately rather than silently falling back to defaults.
* Re-raise or wrap lower-level exceptions using chained exceptions (`raise SpecificError(...) from err`) preserving original root cause and traceback.

### Rule 5: Lean Documentation Policy (Zero Wasted Human Reading Time)
* **Zero fluff, zero filler, zero conversational preamble**.
* State technical facts, commands, configuration parameters, and code blocks directly.
* Favor high-density, structured representations (tables, bulleted lists, concrete JSON snippets) over verbose narrative paragraphs.
* Every sentence must provide actionable, non-redundant technical value.

### Rule 6: Git Commit Restrictions
* **Do not execute `git commit`** unless explicitly requested by the user. You are authorized to stage files or check status, but commit creation is reserved for user review.

---

## 3. Technology Stack & Coding Standards

* **Python Version:** 3.10+
* **Build System:** Standard `setuptools` with `setuptools.build_meta` via `pyproject.toml` (avoid bleeding-edge build systems).
* **HTTP Client:** `requests.Session` with cookie-jar persistence and connection pooling.
* **Typing & Validation:** Strict type annotations with `typing` and Pydantic v2.
* **Code Formatter:** Black formatting style (100 characters line length).

---

## 4. Testing & Verification

* A live Binner server instance is typically active on `http://127.0.0.1:8090`.
* Test database connectivity before full operations using `GET /api/ping`.
* Place automated tests in `tests/` using `pytest` and `pytest-asyncio`.
