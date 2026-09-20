import json
from typing import Any, Dict, Optional, TypeVar
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class CommonBaseModel(BaseModel):
    """Base model configured to accept both snake_case and camelCase, ignore unknown fields, and support JSON serialization."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        from_attributes=True,
        serialize_by_alias=True,
    )

    def to_json(self, indent: Optional[int] = None, **kwargs: Any) -> str:
        """Serialize model to a JSON formatted string."""
        return self.model_dump_json(indent=indent, **kwargs)

    def to_dict(self, **kwargs: Any) -> Dict[str, Any]:
        """Convert model to a dictionary with JSON-compatible primitives."""
        return self.model_dump(mode="json", **kwargs)

    def __json__(self) -> Dict[str, Any]:
        """Hook for third-party JSON libraries (orjson, simplejson, etc.)."""
        return self.model_dump(by_alias=True, mode="json")


# Enable standard library json.dumps() to serialize Pydantic models automatically
_orig_json_default = json.JSONEncoder.default


def _binner_json_default(self: json.JSONEncoder, obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(by_alias=True, mode="json")
    return _orig_json_default(self, obj)


if not getattr(json.JSONEncoder.default, "_is_binner_patched", False):
    setattr(_binner_json_default, "_is_binner_patched", True)
    json.JSONEncoder.default = _binner_json_default

