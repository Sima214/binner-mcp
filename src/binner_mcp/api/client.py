"""MCP-agnostic REST proxy client for local Binner inventory instances."""

import logging
from typing import Any

from binner_mcp.api.base import BaseBinnerClient
from binner_mcp.api.cache import PartCacheComp
from binner_mcp.api.data import DataComp
from binner_mcp.api.part_types import PartTypesComp
from binner_mcp.api.parts import PartsComp
from binner_mcp.api.projects import ProjectsComp
from binner_mcp.api.system import SystemComp
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
    PartCacheComp,
    PartsComp,
    PartTypesComp,
    ProjectsComp,
    SystemComp,
    DataComp,
    BaseBinnerClient,
):
    """
    Programmatic client for local Binner instances.

    Manages connection pooling, cookie-bound token refreshes, and verified API endpoints.
    Composes domain components for parts inventory, caching, taxonomies, projects, BOM,
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
