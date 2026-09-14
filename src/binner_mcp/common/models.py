"""Common base Pydantic models for Binner MCP schemas."""

from typing import TypeVar
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class CommonBaseModel(BaseModel):
    """Base model configured to accept both snake_case and camelCase and ignore unknown fields."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        from_attributes=True,
    )
