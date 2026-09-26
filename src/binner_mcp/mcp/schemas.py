"""Pydantic input models for MCP tools.

Defines rich schemas for MCP tool arguments, exposing field types, constraints,
defaults, and documentation to the MCP SDK and connected LLMs.
"""

from typing import Any, List, Optional, Union
from pydantic import ConfigDict, Field

from binner_mcp.common.models import CommonBaseModel


class PartSaveInput(CommonBaseModel):
    """Component record for batch inventory upsert."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    part_number: str = Field(
        ...,
        description="Unique component identifier / Manufacturer Part Number (MPN). Required.",
    )
    part_type: Optional[Union[str, int]] = Field(
        None,
        description=(
            "Overloaded category identifier: category hierarchy path (e.g. 'Passive::Resistor'), "
            "leaf category name, or numeric part type ID."
        ),
    )
    part_type_id: Optional[Union[int, str]] = Field(
        None,
        description="Optional numeric category ID (accepted as fallback if 'part_type' is omitted).",
    )
    quantity: Optional[Union[int, str]] = Field(
        None,
        description="Absolute physical units in stock (>= 0).",
    )
    low_stock_threshold: Optional[Union[int, str]] = Field(
        None,
        description="Reorder alert threshold (>= 0). Triggers low stock alert when quantity <= threshold.",
    )
    cost: Optional[Union[float, str]] = Field(
        None,
        description="Unit purchase cost (>= 0.0).",
    )
    currency: Optional[str] = Field(
        "USD",
        description="Currency code for unit cost (e.g. 'USD', 'EUR').",
    )
    bin_number: Optional[str] = Field(
        None,
        description="Primary storage bin / drawer identifier (e.g. 'A1-04', 'Drawer 12').",
    )
    bin_number2: Optional[str] = Field(
        None,
        description="Secondary storage bin or sub-compartment label.",
    )
    location: Optional[str] = Field(
        None,
        description="Physical storage location (room, cabinet, rack, or shelf name).",
    )
    package_type: Optional[str] = Field(
        None,
        description="Physical component footprint / package (e.g. '0805', 'SOIC-8', 'TO-220').",
    )
    manufacturer: Optional[str] = Field(
        None,
        description="Component manufacturer name.",
    )
    manufacturer_part_number: Optional[str] = Field(
        None,
        description="Manufacturer internal part number if different from part_number.",
    )
    description: Optional[str] = Field(
        None,
        description="Free-form component technical description.",
    )
    datasheet_url: Optional[str] = Field(
        None,
        description="Direct HTTP/HTTPS URL to component datasheet.",
    )
    product_url: Optional[str] = Field(
        None,
        description="Direct URL to supplier product page.",
    )
    part_id: Optional[Union[int, str]] = Field(
        None,
        description="Database primary key of existing part. Explicitly passed for updates.",
    )
    create_only: Optional[bool] = Field(
        False,
        description="If True, mutation halts with an error if the part already exists in inventory.",
    )


class ProjectSaveInput(CommonBaseModel):
    """Maker project record for batch persistence."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: Optional[str] = Field(
        None,
        description="Project name. Required when creating a new project.",
    )
    project_id: Optional[int] = Field(
        None,
        description="Numeric project ID. Required when updating an existing project without name.",
    )
    description: Optional[str] = Field(
        None,
        description="Maker project description or documentation notes.",
    )
    archived: Optional[bool] = Field(
        False,
        description="Archive status of the project.",
    )


class PartTypeSaveInput(CommonBaseModel):
    """Part type / category record for batch persistence."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: Optional[str] = Field(
        None,
        description="Part type / category name (e.g. 'Resistors'). Required when creating a new type.",
    )
    part_type_id: Optional[int] = Field(
        None,
        description="Numeric part type ID. Required when updating an existing category with ambiguous name.",
    )
    parent_part_type_id: Optional[int] = Field(
        None,
        description="Parent category ID for hierarchical nesting (null or 0 for root categories).",
    )
    description: Optional[str] = Field(
        None,
        description="Classification scope or description for this category node.",
    )


class BomPartInput(CommonBaseModel):
    """Bill of Materials line item operation record."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    part_number: Optional[str] = Field(
        None,
        description="Inventory part number to assign or modify.",
    )
    part_id: Optional[int] = Field(
        None,
        description="Inventory numeric part ID.",
    )
    quantity: Optional[int] = Field(
        1,
        description="Required quantity per board unit (>= 1).",
    )
    reference_designator: Optional[str] = Field(
        None,
        description="Silkscreen schematic reference designators (e.g. 'R1, R2, C5').",
    )
    notes: Optional[str] = Field(
        None,
        description="Assembly notes or custom instructions for this line item.",
    )
    remove: Optional[bool] = Field(
        False,
        description="If True, removes this line item assignment from the project BOM.",
    )
    adjust_stock_delta: Optional[int] = Field(
        None,
        description="Optional additive inventory stock adjustment (e.g. -5 to deduct or +5 to restock).",
    )
