# System Architecture & Technical Design

This document details the internal design patterns, concurrency controls, token lifecycle, and backend idiosyncrasies implemented in `binner_mcp`.

---

## 1. Dual-Layered System Architecture

`binner_mcp` isolates protocol transport logic from domain API client execution:

```
+-------------------------------------------------------------------------------+
|                       Layer 2: MCP Protocol Binding Layer                     |
|                                                                               |
|  - MCP Server Setup (stdio / sse)                                             |
|  - Registered Tools (Inventory queries, part updates, BOM assignments)        |
|  - Registered Resources (Inventory snapshots, part detail streams)            |
|  - Curated Prompts (Inventory audit, procurement templates)                   |
+-------------------------------------------------------------------------------+
                                      |
                                      v
+-------------------------------------------------------------------------------+
|                      Layer 1: MCP-Agnostic API Client Core                    |
|                                                                               |
|  - BinnerAPIProxy (Requests Session, connection pooling, cookie jar)          |
|  - SwarmClient (Cloud datasheet and pinout resolution)                        |
|  - Domain Components (Parts, Projects, Taxonomy, System, Data, Cache)         |
|  - In-Memory Part Identity Cache (_part_id_to_number, _part_number_to_id)     |
|  - Pydantic v2 Models (Dual snake_case & camelCase serialization)             |
+-------------------------------------------------------------------------------+
                                      |
                                      v
+-------------------------------------------------------------------------------+
|                         Upstream Backend Services                             |
|                                                                               |
|  - Local Binner .NET 8 / Kestrel Instance (127.0.0.1:8090)                    |
|  - Binner Swarm Cloud Services (https://swarm.binner.io)                      |
+-------------------------------------------------------------------------------+
```

---

## 2. Dual-Token Authentication Lifecycle

Binner uses a dual-token authentication mechanism implemented in ASP.NET Core:
1. **Access Token (JWT):** Short-lived token returned in the login JSON response under `"jwtToken"`. Sent as `Authorization: Bearer <token>` on all requests.
2. **Refresh Token:** Long-lived token delivered **strictly** in the `Set-Cookie` header (`refreshToken=...; HttpOnly; SameSite=Strict`). The JSON payload omits this value (`[JsonIgnore]`).
3. **Refresh Route:** The verified backend route is `POST /api/authentication/refresh-token` (NOT `/api/authentication/refresh`). The server reads `Request.Cookies["refreshToken"]` directly.

### Transparent Recovery Sequence

```
Client Proxy                    Local Binner Backend
     |                                    |
     | 1. GET /api/part/list              |
     |    Header: Bearer <expired-jwt>    |
     |----------------------------------->|
     | 2. HTTP 401 Unauthorized           |
     |<-----------------------------------|
     |                                    |
     | 3. POST /api/authentication/refresh-token
     |    Cookie: refreshToken=<token>    |
     |----------------------------------->|
     | 4. HTTP 200 OK                     |
     |    Set-Cookie: refreshToken=<new>  |
     |    JSON: {"jwtToken": "<new-jwt>"} |
     |<-----------------------------------|
     |                                    |
     | 5. Retry original GET /api/part/list
     |    Header: Bearer <new-jwt>        |
     |----------------------------------->|
     | 6. HTTP 200 OK (Paginated parts)   |
     |<-----------------------------------|
```

* **Fallback Strategy:** If the refresh cookie is missing or the refresh endpoint fails (e.g. expired refresh token), the proxy automatically falls back to an explicit login sequence using the stored username and password.
* **1-Second JWT Granularity:** ASP.NET Core JWT `iat` (issued-at) claims use 1-second Unix epoch granularity. Consecutive refresh or login calls within the same second yield identical signatures.

---

## 3. Concurrency & Re-entrant Locking

All HTTP interactions in `BaseHttpClient` and `BaseBinnerClient` are serialized using a re-entrant lock (`threading.RLock`).

### Design Rationale
* **Token Refresh Race Condition Prevention:** When multiple background threads or concurrent tool executions trigger HTTP 401 simultaneously, the `RLock` ensures only one thread executes token rotation while others wait and reuse the newly acquired token.
* **Cookie Jar Thread Safety:** `requests.Session.cookies` is not thread-safe under rapid concurrent modifications. Serializing requests through `with self._lock:` guarantees session cookie jar integrity.
* **Multi-Page Chunking Atomicity:** In methods like `list_parts(results=5000)` or `get_projects(results=None)`, chunked multi-page requests execute under a single lock context to avoid interleaving cache mutations.

---

## 4. In-Memory Part Identity Resolution (`PartCacheComp`)

### The Backend Omission Pitfall

In upstream Binner C# source code (`EntityFrameworkStorageProvider.cs`):

```csharp
.WhereIf(request.PartId > 0, x => x.PartId == request.PartId)
.WhereIf(request.PartId > 0, x => x.PartNumber == request.PartNumber)
```

Because of this second `.WhereIf`, if a client passes `partId: 42` but omits `partNumber`, the query evaluates `x.PartNumber == null`. In SQL, this matches nothing, causing Binner to return **HTTP 404 NotFound** even if `partId: 42` exists.

Furthermore, `POST /api/part/print` in `PartController.cs` explicitly verifies:
```csharp
if (string.IsNullOrEmpty(request.PartNumber)) return BadRequest(...);
```
returning **HTTP 400 BadRequest** if `partNumber` is omitted, even when a valid `partId` is supplied.

### 3-Tier Resolution Algorithm

To prevent failures, `PartCacheComp._resolve_part_identity` automatically reconciles IDs and part numbers:

```
[ Input: part_id, part_number ]
              |
    Both present? ---> Yes ---> Cache mapping & Return (part_id, part_number)
              | No
              v
    Cache Hit in _part_id_to_number or _part_number_to_id? ---> Yes ---> Return resolved pair
              | No
              v
    part_number provided, part_id missing?
              | Yes
              v
    Call get_part_by_number(pn) -> Populate cache -> Return (part_id, part_number)
              | No
              v
    part_id provided, part_number missing?
              | Yes
              v
    Call get_part_number_by_id(pid) (queries list_parts?by=partId&value=pid)
              |
              v
    Populate cache & Return (part_id, resolved_part_number)
```

The cache is automatically updated during `create_part`, `update_part`, `list_parts`, `filter_parts`, `bulk_import_parts`, and `export_data`. When `delete_part` is called, the part is evicted from both dictionaries.

---

## 5. Pagination & Large Result Chunking Strategy

Binner's backend controller limits single-page queries to 1000 items (`Math.Min(results, 1000)`). Passing values above 1000 is silently clamped by the server.

`binner_mcp` handles pagination transparently across three tiers:

| Query Limit (`results`) | Execution Pattern | Description |
|---|---|---|
| `1 <= results <= 1000` | **Single Request** | Standard single HTTP request to `/api/part/list`. |
| `results > 1000` | **Chunked Loop** | Requests up to 1000 items per chunk in a loop until `results` limit or `totalPages` is satisfied. Merges items into a single `PaginatedResponse`. |
| `results is None` or `<= 0` | **Full Inventory Stream** | Automatically loops through all available pages in 1000-item chunks until `curr_page >= total_pages` or an empty page is returned. |

### PascalCase Sorting Guard

EF Core dynamic sorting in Binner expects PascalCase property names (e.g. `OrderBy("PartNumber")`). Passing camelCase or snake_case can raise `System.InvalidOperationException`. In `ProjectsComp.get_projects`, `order_by` parameters (e.g. `"project_id"`) are automatically converted to PascalCase (`"ProjectId"`).

---

## 6. Stdio Transport Safety & Lean Logging Policy

### Stdio Isolation
When running as an MCP server over `stdio`, `sys.stdout` carries JSON-RPC protocol frames. **Any write to `sys.stdout` will corrupt the transport stream and disconnect the client.**

* All logging in `binner_mcp` targets `sys.stderr` exclusively via `StreamHandler(stream=sys.stderr)`.
* Print statements are strictly prohibited across all library and server modules.

### Custom TRACE Level (Level 5)
A custom `TRACE` logging level is registered at numeric value `5` (below `DEBUG: 10`).

| Level | Severity | Application Event |
|---|---|---|
| `TRACE` | 5 | Every raw HTTP request, URL, method, and sanitized payload. |
| `DEBUG` | 10 | Cache resolution hits/misses, config file discovery, token refresh events. |
| `INFO` | 20 | Server startup/shutdown, successful backend connection, ready state. |
| `WARNING` | 30 | Fallbacks, missing optional fields, 401 token retry notices. |
| `ERROR` | 40 | Unhandled HTTP 4xx/5xx, connection dropouts, auth failures. |

### Sensitive Data Masking
`binner_mcp.common.logging.sanitize_for_trace` recursively traverses request/response payloads before logging at `TRACE` level, replacing values for keys matching `password`, `token`, `authorization`, `secret`, or `apikey` with `"[REDACTED]"`.
