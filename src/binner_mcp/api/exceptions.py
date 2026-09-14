"""Exceptions for Binner API client and proxy."""

from binner_mcp.common.exceptions import (
    BaseProxyError,
    ProxyAPIError,
    ProxyConnectionError,
)


class BinnerError(BaseProxyError):
    """Base exception for all Binner API proxy errors."""
    pass


class BinnerAuthError(BinnerError):
    """Raised when authentication or token refresh fails."""
    pass


class BinnerConnectionError(ProxyConnectionError, BinnerError):
    """Raised when the Binner instance is unreachable or network times out."""
    pass


class BinnerNotFoundError(BinnerError):
    """Raised when a requested resource (part, project, part type) is not found (HTTP 404)."""
    pass


class BinnerAPIError(ProxyAPIError, BinnerError):
    """Raised when Binner API returns an unhandled HTTP 4xx or 5xx status code."""
    pass
