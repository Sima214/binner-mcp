"""MCP-agnostic REST proxy client for local Binner inventory instances."""

import logging
from typing import Any

from binner_mcp.api.base import BaseBinnerClient
from binner_mcp.api.cache import PartCacheMixin
from binner_mcp.api.data import DataMixin
from binner_mcp.api.part_types import PartTypesMixin
from binner_mcp.api.parts import PartsMixin
from binner_mcp.api.projects import ProjectsMixin
from binner_mcp.api.system import SystemMixin
from binner_mcp.common.logging import (
    TRACE_LEVEL_NUM,
    log_trace,
    sanitize_for_trace,
)

logger = logging.getLogger("binner_mcp.api.client")

# Backward compatibility aliases
_log_trace = lambda msg, *args, **kwargs: log_trace(logger, msg, *args, **kwargs)
_sanitize_for_trace = sanitize_for_trace


class BinnerAPIProxy(
    PartCacheMixin,
    PartsMixin,
    PartTypesMixin,
    ProjectsMixin,
    SystemMixin,
    DataMixin,
    BaseBinnerClient,
):
    """
    MCP-agnostic client proxy for local Binner instances.

    Manages connection pooling, cookie-bound token refreshes, and verified REST endpoints.
    Composes domain mixins for parts inventory, caching, taxonomies, projects, BOM,
    system diagnostics, and batch import/export operations.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8090",
        username: str = "admin",
        password: str = "admin",
        timeout: float = 10.0,
    ) -> None:
        super().__init__(
            base_url=base_url,
            username=username,
            password=password,
            timeout=timeout,
        )


__all__ = ["BinnerAPIProxy", "TRACE_LEVEL_NUM"]
