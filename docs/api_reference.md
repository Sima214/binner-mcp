# API Technical Reference

Exhaustive technical reference for all public classes, methods, request/response models, exceptions, and configuration schemas in `binner_mcp`.

---

## 1. `binner_mcp.api.client.BinnerAPIProxy`

The primary Python API client for local Binner instances. Composed of domain components:
`PartCacheComp`, `PartsComp`, `PartTypesComp`, `ProjectsComp`, `SystemComp`, `DataComp`, `BaseBinnerClient`.

### Constructor

```python
BinnerAPIProxy(
    base_url: str = "http://localhost:8090",
    username: str = "admin",
    password: str = "admin",
    timeout: float = 10.0,
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `base_url` | `str` | `"http://localhost:8090"` | Root URL of local Binner Kestrel server. Normalized without trailing slash. |
| `username` | `str` | `"admin"` | User account name for authentication. |
| `password` | `str` | `"admin"` | User account password for authentication. |
| `timeout` | `float` | `10.0` | Default HTTP request timeout in seconds. |

---

### Authentication & Session Lifecycle

#### `ping() -> bool`
* **Route:** `GET /api/ping` (Anonymous)
* **Description:** Verifies database connectivity. Returns `True` if HTTP status is 200 and response body is `"pong"`.
* **Exceptions:** Catches `requests.RequestException` and returns `False`.

#### `login() -> AuthenticatedTokens`
* **Route:** `POST /api/authentication/login`
* **Payload:** `AuthenticationRequest(username, password)`
* **Description:** Authenticates user. Attaches `Bearer <jwtToken>` to session headers and stores rotated refresh token in the cookie jar.
* **Returns:** `AuthenticatedTokens` instance.
* **Raises:** `BinnerAuthError` on invalid credentials (401/403) or missing token; `BinnerConnectionError` on network drops.

#### `logout() -> bool`
* **Route:** `POST /api/authentication/logout`
* **Description:** Invalidates backend session, clears `Authorization` header, and flushes session cookie jar. Always returns `True`.

#### `get_identity() -> UserContext`
* **Route:** `GET /api/authentication/identity`
* **Description:** Fetches claims for the currently authenticated identity.
* **Returns:** `UserContext` (`user_id`, `organization_id`, `name`, `email_address`, `phone_number`, `is_admin`).

#### `is_logged_in -> bool`
* **Property:** Returns `True` if proxy holds an active authenticated session.

---

### Inventory Dashboard & Queries

#### `get_summary() -> DashboardSummaryResponse`
* **Route:** `GET /api/part/summary`
* **Description:** Retrieves aggregate inventory statistics.
* **Returns:** `DashboardSummaryResponse` (`unique_parts_count`, `parts_count`, `parts_cost`, `low_stock_count`, `projects_count`, `currency`).

#### `list_parts(...) -> PaginatedResponse[PartResponse]`
* **Route:** `GET /api/part/list`
* **Parameters:**
  * `page` (`int`, default `1`): 1-indexed page number.
  * `results` (`Optional[int]`, default `20`): Page size limit. If `None` or `<= 0`, automatically fetches **all** items across all pages. If `> 1000`, chunks requests automatically in 1000-item pages.
  * `order_by` (`Optional[str]`): Column name to sort on (e.g. `"PartNumber"`, `"DateCreatedUtc"`, `"Quantity"`).
  * `direction` (`Union[str, int]`, default `"Descending"`): `"Ascending"`, `"Descending"`, `0`, or `1`.
  * `keyword` (`Optional[str]`): Substring query applied across all searchable fields.
  * `by` (`Optional[Union[str, List[str]]]`): Comma-separated or list of field names.
  * `value` (`Optional[Union[str, List[str], Any]]`): Comma-separated or list of values matching `by`.
  * `part_type` (`Optional[str]`): Filter by category name.
  * `part_type_id` (`Optional[int]`): Filter by category ID.
  * `bin_number` / `bin_number2` (`Optional[str]`): Primary/secondary bin storage label.
  * `location` (`Optional[str]`): Room / shelf / drawer name.
  * `manufacturer` (`Optional[str]`): Manufacturer name filter.
  * `package_type` (`Optional[str]`): Package / footprint filter (e.g. `"SOIC-8"`).
  * `filters` (`Optional[Dict[str, Any]]`): Additional snake_case or camelCase key-value filters.
* **Returns:** `PaginatedResponse[PartResponse]`.

#### `get_part_by_id(part_id: int) -> Optional[PartResponse]`
* **Route:** `GET /api/part/list?by=partId&value=<part_id>&results=1`
* **Description:** Retrieves single part by numeric ID. Caches resolved `part_id <-> part_number` mapping.

#### `get_part_number_by_id(part_id: int) -> Optional[str]`
* **Description:** Fast lookup of `partNumber` string for a numeric `partId`. Checks in-memory cache first, falls back to `get_part_by_id`.

#### `get_part_by_number(part_number: str) -> Optional[PartStoredFilesResponse]`
* **Route:** `GET /api/part?partNumber=<part_number>`
* **Description:** Retrieves detailed part representation including attached files (`stored_files`).
* **Returns:** `PartStoredFilesResponse` or `None` if not found.

#### `get_low_stock(...) -> PaginatedResponse[PartResponse]`
* **Route:** `GET /api/part/low`
* **Description:** Retrieves components where `quantity <= low_stock_threshold`. Supports the same filtering, sorting, and pagination parameters as `list_parts`.

#### `filter_parts(...) -> PaginatedResponse[PartResponse]`
* **Route:** `GET /api/part/filter`
* **Description:** Disjunctive (OR) multi-attribute search across parts inventory.
* **Parameters:** `part_names`, `values`, `part_types`, `keywords`, `manufacturers`, `mounting_types`, `locations`, `bin_numbers`, `bin_numbers2`, `order_by`, `direction`, `page`, `results`.

#### `search_parts(...) -> Union[Optional[PartResponse], List[PartResponse]]`
* **Route:** `GET /api/part/search`
* **Status:** `.. deprecated:: Upstream Binner v2.x`
* **Note:** Relevance ranking in upstream backend is non-functional (rank hardcoded to 0). Use `list_parts(keyword=...)` or `filter_parts(...)` instead.

---

### Component Lifecycle (CRUD)

#### `create_part(part: Union[CreatePartRequest, Dict[str, Any]]) -> PartResponse`
* **Route:** `POST /api/part`
* **Description:** Creates a new component. Automatically populates internal cache with returned ID and part number.

#### `update_part(part: Union[UpdatePartRequest, Dict[str, Any]]) -> PartResponse`
* **Route:** `PUT /api/part`
* **Description:** Replaces part fields and sets **absolute** on-hand quantity.

#### `delete_part(part_id: int) -> bool`
* **Route:** `DELETE /api/part`
* **Payload:** `{"partId": <part_id>}`
* **Description:** Deletes part by numeric ID and evicts it from the in-memory cache.

---

### Stock Quantity Adjustments

#### `update_quantity(part_id=None, part_number=None, quantity=1, reason=None) -> PartResponse`
* **Route:** `POST /api/part/quantity`
* **Description:** Adjusts stock by an **additive delta** (`Quantity += quantity`). Auto-resolves `part_id` and `part_number` to satisfy EF Core requirements.
* **Parameters:**
  * `quantity` (`int`): Positive or negative delta.
  * `reason` (`Optional[str]`): Optional audit log note.

#### `increment_quantity(part_id=None, part_number=None, quantity=1) -> PartResponse`
* **Route:** `POST /api/part/quantity/increment`
* **Description:** Adds positive `quantity` to current on-hand stock.

#### `decrement_quantity(part_id=None, part_number=None, quantity=1) -> PartResponse`
* **Route:** `POST /api/part/quantity/decrement`
* **Description:** Deducts positive `quantity` from current on-hand stock.

---

### Labels & Barcodes

#### `get_part_barcode(part_number: str) -> bytes`
* **Route:** `GET /api/part/barcode?partNumber=...&token=...`
* **Description:** Generates PNG barcode image using session `images_token`.

#### `print_part_label(...) -> bytes`
* **Route:** `POST /api/part/print`
* **Parameters:** `part_id`, `part_number` (mandatory), `printer_name`, `template_name`, `generate_image_only=True`.
* **Returns:** Binary image preview data.

#### `get_part_info(...) -> Dict[str, Any]`
* **Route:** `GET /api/part/info`
* **Description:** Aggregates part metadata, datasheets, circuits, and distributor pricing via backend integrations.

---

### Category Taxonomies

#### `get_part_types(parent: Optional[str] = None) -> List[PartTypeResponse]`
* **Route:** `GET /api/parttype/list?parent=...` (if parent specified) or `GET /api/parttype/all`

#### `create_part_type(part_type: Union[CreatePartTypeRequest, Dict[str, Any]]) -> PartTypeResponse`
* **Route:** `POST /api/parttype`

#### `update_part_type(part_type: Union[UpdatePartTypeRequest, Dict[str, Any]]) -> PartTypeResponse`
* **Route:** `PUT /api/parttype`

#### `delete_part_type(part_type_id: int) -> bool`
* **Route:** `DELETE /api/parttype` with payload `{"partTypeId": <part_type_id>}`

---

### Maker Projects & Bill of Materials (BOM)

#### `get_projects(page=1, results=20, order_by=None, direction="Ascending") -> List[ProjectResponse]`
* **Route:** `GET /api/project/list`
* **Note:** Automatically normalizes `order_by` into PascalCase to satisfy EF Core requirements.

#### `get_project(project_id=None, name=None) -> Optional[ProjectResponse]`
* **Route:** `GET /api/project?projectId=...` or `?name=...`

#### `create_project(project: Union[CreateProjectRequest, Dict[str, Any]]) -> ProjectResponse`
* **Route:** `POST /api/project`

#### `update_project(project: Union[UpdateProjectRequest, Dict[str, Any]]) -> ProjectResponse`
* **Route:** `PUT /api/project`

#### `delete_project(project_id: int) -> bool`
* **Route:** `DELETE /api/project` with payload `{"projectId": <project_id>}`

#### `get_bom(project_id=None, name=None) -> Dict[str, Any]`
* **Route:** `GET /api/bom?projectId=...` or `?name=...`

#### `get_bom_list(page=1, results=20) -> List[BomBasicResponse]`
* **Route:** `GET /api/bom/list`

#### `add_bom_part(req: Union[AddBomPartRequest, Dict[str, Any]]) -> Dict[str, Any]`
* **Route:** `POST /api/bom/part`

#### `update_bom_part(req: Union[UpdateBomPartRequest, Dict[str, Any]]) -> Dict[str, Any]`
* **Route:** `PUT /api/bom/part`

#### `delete_bom_part(ids: Union[int, List[int]], project_id=None, project_name=None) -> bool`
* **Route:** `DELETE /api/bom/part` with payload `{"ids": [...], "projectId": ..., "project": ...}`

---

### Data Ingestion & Backup Archives

#### `export_data(export_format="csv", populate_cache=True) -> BinnerExportArchive`
* **Route:** `GET /api/export?exportFormat=csv`
* **Description:** Downloads complete database archive as ZIP of CSV files. If `populate_cache=True`, parses `Parts.csv` and hydrates the in-memory cache.
* **Returns:** `BinnerExportArchive` with `.parts_csv`, `.part_types_csv`, `.projects_csv`, and `.save_to_disk(path)`.

#### `import_data_file(file_path_or_content, filename="Parts.csv") -> Dict[str, Any]`
* **Route:** `POST /api/data/import` (multipart/form-data)

#### `import_parts_csv(csv_content_or_path: Union[str, Path]) -> List[PartResponse]`
* **Description:** Client-side CSV batch parser. Sequentially invokes `create_part` and updates cache.

#### `bulk_import_parts(parts: List[Union[BulkImportItem, Dict[str, Any]]]) -> BulkImportResponse`
* **Route:** `POST /api/part/bulk`
* **Description:** Free batch ingestion endpoint. Resolves categories and hydrates cache with added/updated items.

---

### System Diagnostics

#### `get_system_version() -> Dict[str, Any]`
* **Route:** `GET /api/ping`
* **Description:** Extracts installed version from `X-Version` HTTP response header. (Does NOT query `/api/system/version` to avoid blocking outbound GitHub requests).

#### `get_system_info() -> Dict[str, Any]`
* **Route:** `GET /api/system/info` (Requires Admin rights).

#### `get_system_logs(source="binner", page=1, results=50) -> PaginatedResponse[SystemLogEntry]`
* **Route:** `GET /api/system/logs?by=...&page=...&results=...`
* **Valid sources:** `'binner'`, `'microsoft'`, `'missinglocalekeys'`, `'internal'`.

#### `test_swarm_integration(api_url="https://swarm.binner.io", enabled=True) -> TestApiResponse`
* **Route:** `PUT /api/settings/testapi`

---

## 2. `binner_mcp.swarmer.client.SwarmClient`

Cloud client for searching component schematics, pinout maps, and datasheets via `https://swarm.binner.io`.

### Constructor

```python
SwarmClient(
    base_url: str = "https://swarm.binner.io",
    api_key: Optional[str] = None,
    timeout: float = 30.0,
)
```

### Methods

#### `get_status() -> StatusResponse`
* **Route:** `GET /Status`
* **Returns:** `StatusResponse(is_up: bool, is_database_up: bool, last_checked_utc: Optional[str])`.

#### `search_parts(part_number, part_type=None, mounting_type=None, record_count=None) -> ServiceResult[SearchPartResponse]`
* **Route:** `POST /Part/search`
* **Description:** Retrieves component records with pinout diagrams, package geometry, and direct PDF datasheet URLs.

#### `get_part_info(...) -> ServiceResult[PartResults]`
* **Route:** `POST /Part/info`
* **Description:** Queries distributor pricing, parametric specs, and image assets.

#### Rate Limit Attributes
* `last_rate_limit: Optional[RateLimitInfo]`: Extracted from `x-rate-limit-limit`, `x-rate-limit-remaining`, and `x-rate-limit-reset` headers on every response.

---

## 3. Exception Hierarchy

```
BaseProxyError
├── ProxyConnectionError
│   └── ProxyTimeoutError
├── ProxyAPIError
│
├── BinnerError
│   ├── BinnerAuthError
│   ├── BinnerConnectionError (inherits ProxyConnectionError)
│   ├── BinnerNotFoundError
│   └── BinnerAPIError (inherits ProxyAPIError)
│
└── SwarmError
    ├── SwarmConnectionError (inherits ProxyConnectionError)
    ├── SwarmTimeoutError (inherits ProxyTimeoutError)
    ├── SwarmRateLimitError (HTTP 429 Too Many Requests)
    └── SwarmAPIError (inherits ProxyAPIError)
```

| Exception | Raised When | Attributes |
|---|---|---|
| `BinnerAuthError` | HTTP 401/403 or invalid login credentials | `message`, `details` |
| `BinnerConnectionError` | Kestrel backend unreachable or network connection drop | `message`, `details` |
| `BinnerNotFoundError` | HTTP 404 resource not found | `message`, `details` |
| `BinnerAPIError` | Unhandled HTTP 4xx or 5xx from Binner | `status_code`, `response_text`, `message` |
| `SwarmRateLimitError` | HTTP 429 response from Swarm cloud | `limit`, `remaining`, `reset`, `message` |
| `SwarmTimeoutError` | Swarm request exceeds timeout | `message`, `details` |

---

## 4. Configuration Reference (`BinnerConfig`)

| Field | CLI Flag | Env Variable | Default | Description |
|---|---|---|---|---|
| `base_url` | None | `BINNER_BASE_URL` | `http://localhost:8090` | Root URL of Binner instance |
| `username` | None | `BINNER_USERNAME` | `admin` | Authentication username |
| `password` | None | `BINNER_PASSWORD` | `admin` | Authentication password |
| `log_level` | `--log-level` | `BINNER_LOG_LEVEL` | `INFO` | Logging level (`TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `transport` | `--transport` | `BINNER_MCP_TRANSPORT` | `stdio` | MCP transport mode (`stdio` or `sse`) |
| `host` | `--host` | `BINNER_MCP_HOST` | `127.0.0.1` | SSE host bind address |
| `port` | `--port` | `BINNER_MCP_PORT` | `8000` | SSE listening port |
| config file | `--config` | `BINNER_MCP_CONFIG` | `./binnermcp_config.json` | Explicit path to JSON configuration |
