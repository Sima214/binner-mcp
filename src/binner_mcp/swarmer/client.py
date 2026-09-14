"""Binner Swarm REST proxy client."""

import logging
from typing import Any, Dict, Optional
import requests

from binner_mcp.common.http import BaseHttpClient
from binner_mcp.common.logging import log_trace
from binner_mcp.swarmer.exceptions import (
    SwarmAPIError,
    SwarmConnectionError,
    SwarmError,
    SwarmRateLimitError,
    SwarmTimeoutError,
)
from binner_mcp.swarmer.models import (
    PartResults,
    RateLimitInfo,
    SearchPartRequest,
    SearchPartResponse,
    ServiceResult,
    StatusResponse,
)

logger = logging.getLogger("binner_mcp.swarmer.client")


class SwarmClient(BaseHttpClient):
    """
    Client for interacting directly with the Binner Swarm cloud service (https://swarm.binner.io).

    Provides connection pooling, rate limit tracking, and structured serialization
    for part metadata, schematics, and pinout definitions.
    """

    def __init__(
        self,
        base_url: str = "https://swarm.binner.io",
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(
            base_url=base_url,
            timeout=timeout,
            user_agent="binner-mcp/swarmer",
        )
        self.api_key = api_key
        self.last_rate_limit: Optional[RateLimitInfo] = None

        if self.api_key:
            self.session.headers["X-ApiKey"] = self.api_key

    def _extract_rate_limit_info(self, response: requests.Response) -> RateLimitInfo:
        """Extract and track quota limits from Swarm HTTP response headers."""
        limit = response.headers.get("x-rate-limit-limit")
        remaining_raw = response.headers.get("x-rate-limit-remaining")
        reset = response.headers.get("x-rate-limit-reset")

        remaining: Optional[int] = None
        if remaining_raw is not None:
            try:
                remaining = int(remaining_raw)
            except ValueError:
                remaining = None

        info = RateLimitInfo(limit=limit, remaining=remaining, reset=reset)
        self.last_rate_limit = info
        return info

    def _on_response(
        self,
        response: requests.Response,
        method: str,
        path: str,
        url: str,
        timeout: float,
        kwargs: Dict[str, Any],
    ) -> Optional[requests.Response]:
        limit_info = self._extract_rate_limit_info(response)
        log_trace(
            logger,
            "Swarm Response: HTTP %s for %s | RateLimit: %s remaining (limit %s)",
            response.status_code,
            url,
            limit_info.remaining,
            limit_info.limit,
        )
        return None

    def _handle_response_status(
        self,
        response: requests.Response,
        method: str,
        path: str,
    ) -> None:
        if response.status_code == 429:
            limit_info = self.last_rate_limit or self._extract_rate_limit_info(response)
            raise SwarmRateLimitError(
                message="Swarm API rate limit exceeded",
                limit=limit_info.limit,
                remaining=limit_info.remaining,
                reset=limit_info.reset,
                details=response.text,
            )

        if response.status_code >= 400:
            raise SwarmAPIError(
                message=f"Swarm request failed: {method} {path}",
                status_code=response.status_code,
                response_text=response.text,
            )

    def _handle_request_exception(
        self,
        exc: requests.RequestException,
        method: str,
        url: str,
    ) -> None:
        if isinstance(exc, requests.exceptions.Timeout):
            raise SwarmTimeoutError(f"Swarm request timed out after {self.timeout}s: {url}") from exc
        if isinstance(exc, requests.exceptions.ConnectionError):
            raise SwarmConnectionError(f"Failed to connect to Swarm at {url}: {exc}") from exc
        raise SwarmError(f"Unexpected network error calling Swarm: {exc}") from exc

    def get_status(self) -> StatusResponse:
        """Check health and database status of the Swarm service (GET /Status)."""
        resp = self._execute_request("GET", "/Status")
        return StatusResponse.model_validate(resp.json())

    def search_parts(
        self,
        part_number: str,
        part_type: Optional[str] = None,
        mounting_type: Optional[str] = None,
        record_count: Optional[int] = None,
    ) -> ServiceResult[SearchPartResponse]:
        """Search for parts and retrieve schematics, pinout maps, and parametrics (POST /Part/search)."""
        req = SearchPartRequest(
            partNumber=part_number,
            partType=part_type,
            mountingType=mounting_type,
            recordCount=record_count,
        )
        resp = self._execute_request(
            "POST",
            "/Part/search",
            json=req.model_dump(by_alias=True, exclude_none=True),
        )
        data = resp.json()
        return ServiceResult[SearchPartResponse].model_validate(data)

    def get_part_info(
        self,
        part_number: str,
        part_type: Optional[str] = None,
        mounting_type: Optional[str] = None,
        record_count: Optional[int] = None,
    ) -> ServiceResult[PartResults]:
        """
        Query part information aggregation endpoint (POST /Part/info).

        Note: May experience distributor aggregation latency or timeouts for standard passives/ICs.
        """
        req = SearchPartRequest(
            partNumber=part_number,
            partType=part_type,
            mountingType=mounting_type,
            recordCount=record_count,
        )
        resp = self._execute_request(
            "POST",
            "/Part/info",
            json=req.model_dump(by_alias=True, exclude_none=True),
        )
        data = resp.json()
        return ServiceResult[PartResults].model_validate(data)
