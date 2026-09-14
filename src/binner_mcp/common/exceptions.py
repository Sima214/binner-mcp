"""Common exception foundations for Binner MCP clients and proxies."""

from typing import Any, Optional


class BaseProxyError(Exception):
    """Base exception for all Binner MCP proxy and client errors."""

    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (Details: {self.details})"
        return self.message


class ProxyConnectionError(BaseProxyError):
    """Raised when an upstream endpoint is unreachable or network connection fails."""
    pass


class ProxyTimeoutError(ProxyConnectionError):
    """Raised when a request exceeds the configured timeout threshold."""
    pass


class ProxyAPIError(BaseProxyError):
    """Raised when an upstream API returns an unhandled HTTP 4xx or 5xx status code."""

    def __init__(
        self,
        message: str,
        status_code: int,
        response_text: Optional[str] = None,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message, details)
        self.status_code = status_code
        self.response_text = response_text

    def __str__(self) -> str:
        base = f"HTTP {self.status_code}: {self.message}"
        if self.response_text:
            return f"{base} | Response: {self.response_text}"
        return base
