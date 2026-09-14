"""System diagnostics, logs, and external integration test endpoints for Binner API."""

import logging
from typing import Any, Dict
import requests

from binner_mcp.api.exceptions import BinnerConnectionError
from binner_mcp.api.models import (
    ApiConfigValue,
    PaginatedResponse,
    SystemLogEntry,
    TestApiRequest,
    TestApiResponse,
)
from binner_mcp.common.logging import log_trace

logger = logging.getLogger("binner_mcp.api.client")


class SystemMixin:
    """Mixin implementing Binner system, diagnostic, and integration test REST endpoints."""

    def get_system_version(self) -> Dict[str, Any]:
        """
        Fetch Binner backend version by extracting the X-Version header from the ping endpoint.

        Don't query the /api/system/version endpoint as that also retrieves latest version information.
        """
        with self._lock:
            url = f"{self.base_url}/api/ping"
            log_trace(logger, "GET %s (version extraction)", url)
            try:
                resp = self.session.get(url, timeout=min(5.0, self.timeout))
                version = resp.headers.get("X-Version") or "unknown"
                return {"version": version}
            except requests.exceptions.RequestException as exc:
                raise BinnerConnectionError(f"Unable to reach Binner instance at {self.base_url}") from exc

    def get_system_info(self) -> Dict[str, Any]:
        """Fetch Binner installation details (requires Admin rights)."""
        resp = self._execute_request("GET", "/api/system/info")
        return resp.json()

    def get_system_logs(
        self,
        source: str = "binner",
        page: int = 1,
        results: int = 50,
    ) -> PaginatedResponse[SystemLogEntry]:
        """
        Fetch backend application logs (GET /api/system/logs).

        Valid sources: 'binner', 'microsoft', 'missinglocalekeys', 'internal'.
        """
        valid_sources = {"binner", "microsoft", "missinglocalekeys", "internal"}
        clean_source = source.lower()
        if clean_source not in valid_sources:
            raise ValueError(f"Invalid log source '{source}'. Must be one of: {', '.join(sorted(valid_sources))}")

        resp = self._execute_request(
            "GET",
            "/api/system/logs",
            params={"by": clean_source, "page": page, "results": results},
        )
        return PaginatedResponse[SystemLogEntry].model_validate(resp.json())

    def test_swarm_integration(
        self,
        api_url: str = "https://swarm.binner.io",
        enabled: bool = True,
    ) -> TestApiResponse:
        """Test connectivity to the Swarm datasheet & metadata aggregation service (PUT /api/settings/testapi)."""
        req = TestApiRequest(
            name="swarm",
            configuration=[
                ApiConfigValue(key="Enabled", value=str(enabled).lower()),
                ApiConfigValue(key="ApiUrl", value=api_url),
            ],
        )
        resp = self._execute_request(
            "PUT",
            "/api/settings/testapi",
            json=req.model_dump(by_alias=True, exclude_none=True),
        )
        return TestApiResponse.model_validate(resp.json())
