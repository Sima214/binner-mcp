"""Synchronous implementation for system diagnostic and status MCP tools."""

import logging
from typing import Any, Dict
import requests

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import (
    BinnerAuthError,
    BinnerConnectionError,
    BinnerError,
)
from binner_mcp.common.exceptions import ProxyConnectionError
from binner_mcp.mcp.normalization import compact_payload
from binner_mcp.swarmer.client import SwarmClient
from binner_mcp.swarmer.exceptions import SwarmError

logger = logging.getLogger("binner_mcp.mcp.tools.system")


def get_system_status_sync(
    proxy: BinnerAPIProxy,
    swarm: SwarmClient,
    check_cloud: bool = False,
) -> Dict[str, Any]:
    """
    Execute synchronous system status inspection with thread-safe locking.

    Serializes access through proxy._lock and returns clear, compact diagnostics.
    """
    with proxy._lock:
        # 1. Probe reachability with specific network diagnostics
        ping_url = f"{proxy.base_url}/api/ping"
        timeout_sec = min(5.0, float(getattr(proxy, "timeout", 10.0)))
        try:
            resp = proxy.session.get(ping_url, timeout=timeout_sec)
        except requests.exceptions.ConnectionError:
            return {
                "status": "offline",
                "backend_url": proxy.base_url,
                "detail": "Connection refused. Ensure Binner service is running.",
            }
        except requests.exceptions.Timeout:
            return {
                "status": "offline",
                "backend_url": proxy.base_url,
                "detail": f"Connection timed out after {timeout_sec}s.",
            }
        except requests.exceptions.RequestException as req_err:
            return {
                "status": "offline",
                "backend_url": proxy.base_url,
                "detail": f"Network error: {req_err}",
            }

        # Validate ping response
        is_pong = resp.status_code == 200 and resp.text.strip().strip('"') == "pong"
        if not is_pong:
            return {
                "status": "offline",
                "backend_url": proxy.base_url,
                "detail": f"Unhealthy ping response (HTTP {resp.status_code}): {resp.text.strip()[:100]}",
            }

        # 2. Extract installed version via X-Version header
        version = resp.headers.get("X-Version") or "unknown"

        # 3. Ensure authenticated session
        try:
            if not proxy.is_logged_in:
                proxy.login()
            identity = proxy.get_identity()
            user_info = {
                "name": identity.name,
                "email": identity.email_address,
                "is_admin": identity.is_admin,
            }
        except BinnerAuthError as auth_err:
            logger.error("Authentication failed during status check: %s", auth_err)
            return {
                "status": "connected",
                "binner_version": version,
                "backend_url": proxy.base_url,
                "auth_error": str(auth_err),
            }
        except (BinnerConnectionError, ProxyConnectionError) as conn_err:
            return {
                "status": "offline",
                "backend_url": proxy.base_url,
                "detail": f"Connection lost during authentication: {conn_err}",
            }

        # 4. Fetch aggregate inventory metrics
        try:
            summary = proxy.get_summary()
            inventory_info = {
                "unique_parts": summary.unique_parts_count,
                "total_quantity": summary.parts_count,
                "valuation": summary.parts_cost,
                "currency": summary.currency or "USD",
                "low_stock_parts": summary.low_stock_count,
                "projects_count": summary.projects_count,
            }
        except (requests.RequestException, BinnerError, KeyError, ValueError) as err:
            logger.warning("Failed to fetch inventory summary: %s", err)
            inventory_info = {}

        result: Dict[str, Any] = {
            "status": "connected",
            "binner_version": version,
            "backend_url": proxy.base_url,
            "user": user_info,
            "inventory": inventory_info,
        }

        # 5. Optional Swarm cloud check
        if check_cloud:
            try:
                cloud_status = swarm.get_status()
                result["swarm_cloud"] = {
                    "status": "online" if cloud_status.is_up else "offline",
                    "database_status": "online" if cloud_status.is_database_up else "offline",
                }
            except (SwarmError, requests.RequestException, KeyError, ValueError) as exc:
                result["swarm_cloud"] = {
                    "status": "unreachable",
                    "detail": str(exc),
                }

        return compact_payload(result)
