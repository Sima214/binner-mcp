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
    ├── tools/               # Modular MCP tool implementations
    └── resources.py         # Registered MCP Resources (data streams)
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
  * **JWT Timestamp Granularity:** JWT `iat` (issued at) has 1-second Unix epoch granularity; consecutive refresh/login calls within the same second yield identical signatures.
  * **Part Lookup:** There is **no** `GET /api/part/{id}` endpoint. Part retrieval by number is `GET /api/part?partNumber=<pn>`. Multi-criteria search is `GET /api/part/search?keywords=...&exactMatch=...&shortId=...`.
  * **Part Creation:** `POST /api/part` requires `partNumber` (string). `location` is a `string` (room/shelf name), and `binNumber` / `binNumber2` are `string` labels (e.g. `"A1-04"`), **not** integer foreign keys.
  * **Part Deletion:** `DELETE /api/part` takes a JSON body `{"partId": <int>}`.
  * **Backend Field Requirement Omissions & Semantics:**
    * `POST /api/part/quantity`, `/increment`, and `/decrement` in `EntityFrameworkStorageProvider.cs` evaluate `.WhereIf(request.PartId > 0, x => x.PartNumber == request.PartNumber)`. Therefore, if `partId` is passed, `partNumber` **must** also be provided; otherwise Binner matches `x.PartNumber == null` and returns HTTP 404.
    * `POST /api/part/print` in `PartController.cs` requires `partNumber` (`if (string.IsNullOrEmpty(request.PartNumber)) return BadRequest(...)`), returning HTTP 400 even if a valid `partId` is provided.
    * `POST /api/part/quantity` applies an additive delta (`+=`), whereas `PUT /api/part` replaces absolute quantity.
  * **Identity Claims Mapping:** `GET /api/authentication/identity` maps ASP.NET claims to `name` and `emailAddress` (never `userName` or `fullName`).
  * **Polymorphic Schemas:** Fields such as `keywords` can arrive as a string or `ICollection<string>` (JSON array `[]`), requiring `Union[str, List[str]]` in Pydantic models.
  * **Health Check & Local Version Extraction:** `GET /api/ping` returns `"pong"` without requiring authentication and delivers the installed Binner version in the `X-Version` response header. **Never call `GET /api/system/version`** as it triggers blocking outbound GitHub API requests subject to rate-limits and timeouts.
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

### Rule 7: Tooling & Environment Discipline
* **Filesystem Operations:** Use native agent filesystem tools (`list_dir`, `view_file`, `find_by_name`, `grep_search`, `write_to_file`, `replace_file_content`) instead of shell utilities (`ls`, `cat`, `find`) to avoid permission prompts and failures.
* **Local Loopback Probing:** Use `curl` directly via `run_command` when probing local loopback (`127.0.0.1` / `localhost`) endpoints rather than browser/URL tools.
* **Workspace Isolation:** Never pollute root `/tmp` with ad-hoc test files. Use `/tmp/binner_mcp` or repository-scoped directories.
* **Source Code Writing:** Never pass `ArtifactMetadata` to `write_to_file` when modifying repository source files (metadata is strictly restricted to markdown artifacts in the artifact directory).

### Rule 8: Category Terminology Restrictions
* **Forbidden Terms:** Do not use the terms "breadcrumbs" or "taxonomies" in documentation, docstrings, variable names, function names, or tool descriptions.
* **Hierarchy Representation:** Delimiter-based hierarchies of part types (e.g. `Audio::Buzzer` with configurable delimiters) are fully supported and should be retained as-is.
* **Scope of Part Type IDs:** In `binner_mcp/api`, part type IDs must always be supported and prioritized when interacting with Binner backend endpoints. This rule is explicitly about `binner_mcp/api` behaviour and is not relevant to the MCP tool interface.

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
* **Test Execution Command:** Always run tests using the virtual environment: `virtenv/bin/python -m pytest tests/ -v`. Do not invoke bare `pytest`.

