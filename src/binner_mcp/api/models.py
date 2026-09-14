from pathlib import Path
from typing import Any, Dict, Generic, List, Optional, Union
from pydantic import Field
from binner_mcp.common.models import CommonBaseModel, T


class BinnerBaseModel(CommonBaseModel):
    """Base model configured to accept both snake_case and camelCase and ignore unknown fields."""
    pass



# === Authentication Models ===


class AuthenticationRequest(BinnerBaseModel):
    """Payload for POST /api/authentication/login."""

    username: str
    password: str
    token: Optional[str] = None


class AuthenticatedTokens(BinnerBaseModel):
    """Response from POST /api/authentication/login and /refresh-token."""

    id: Optional[int] = None
    organization_id: Optional[int] = Field(None, alias="organizationId")
    name: Optional[str] = None
    message: Optional[str] = None
    is_admin: bool = Field(False, alias="isAdmin")
    subscription_level: Optional[int] = Field(None, alias="subscriptionLevel")
    is_authenticated: bool = Field(False, alias="isAuthenticated")
    can_login: bool = Field(False, alias="canLogin")
    jwt_token: Optional[str] = Field(None, alias="jwtToken")
    images_token: Optional[str] = Field(None, alias="imagesToken")


class UserContext(BinnerBaseModel):
    """Current user identity from GET /api/authentication/identity."""

    user_id: Optional[int] = Field(None, alias="userId")
    organization_id: Optional[int] = Field(None, alias="organizationId")
    name: Optional[str] = None
    email_address: Optional[str] = Field(None, alias="emailAddress")
    phone_number: Optional[str] = Field(None, alias="phoneNumber")
    is_admin: bool = Field(False, alias="isAdmin")

    @property
    def user_name(self) -> Optional[str]:
        """Convenience alias for username/email or display name."""
        return self.email_address or self.name


# === Part Models ===


class StoredFile(BinnerBaseModel):
    """User-uploaded file attached to a part."""

    stored_file_id: Optional[int] = Field(None, alias="storedFileId")
    file_name: Optional[str] = Field(None, alias="fileName")
    content_type: Optional[str] = Field(None, alias="contentType")
    file_length: Optional[int] = Field(None, alias="fileLength")


class CreatePartRequest(BinnerBaseModel):
    """Payload for POST /api/part."""

    part_number: str = Field(..., alias="partNumber")
    quantity: int = 0
    low_stock_threshold: int = Field(0, alias="lowStockThreshold")
    cost: float = 0.0
    currency: Optional[str] = None
    project_id: Optional[int] = Field(None, alias="projectId")
    digi_key_part_number: Optional[str] = Field(None, alias="digiKeyPartNumber")
    mouser_part_number: Optional[str] = Field(None, alias="mouserPartNumber")
    arrow_part_number: Optional[str] = Field(None, alias="arrowPartNumber")
    tme_part_number: Optional[str] = Field(None, alias="tmePartNumber")
    element14_part_number: Optional[str] = Field(None, alias="element14PartNumber")
    description: Optional[str] = None
    product_url: Optional[str] = Field(None, alias="productUrl")
    lowest_cost_supplier: Optional[str] = Field(None, alias="lowestCostSupplier")
    lowest_cost_supplier_url: Optional[str] = Field(None, alias="lowestCostSupplierUrl")
    image_url: Optional[str] = Field(None, alias="imageUrl")
    package_type: Optional[str] = Field(None, alias="packageType")
    part_type_id: Optional[str] = Field(None, alias="partTypeId")
    mounting_type_id: Optional[str] = Field(None, alias="mountingTypeId")
    keywords: Optional[Union[str, List[str]]] = None
    datasheet_url: Optional[str] = Field(None, alias="datasheetUrl")
    location: Optional[str] = None
    bin_number: Optional[str] = Field(None, alias="binNumber")
    bin_number2: Optional[str] = Field(None, alias="binNumber2")
    manufacturer: Optional[str] = None
    manufacturer_part_number: Optional[str] = Field(None, alias="manufacturerPartNumber")
    barcode: Optional[str] = None
    symbol_name: Optional[str] = Field(None, alias="symbolName")
    footprint_name: Optional[str] = Field(None, alias="footprintName")
    value: Optional[str] = None
    short_id: Optional[str] = Field(None, alias="shortId")
    allow_potential_duplicate: bool = Field(False, alias="allowPotentialDuplicate")


class UpdatePartRequest(CreatePartRequest):
    """Payload for PUT /api/part."""

    part_id: int = Field(..., alias="partId")


class DeletePartRequest(BinnerBaseModel):
    """Payload for DELETE /api/part."""

    part_id: int = Field(..., alias="partId")


class PartQuantityRequest(BinnerBaseModel):
    """Payload for POST /api/part/quantity, /increment, /decrement."""

    part_id: Optional[int] = Field(None, alias="partId")
    part_number: Optional[str] = Field(None, alias="partNumber")
    quantity: int = 1
    reason: Optional[str] = None


class PartResponse(BinnerBaseModel):
    """Part representation returned from Binner API."""

    part_id: int = Field(..., alias="partId")
    short_id: Optional[str] = Field(None, alias="shortId")
    part_number: Optional[str] = Field(None, alias="partNumber")
    quantity: int = 0
    low_stock_threshold: int = Field(0, alias="lowStockThreshold")
    cost: float = 0.0
    currency: Optional[str] = None
    project_id: Optional[int] = Field(None, alias="projectId")
    digi_key_part_number: Optional[str] = Field(None, alias="digiKeyPartNumber")
    mouser_part_number: Optional[str] = Field(None, alias="mouserPartNumber")
    description: Optional[str] = None
    package_type: Optional[str] = Field(None, alias="packageType")
    product_url: Optional[str] = Field(None, alias="productUrl")
    lowest_cost_supplier: Optional[str] = Field(None, alias="lowestCostSupplier")
    lowest_cost_supplier_url: Optional[str] = Field(None, alias="lowestCostSupplierUrl")
    image_url: Optional[str] = Field(None, alias="imageUrl")
    part_type_id: Optional[int] = Field(None, alias="partTypeId")
    part_type: Optional[str] = Field(None, alias="partType")
    mounting_type_id: Optional[int] = Field(None, alias="mountingTypeId")
    mounting_type: Optional[str] = Field(None, alias="mountingType")
    keywords: Optional[Union[str, List[str]]] = None
    datasheet_url: Optional[str] = Field(None, alias="datasheetUrl")
    location: Optional[str] = None
    bin_number: Optional[str] = Field(None, alias="binNumber")
    bin_number2: Optional[str] = Field(None, alias="binNumber2")
    manufacturer: Optional[str] = None
    manufacturer_part_number: Optional[str] = Field(None, alias="manufacturerPartNumber")
    barcode: Optional[str] = None
    value: Optional[str] = None
    date_created_utc: Optional[str] = Field(None, alias="dateCreatedUtc")
    date_updated_utc: Optional[str] = Field(None, alias="dateUpdatedUtc")


class PartStoredFilesResponse(PartResponse):
    """Detailed part representation including attached files (from GET /api/part)."""

    stored_files: Optional[List[StoredFile]] = Field(default_factory=list, alias="storedFiles")


# === Dashboard & Pagination Models ===


class DashboardSummaryResponse(BinnerBaseModel):
    """Aggregate dashboard summary from GET /api/part/summary."""

    unique_parts_count: int = Field(..., alias="uniquePartsCount")
    parts_count: int = Field(..., alias="partsCount")
    parts_cost: float = Field(..., alias="partsCost")
    low_stock_count: int = Field(..., alias="lowStockCount")
    projects_count: int = Field(..., alias="projectsCount")
    currency: str = "USD"


class PaginatedResponse(BinnerBaseModel, Generic[T]):
    """Generic paginated response container."""

    total_items: int = Field(..., alias="totalItems")
    page_size: int = Field(..., alias="pageSize")
    total_pages: int = Field(..., alias="totalPages")
    page_number: int = Field(..., alias="pageNumber")
    items: List[T] = Field(default_factory=list)


# === Part Type & Category Models ===


class PartTypeResponse(BinnerBaseModel):
    """Part type / category representation."""

    part_type_id: int = Field(..., alias="partTypeId")
    name: str
    description: Optional[str] = None
    parent_part_type_id: Optional[int] = Field(None, alias="parentPartTypeId")
    parent_part_type: Optional[str] = Field(None, alias="parentPartType")
    parts: int = 0
    symbol_name: Optional[str] = Field(None, alias="symbolName")
    footprint_name: Optional[str] = Field(None, alias="footprintName")


class CreatePartTypeRequest(BinnerBaseModel):
    """Payload for POST /api/parttype."""

    name: str
    description: Optional[str] = None
    parent_part_type_id: Optional[int] = Field(None, alias="parentPartTypeId")
    symbol_name: Optional[str] = Field(None, alias="symbolName")
    footprint_name: Optional[str] = Field(None, alias="footprintName")


class UpdatePartTypeRequest(CreatePartTypeRequest):
    """Payload for PUT /api/parttype."""

    part_type_id: int = Field(..., alias="partTypeId")


# === Project & BOM Models ===


class ProjectResponse(BinnerBaseModel):
    """Project representation from GET /api/project or /api/project/list."""

    project_id: int = Field(..., alias="projectId")
    name: str
    description: Optional[str] = None
    archived: bool = False
    part_count: Optional[int] = Field(None, alias="partCount")
    pcb_count: Optional[int] = Field(None, alias="pcbCount")


class CreateProjectRequest(BinnerBaseModel):
    """Payload for POST /api/project."""

    name: str
    description: Optional[str] = None
    archived: bool = False


class UpdateProjectRequest(CreateProjectRequest):
    """Payload for PUT /api/project."""

    project_id: int = Field(..., alias="projectId")


class BomBasicResponse(BinnerBaseModel):
    """BOM project summary from GET /api/bom/list."""

    project_id: int = Field(..., alias="projectId")
    name: str
    description: Optional[str] = None
    part_count: int = Field(0, alias="partCount")
    pcb_count: int = Field(0, alias="pcbCount")


class AddBomPartRequest(BinnerBaseModel):
    """Payload for POST /api/bom/part."""

    part_number: str = Field(..., alias="partNumber")
    project_id: Optional[int] = Field(None, alias="projectId")
    project: Optional[str] = None
    pcb_id: Optional[int] = Field(None, alias="pcbId")
    cost: float = 0.0
    currency: Optional[str] = None
    quantity: int = 1
    quantity_available: int = Field(0, alias="quantityAvailable")
    notes: Optional[str] = None
    reference_id: Optional[str] = Field(None, alias="referenceId")
    schematic_reference_id: Optional[str] = Field(None, alias="schematicReferenceId")
    custom_description: Optional[str] = Field(None, alias="customDescription")


class UpdateBomPartRequest(BinnerBaseModel):
    """Payload for PUT /api/bom/part."""

    project_part_assignment_id: int = Field(..., alias="projectPartAssignmentId")
    project_id: int = Field(..., alias="projectId")
    part_id: Optional[int] = Field(None, alias="partId")
    pcb_id: Optional[int] = Field(None, alias="pcbId")
    part_name: Optional[str] = Field(None, alias="partName")
    cost: float = 0.0
    currency: Optional[str] = None
    quantity: int = 1
    quantity_available: int = Field(0, alias="quantityAvailable")
    notes: Optional[str] = None
    reference_id: Optional[str] = Field(None, alias="referenceId")
    schematic_reference_id: Optional[str] = Field(None, alias="schematicReferenceId")
    custom_description: Optional[str] = Field(None, alias="customDescription")


class RemoveBomPartRequest(BinnerBaseModel):
    """Payload for DELETE /api/bom/part."""

    project_id: Optional[int] = Field(None, alias="projectId")
    project: Optional[str] = None
    ids: List[int] = Field(default_factory=list)


# === Bulk Import Models ===


class BulkImportItem(BinnerBaseModel):
    """Single part item for bulk ingestion via POST /api/part/bulk."""

    part_number: str = Field(..., alias="partNumber")
    quantity: int = 0
    description: Optional[str] = None
    location: Optional[str] = None
    bin_number: Optional[str] = Field(None, alias="binNumber")
    bin_number2: Optional[str] = Field(None, alias="binNumber2")
    part_type: Optional[str] = Field(None, alias="partType")
    part_type_id: Optional[int] = Field(None, alias="partTypeId")
    cost: float = 0.0
    manufacturer: Optional[str] = None
    manufacturer_part_number: Optional[str] = Field(None, alias="manufacturerPartNumber")
    supplier_part_number: Optional[str] = Field(None, alias="supplierPartNumber")
    barcode: Optional[str] = None
    package_type: Optional[str] = Field(None, alias="packageType")
    keywords: Optional[Union[str, List[str]]] = None


class BulkImportRequest(BinnerBaseModel):
    """Payload for POST /api/part/bulk."""

    parts: List[BulkImportItem] = Field(default_factory=list)


class BulkImportResponse(BinnerBaseModel):
    """Response from POST /api/part/bulk."""

    added: List[PartResponse] = Field(default_factory=list)
    updated: List[PartResponse] = Field(default_factory=list)


# === System Logs & Integration Testing Models ===


class SystemLogEntry(BinnerBaseModel):
    """Log entry returned by GET /api/system/logs."""

    log_entry: str = Field(..., alias="logEntry")


class ApiConfigValue(BinnerBaseModel):
    """Key-value setting for integration configuration."""

    key: str
    value: Optional[str] = None


class TestApiRequest(BinnerBaseModel):
    """Payload for PUT /api/settings/testapi."""

    __test__ = False

    name: str
    configuration: List[ApiConfigValue] = Field(default_factory=list)


class TestApiResponse(BinnerBaseModel):
    """Response from PUT /api/settings/testapi."""

    __test__ = False

    api_name: str = Field(..., alias="apiName")
    success: bool = False
    message: Optional[str] = None
    authorization_url: Optional[str] = Field(None, alias="authorizationUrl")


# === Export & Import Models ===


class BinnerExportArchive(BinnerBaseModel):
    """
    Representation of Binner's export archive (ZIP containing CSVs).
    Mirrors the archive's internal filesystem structure.
    """

    files: Dict[str, str] = Field(
        default_factory=dict,
        description="Filename to CSV file content mapping mirroring the ZIP structure",
    )

    @property
    def parts_csv(self) -> Optional[str]:
        """Access Parts.csv content if present in archive."""
        return self.files.get("Parts.csv")

    @property
    def part_types_csv(self) -> Optional[str]:
        """Access PartTypes.csv content if present in archive."""
        return self.files.get("PartTypes.csv")

    @property
    def projects_csv(self) -> Optional[str]:
        """Access Projects.csv content if present in archive."""
        return self.files.get("Projects.csv")

    def save_to_disk(self, destination_dir: Union[str, Path]) -> List[Path]:
        """Extract and save all archive CSV files to a destination directory."""
        dest = Path(destination_dir)
        dest.mkdir(parents=True, exist_ok=True)
        saved: List[Path] = []
        for name, content in self.files.items():
            target = dest / name
            target.write_text(content, encoding="utf-8")
            saved.append(target)
        return saved
