"""Exceptions for Swarm API client and proxy."""

from typing import Any, Optional

from binner_mcp.common.exceptions import (
    BaseProxyError,
    ProxyAPIError,
    ProxyConnectionError,
    ProxyTimeoutError,
)


class SwarmError(BaseProxyError):
    """Base exception for all Swarm API errors."""
    pass


class SwarmConnectionError(ProxyConnectionError, SwarmError):
    """Raised when the Swarm endpoint is unreachable or network connection fails."""
    pass


class SwarmTimeoutError(ProxyTimeoutError, SwarmError):
    """Raised when a Swarm request exceeds the configured timeout threshold."""
    pass


class SwarmRateLimitError(SwarmError):
    """Raised when Swarm returns HTTP 429 Too Many Requests."""

    def __init__(
        self,
        message: str = "Swarm API rate limit exceeded",
        limit: Optional[str] = None,
        remaining: Optional[int] = None,
        reset: Optional[str] = None,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message, details)
        self.limit = limit
        self.remaining = remaining
        self.reset = reset

    def __str__(self) -> str:
        parts = [self.message]
        if self.limit:
            parts.append(f"Limit: {self.limit}")
        if self.remaining is not None:
            parts.append(f"Remaining: {self.remaining}")
        if self.reset:
            parts.append(f"Reset: {self.reset}")
        return " | ".join(parts)


class SwarmAPIError(ProxyAPIError, SwarmError):
    """Raised when Swarm API returns an unhandled HTTP 4xx or 5xx status code."""
    pass
