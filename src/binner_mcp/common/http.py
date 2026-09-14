"""Unified HTTP client base with connection pooling, request tracing, and polymorphic lifecycle hooks."""

import logging
import threading
from typing import Any, Dict, Optional
import requests

from binner_mcp.common.exceptions import (
    ProxyAPIError,
    ProxyConnectionError,
    ProxyTimeoutError,
)
from binner_mcp.common.logging import log_trace, sanitize_for_trace

logger = logging.getLogger("binner_mcp.common.http")


class BaseHttpClient:
    """
    Base HTTP client providing connection pooling, URL normalization,
    request tracing with sensitive field redaction, and polymorphic lifecycle hooks.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        user_agent: str = "Binner-MCP/1.0",
        lock: Optional[threading.RLock] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": user_agent,
        })
        self._lock = lock if lock is not None else threading.RLock()

    def build_url(self, path: str) -> str:
        """Resolve a relative API path against base_url."""
        return f"{self.base_url}/{path.lstrip('/')}"

    def close(self) -> None:
        """Close underlying requests Session."""
        self.session.close()

    def __enter__(self) -> "BaseHttpClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # === Polymorphic Extension Points (Subclass Overrides) ===

    def _before_request(
        self,
        method: str,
        path: str,
        url: str,
        kwargs: Dict[str, Any],
    ) -> None:
        """Polymorphic lifecycle hook called before each request is sent."""
        pass

    def _on_response(
        self,
        response: requests.Response,
        method: str,
        path: str,
        url: str,
        timeout: float,
        kwargs: Dict[str, Any],
    ) -> Optional[requests.Response]:
        """
        Polymorphic lifecycle hook called after receiving an HTTP response.
        Returning a new requests.Response replaces the response (e.g. after token refresh retry).
        """
        return None

    def _handle_response_status(
        self,
        response: requests.Response,
        method: str,
        path: str,
    ) -> None:
        """Polymorphic lifecycle hook to validate HTTP response status and raise service-specific errors."""
        if not response.ok:
            raise ProxyAPIError(
                f"Request failed: {method} {path}",
                status_code=response.status_code,
                response_text=response.text,
            )

    def _handle_request_exception(
        self,
        exc: requests.RequestException,
        method: str,
        url: str,
    ) -> None:
        """Polymorphic lifecycle hook to map low-level requests exceptions into service-specific errors."""
        if isinstance(exc, requests.exceptions.Timeout):
            raise ProxyTimeoutError(f"Request timed out after {self.timeout}s: {url}") from exc
        if isinstance(exc, requests.exceptions.ConnectionError):
            raise ProxyConnectionError(f"Failed to connect to {url}: {exc}") from exc
        raise ProxyConnectionError(f"Unexpected network error calling {url}: {exc}") from exc

    # === Core Request Execution ===

    def _execute_request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Execute an HTTP request with polymorphic lifecycle hooks, locking, and error handling.
        """
        with self._lock:
            url = self.build_url(path)
            req_timeout = kwargs.pop("timeout", self.timeout)

            # Fire polymorphic before-request hook
            self._before_request(method, path, url, kwargs)

            log_trace(
                logger,
                "Request %s %s kwargs=%s",
                method,
                url,
                sanitize_for_trace(kwargs),
            )

            try:
                resp = self.session.request(method, url, timeout=req_timeout, **kwargs)
            except requests.RequestException as exc:
                self._handle_request_exception(exc, method, url)
                raise

            # Fire polymorphic on-response hook (e.g. rate-limit tracking or 401 token refresh retry)
            retry_resp = self._on_response(resp, method, path, url, req_timeout, kwargs)
            if retry_resp is not None:
                resp = retry_resp

            log_trace(
                logger,
                "Response %d from %s %s",
                resp.status_code,
                method,
                url,
            )

            # Validate HTTP status and raise appropriate exceptions
            self._handle_response_status(resp, method, path)

            return resp
