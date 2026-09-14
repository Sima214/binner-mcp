"""Pydantic models for Binner Swarm API requests and responses."""

from typing import Any, Generic, List, Optional
from pydantic import Field
from binner_mcp.common.models import CommonBaseModel, T


class SwarmBaseModel(CommonBaseModel):
    """Base model configured to accept both snake_case and camelCase and ignore unknown fields."""
    pass



# === Rate Limiting & Diagnostics ===


class RateLimitInfo(SwarmBaseModel):
    """Extracted rate-limit details from Swarm HTTP response headers."""

    limit: Optional[str] = None
    remaining: Optional[int] = None
    reset: Optional[str] = None


class StatusResponse(SwarmBaseModel):
    """Payload returned by GET /Status."""

    is_up: bool = Field(False, alias="isUp")
    is_database_up: bool = Field(False, alias="isDatabaseUp")
    last_checked_utc: Optional[str] = Field(None, alias="lastCheckedUtc")


# === Request Models ===


class SearchPartRequest(SwarmBaseModel):
    """Request body for POST /Part/search and POST /Part/info."""

    part_number: str = Field(..., alias="partNumber")
    part_type: Optional[str] = Field(None, alias="partType")
    mounting_type: Optional[str] = Field(None, alias="mountingType")
    record_count: Optional[int] = Field(None, alias="recordCount")


# === Common Media & Assets ===


class SwarmImage(SwarmBaseModel):
    """Represents an image asset stored on CloudFront / S3."""

    image_id: Optional[int] = Field(None, alias="imageId")
    resource_id: Optional[str] = Field(None, alias="resourceId")
    image_type: Optional[int] = Field(None, alias="imageType")
    image_size: Optional[int] = Field(None, alias="imageSize")
    width: Optional[int] = None
    height: Optional[int] = None
    dpi_x: Optional[float] = Field(None, alias="dpiX")
    dpi_y: Optional[float] = Field(None, alias="dpiY")
    crc32: Optional[int] = None
    extension: Optional[str] = None
    resource_source_url: Optional[str] = Field(None, alias="resourceSourceUrl")
    resource_path: Optional[str] = Field(None, alias="resourcePath")
    original_url: Optional[str] = Field(None, alias="originalUrl")
    global_id: Optional[str] = Field(None, alias="globalId")

    @property
    def url(self) -> Optional[str]:
        """Reconstruct full CDN URL if source and path exist."""
        if self.resource_source_url and self.resource_path and self.image_id is not None:
            ext = self.extension or ".png"
            return f"https://{self.resource_source_url}/{self.resource_path}_{self.image_id}{ext}"
        return self.original_url


class CircuitPartAssignment(SwarmBaseModel):
    """Component assigned to a circuit diagram position."""

    circuit_part_assignment_id: Optional[int] = Field(None, alias="circuitPartAssignmentId")
    part_name: Optional[str] = Field(None, alias="partName")
    part_type: Optional[str] = Field(None, alias="partType")
    reference: Optional[str] = None
    description: Optional[str] = None
    role: Optional[str] = None
    color: Optional[str] = None
    is_ai_generated: bool = Field(False, alias="isAiGenerated")
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    part_number: Optional[Any] = Field(None, alias="partNumber")
    part_number_manufacturer: Optional[Any] = Field(None, alias="partNumberManufacturer")


class Circuit(SwarmBaseModel):
    """Circuit schematic or application diagram."""

    circuit_id: Optional[int] = Field(None, alias="circuitId")
    name: Optional[str] = None
    description: Optional[str] = None
    date_created_utc: Optional[str] = Field(None, alias="dateCreatedUtc")
    global_id: Optional[str] = Field(None, alias="globalId")
    output_image: Optional[SwarmImage] = Field(None, alias="outputImage")
    print_image: Optional[SwarmImage] = Field(None, alias="printImage")
    parts: List[CircuitPartAssignment] = Field(default_factory=list)


class Pinout(SwarmBaseModel):
    """Component pinout map and pin definition."""

    pinout_id: Optional[int] = Field(None, alias="pinoutId")
    part_name: Optional[str] = Field(None, alias="partName")
    package_name: Optional[str] = Field(None, alias="packageName")
    package_id: Optional[int] = Field(None, alias="packageId")
    has_pin1_indicator: bool = Field(False, alias="hasPin1Indicator")
    pinout_definition: Optional[str] = Field(None, alias="pinoutDefinition")
    pin_count: Optional[int] = Field(None, alias="pinCount")
    is_transitive: bool = Field(False, alias="isTransitive")
    date_created_utc: Optional[str] = Field(None, alias="dateCreatedUtc")
    global_id: Optional[str] = Field(None, alias="globalId")
    manufacturer_name: Optional[str] = Field(None, alias="manufacturerName")
    manufacturer_part_name: Optional[str] = Field(None, alias="manufacturerPartName")
    export_image: Optional[SwarmImage] = Field(None, alias="exportImage")


class DatasheetBasic(SwarmBaseModel):
    """Datasheet document metadata."""

    datasheet_id: Optional[int] = Field(None, alias="datasheetId")
    title: Optional[str] = None
    short_description: Optional[str] = Field(None, alias="shortDescription")
    manufacturer_name: Optional[str] = Field(None, alias="manufacturerName")
    original_url: Optional[str] = Field(None, alias="originalUrl")
    product_url: Optional[str] = Field(None, alias="productUrl")
    resource_id: Optional[str] = Field(None, alias="resourceId")
    resource_path: Optional[str] = Field(None, alias="resourcePath")
    resource_source_url: Optional[str] = Field(None, alias="resourceSourceUrl")
    page_count: Optional[int] = Field(None, alias="pageCount")
    image_count: Optional[int] = Field(None, alias="imageCount")

    @property
    def direct_pdf_url(self) -> Optional[str]:
        """Construct direct CloudFront PDF download URL."""
        if self.resource_source_url and self.resource_path:
            return f"https://{self.resource_source_url}/{self.resource_path}.pdf"
        return self.original_url


class PartNumberManufacturerSupplier(SwarmBaseModel):
    """Distributor inventory and pricing details."""

    supplier_id: Optional[int] = Field(None, alias="supplierId")
    supplier_name: Optional[str] = Field(None, alias="supplierName")
    supplier_part_number: Optional[str] = Field(None, alias="supplierPartNumber")
    cost: Optional[float] = None
    currency: Optional[str] = None
    product_url: Optional[str] = Field(None, alias="productUrl")
    quantity_available: Optional[int] = Field(None, alias="quantityAvailable")
    minimum_order_quantity: Optional[int] = Field(None, alias="minimumOrderQuantity")
    factory_stock_available: Optional[int] = Field(None, alias="factoryStockAvailable")
    factory_lead_time: Optional[str] = Field(None, alias="factoryLeadTime")


class PartNumberManufacturerParametric(SwarmBaseModel):
    """Parametric electrical specifications."""

    part_number_manufacturer_parametric_id: Optional[int] = Field(
        None, alias="partNumberManufacturerParametricId"
    )
    name: Optional[str] = None
    value: Optional[str] = None
    value_number: Optional[float] = Field(None, alias="valueNumber")
    units: Optional[int] = None


class PartNumberManufacturerPackage(SwarmBaseModel):
    """Package dimensions and geometry."""

    package_id: Optional[int] = Field(None, alias="packageId")
    name: Optional[str] = None
    pin_count: Optional[int] = Field(None, alias="pinCount")
    size_width_mm: Optional[float] = Field(None, alias="sizeWidthMm")
    size_height_mm: Optional[float] = Field(None, alias="sizeHeightMm")
    size_depth_mm: Optional[float] = Field(None, alias="sizeDepthMm")


class PartNumberManufacturer(SwarmBaseModel):
    """Manufacturer specific part information."""

    part_number_manufacturer_id: Optional[int] = Field(None, alias="partNumberManufacturerId")
    name: Optional[str] = None
    manufacturer_name: Optional[str] = Field(None, alias="manufacturerName")
    description: Optional[str] = None
    is_obsolete: bool = Field(False, alias="isObsolete")
    package: List[PartNumberManufacturerPackage] = Field(default_factory=list)
    datasheets: List[DatasheetBasic] = Field(default_factory=list)
    suppliers: List[PartNumberManufacturerSupplier] = Field(default_factory=list)
    parametrics: List[PartNumberManufacturerParametric] = Field(default_factory=list)
    pinouts: List[Pinout] = Field(default_factory=list)
    circuits: List[Circuit] = Field(default_factory=list)


class PartNumber(SwarmBaseModel):
    """Top-level electronic component record."""

    part_number_id: Optional[int] = Field(None, alias="partNumberId")
    name: Optional[str] = None
    description: Optional[str] = None
    part_type: Optional[str] = Field(None, alias="partType")
    circuits: List[Circuit] = Field(default_factory=list)
    pinouts: List[Pinout] = Field(default_factory=list)
    part_number_manufacturers: List[PartNumberManufacturer] = Field(
        default_factory=list, alias="partNumberManufacturers"
    )


# === Top-Level Response Containers ===


class SearchPartResponse(SwarmBaseModel):
    """Payload wrapped inside ServiceResult for POST /Part/search."""

    parts: List[PartNumber] = Field(default_factory=list)


class DatasheetSource(SwarmBaseModel):
    """Datasheet source reference inside PartResults."""

    resource_id: Optional[str] = Field(None, alias="resourceId")
    image_count: Optional[int] = Field(None, alias="imageCount")
    page_count: Optional[int] = Field(None, alias="pageCount")
    datasheet_cover_image_url: Optional[str] = Field(None, alias="datasheetCoverImageUrl")
    datasheet_url: Optional[str] = Field(None, alias="datasheetUrl")
    title: Optional[str] = None
    short_description: Optional[str] = Field(None, alias="shortDescription")
    manufacturer_name: Optional[str] = Field(None, alias="manufacturerName")
    original_url: Optional[str] = Field(None, alias="originalUrl")
    product_url: Optional[str] = Field(None, alias="productUrl")


class PartResults(SwarmBaseModel):
    """Aggregated part details returned inside ServiceResult for POST /Part/info."""

    parts: List[Any] = Field(default_factory=list)
    product_images: List[Any] = Field(default_factory=list, alias="productImages")
    datasheets: List[Any] = Field(default_factory=list)
    pinouts: List[Any] = Field(default_factory=list)
    circuits: List[Any] = Field(default_factory=list)


class ServiceResult(SwarmBaseModel, Generic[T]):
    """Generic envelope used by Binner Swarm API."""

    response: Optional[T] = None
    api_name: Optional[str] = Field(None, alias="apiName")
    requires_authentication: bool = Field(False, alias="requiresAuthentication")
    redirect_url: Optional[str] = Field(None, alias="redirectUrl")
    errors: List[str] = Field(default_factory=list)

    @property
    def is_success(self) -> bool:
        """Returns True if there are no errors and response payload exists."""
        return len(self.errors) == 0 and self.response is not None
