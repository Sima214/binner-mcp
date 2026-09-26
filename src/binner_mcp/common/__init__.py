"""Shared common utilities, base models, exceptions, and HTTP client foundations."""

from binner_mcp.common.exceptions import (
    BaseProxyError,
    ProxyAPIError,
    ProxyConnectionError,
    ProxyTimeoutError,
)
from binner_mcp.common.http import (
    BaseHttpClient,
    RETRY_DELAY,
    is_transient_network_error,
)
from binner_mcp.common.logging import (
    TRACE_LEVEL_NUM,
    log_trace,
    sanitize_for_trace,
    setup_logging,
    setup_trace_level,
)
from binner_mcp.common.models import CommonBaseModel

__all__ = [
    "BaseProxyError",
    "ProxyConnectionError",
    "ProxyTimeoutError",
    "ProxyAPIError",
    "BaseHttpClient",
    "RETRY_DELAY",
    "is_transient_network_error",
    "CommonBaseModel",
    "TRACE_LEVEL_NUM",
    "setup_trace_level",
    "setup_logging",
    "sanitize_for_trace",
    "log_trace",
]
