"""Binner MCP Server implementation using Python MCP SDK 2."""

import asyncio
import concurrent.futures
import functools
import logging
from typing import Any, Dict, List, Optional

import requests

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase

# Enforce strict rejection of unknown arguments across all MCP tools
ArgModelBase.model_config["extra"] = "forbid"

from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import BinnerError
from binner_mcp.config import BinnerConfig, load_config
from binner_mcp.mcp.categories import CategoryResolver
from binner_mcp.mcp.normalization import compact_payload
from binner_mcp.mcp.schemas import (
    BomPartInput,
    PartSaveInput,
    PartTypeSaveInput,
    ProjectSaveInput,
)
from binner_mcp.mcp.tools.cloud import lookup_cloud_parts_sync
from binner_mcp.mcp.tools.inventory import (
    delete_parts_sync,
    get_parts_sync,
    list_parts_sync,
    save_parts_sync,
)
from binner_mcp.mcp.tools.part_types import (
    delete_part_types_sync,
    list_part_types_sync,
    save_part_types_sync,
)
from binner_mcp.mcp.tools.projects import (
    consume_project_bom_sync,
    delete_projects_sync,
    get_projects_sync,
    list_projects_sync,
    manage_bom_parts_sync,
    save_projects_sync,
)
from binner_mcp.mcp.tools.system import get_system_status_sync
from binner_mcp.swarmer.client import SwarmClient

logger = logging.getLogger("binner_mcp.mcp.server")


class BinnerMCPServer:
    """
    Standard Python class managing the Binner MCP server lifecycle,
    underlying REST client proxy, single-thread task queue, and protocol tool registrations.
    """

    def __init__(
        self,
        config: Optional[BinnerConfig] = None,
        proxy: Optional[BinnerAPIProxy] = None,
        swarm: Optional[SwarmClient] = None,
    ) -> None:
        self.config = config or load_config()
        self.proxy = proxy or BinnerAPIProxy(
            base_url=self.config.base_url,
            username=self.config.username,
            password=self.config.password,
        )
        self.swarm = swarm or SwarmClient()
        self.mcp = MCPServer(
            name="binner-mcp",
            version="0.1.0",
            instructions="Binner inventory and maker project assistant.",
        )
        self._category_cache: Dict[int, str] = {}
        self._category_name_to_id: Dict[str, int] = {}
        self.category_delimiter: str = self.config.category_delimiter
        self.category_resolver = CategoryResolver(delimiter=self.category_delimiter)
        self.retry_delay: float = self.config.retry_delay
        self.retry_count: int = self.config.retry_count

        # Dedicated single-thread executor to strictly serialize all sync proxy operations
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="binner-mcp-sync",
        )

        self._register_tools()
        self._register_resources()

    async def _run_sync(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """
        Execute a synchronous blocking function in the dedicated single-thread executor.

        Guarantees strict FIFO execution order across all synchronous proxy operations,
        preventing thread pool thrashing and race conditions on session cookies or tokens.
        """
        loop = asyncio.get_running_loop()
        if kwargs:
            call = functools.partial(func, *args, **kwargs)
            return await loop.run_in_executor(self._executor, call)
        return await loop.run_in_executor(self._executor, func, *args)

    def _register_tools(self) -> None:
        """Register MCP tools on the underlying MCPServer instance."""

        @self.mcp.tool()
        async def get_system_status(check_cloud: bool = False) -> Dict[str, Any]:
            """
            Get Binner instance health, version, user identity, and inventory summary.

            Args:
                check_cloud: Probe Binner Swarm cloud reachability.
            """
            return await self._run_sync(
                get_system_status_sync,
                self.proxy,
                self.swarm,
                check_cloud=check_cloud,
            )

        @self.mcp.tool()
        async def list_parts(
            query: Optional[str] = None,
            part_type: Optional[str] = None,
            bin_number: Optional[str] = None,
            location: Optional[str] = None,
            package_type: Optional[str] = None,
            manufacturer: Optional[str] = None,
            low_stock_only: bool = False,
            fields: Optional[List[str]] = None,
            page: int = 1,
            limit: int = 20,
            sort_by: str = "DateCreatedUtc",
            direction: str = "Descending",
        ) -> Dict[str, Any]:
            """
            Search and filter parts. Returns (id, part_number) unless extra fields are requested.

            Args:
                query: Search keyword across part numbers and descriptions.
                part_type: Filter by category name or path.
                bin_number: Filter by storage bin.
                location: Filter by room or cabinet.
                package_type: Filter by footprint/package (e.g. '0805', 'SOIC-8').
                manufacturer: Filter by manufacturer name.
                low_stock_only: Return only parts at or below threshold.
                fields: Extra fields to return (e.g. ['quantity', 'location', 'bin_number']).
                page: Page number (1-based).
                limit: Max results per page (1-500).
                sort_by: Column to sort by (default 'DateCreatedUtc').
                direction: 'Ascending' or 'Descending'.
            """
            return await self._run_sync(
                list_parts_sync,
                self.proxy,
                query=query,
                part_type=part_type,
                bin_number=bin_number,
                location=location,
                package_type=package_type,
                manufacturer=manufacturer,
                low_stock_only=low_stock_only,
                fields=fields,
                page=page,
                limit=limit,
                sort_by=sort_by,
                direction=direction,
                category_resolver=self.category_resolver,
            )

        @self.mcp.tool()
        async def get_parts(
            part_numbers: Optional[List[str]] = None,
            part_ids: Optional[List[int]] = None,
            fields: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            """
            Get component details, bin locations, category paths, and datasheets by part number or ID.

            Args:
                part_numbers: Part numbers to fetch.
                part_ids: Numeric part IDs to fetch.
                fields: Optional list of specific fields to return (e.g. ['quantity', 'bin_number', 'location']).
            """
            return await self._run_sync(
                get_parts_sync,
                self.proxy,
                self._category_cache,
                part_numbers=part_numbers,
                part_ids=part_ids,
                fields=fields,
            )

        @self.mcp.tool()
        async def save_parts(
            parts: List[PartSaveInput],
        ) -> Dict[str, Any]:
            """
            Batch create or update parts. Each item requires 'part_number'.

            Args:
                parts: Part records with fields (e.g. 'part_number', 'quantity', 'cost', 'bin_number', 'part_type').
                       'part_type' accepts a numeric ID (e.g. 10 or '10') or a category path/name string.
            """
            return await self._run_sync(
                save_parts_sync,
                self.proxy,
                self._category_cache,
                self._category_name_to_id,
                parts,
                category_delimiter=self.category_delimiter,
                retry_delay=self.retry_delay,
                retry_count=self.retry_count,
                category_resolver=self.category_resolver,
            )

        @self.mcp.tool()
        async def delete_parts(
            part_numbers: Optional[List[str]] = None,
            part_ids: Optional[List[int]] = None,
        ) -> Dict[str, Any]:
            """
            Batch delete parts by part number or ID.

            Args:
                part_numbers: Part numbers to delete.
                part_ids: Numeric part IDs to delete.
            """
            return await self._run_sync(
                delete_parts_sync,
                self.proxy,
                part_numbers=part_numbers,
                part_ids=part_ids,
                retry_delay=self.retry_delay,
                retry_count=self.retry_count,
            )

        @self.mcp.tool()
        async def list_projects(
            page: int = 1,
            limit: int = 50,
            sort_by: str = "DateCreatedUtc",
            direction: str = "Descending",
            query: Optional[str] = None,
        ) -> Dict[str, Any]:
            """
            Search and list maker projects with pagination, keyword search, and metadata.

            Args:
                page: Page number (1-based).
                limit: Max projects to return (1-500).
                sort_by: Column to sort by (default 'DateCreatedUtc').
                direction: 'Ascending' or 'Descending'.
                query: Optional search keyword to filter projects by name or description.
            """
            return await self._run_sync(
                list_projects_sync,
                self.proxy,
                page=page,
                limit=limit,
                sort_by=sort_by,
                direction=direction,
                query=query,
            )

        @self.mcp.tool()
        async def get_projects(
            project_ids: Optional[List[int]] = None,
            names: Optional[List[str]] = None,
            include_bom: bool = False,
        ) -> Dict[str, Any]:
            """
            Batch inspect maker projects by IDs or names, with optional BOM inclusion.

            Args:
                project_ids: Numeric project IDs to inspect.
                names: Project names to inspect.
                include_bom: Include Bill of Materials for each project.
            """
            return await self._run_sync(
                get_projects_sync,
                self.proxy,
                project_ids=project_ids,
                names=names,
                include_bom=include_bom,
            )

        @self.mcp.tool()
        async def save_projects(
            projects: List[ProjectSaveInput],
        ) -> Dict[str, Any]:
            """
            Batch create or update maker projects. Each item requires 'name' (for create) or 'project_id' (for update).

            Args:
                projects: Project records with 'name', optional 'description', optional 'project_id', optional 'archived'.
            """
            return await self._run_sync(
                save_projects_sync,
                self.proxy,
                projects=projects,
                retry_delay=self.retry_delay,
                retry_count=self.retry_count,
            )

        @self.mcp.tool()
        async def delete_projects(
            project_ids: Optional[List[int]] = None,
            names: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            """
            Batch delete maker projects by ID or name.

            Args:
                project_ids: Numeric project IDs to delete.
                names: Project names to delete.
            """
            return await self._run_sync(
                delete_projects_sync,
                self.proxy,
                project_ids=project_ids,
                names=names,
                retry_delay=self.retry_delay,
                retry_count=self.retry_count,
            )

        @self.mcp.tool()
        async def consume_project_bom(
            project_id: Optional[int] = None,
            name: Optional[str] = None,
            build_quantity: int = 1,
        ) -> Dict[str, Any]:
            """
            Deduct inventory stock for assembling board units of a maker project's BOM.

            Args:
                project_id: Numeric project ID to consume for.
                name: Project name to consume for.
                build_quantity: Number of complete board units to assemble (>= 1).
            """
            return await self._run_sync(
                consume_project_bom_sync,
                self.proxy,
                project_id=project_id,
                name=name,
                build_quantity=build_quantity,
                retry_delay=self.retry_delay,
                retry_count=self.retry_count,
            )

        @self.mcp.tool()
        async def list_part_types(
            depth: Optional[int] = None,
            root_id: Optional[int] = None,
            root_name: Optional[str] = None,
            include_descriptions: bool = False,
            include_part_counts: bool = False,
        ) -> Dict[str, Any]:
            """
            List part types structured as a lightweight hierarchical tree focusing on IDs and names.

            Args:
                depth: Optional maximum depth of tree recursion (e.g. 1 for top-level root categories only).
                root_id: Optional root category ID to scope the tree to a single subtree.
                root_name: Optional root category name to scope the tree to a single subtree.
                include_descriptions: If True, includes description per node (default False).
                include_part_counts: If True, includes parts count per part type (default False).
            """
            return await self._run_sync(
                list_part_types_sync,
                self.proxy,
                depth=depth,
                root_id=root_id,
                root_name=root_name,
                include_descriptions=include_descriptions,
                include_part_counts=include_part_counts,
                category_resolver=self.category_resolver,
            )

        @self.mcp.tool()
        async def save_part_types(
            part_types: List[PartTypeSaveInput],
        ) -> Dict[str, Any]:
            """
            Batch create or update part types.

            Args:
                part_types: Part type records with 'name', optional 'description', optional 'parent_part_type_id', optional 'part_type_id'.
            """
            return await self._run_sync(
                save_part_types_sync,
                self.proxy,
                self._category_cache,
                self._category_name_to_id,
                part_types=part_types,
                retry_delay=self.retry_delay,
                retry_count=self.retry_count,
                category_resolver=self.category_resolver,
            )

        @self.mcp.tool()
        async def delete_part_types(
            part_type_ids: Optional[List[int]] = None,
            names: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            """
            Batch delete part types by ID or name.

            Args:
                part_type_ids: Numeric part type IDs to delete.
                names: Part type names to delete.
            """
            return await self._run_sync(
                delete_part_types_sync,
                self.proxy,
                self._category_cache,
                self._category_name_to_id,
                part_type_ids=part_type_ids,
                names=names,
                retry_delay=self.retry_delay,
                retry_count=self.retry_count,
                category_resolver=self.category_resolver,
            )

        @self.mcp.tool()
        async def manage_bom_parts(
            project_id: int,
            parts: List[BomPartInput],
        ) -> Dict[str, Any]:
            """
            Batch allocate, update, or remove BOM line items for a project.

            Args:
                project_id: Target project ID.
                parts: BOM items with 'part_number'/'part_id', 'quantity', 'reference_designator', optional 'remove'.
            """
            return await self._run_sync(
                manage_bom_parts_sync,
                self.proxy,
                project_id=project_id,
                parts=parts,
                retry_delay=self.retry_delay,
                retry_count=self.retry_count,
            )

        @self.mcp.tool()
        async def lookup_cloud_parts(
            part_numbers: List[str],
        ) -> Dict[str, Any]:
            """
            Lookup manufacturer pinouts, package footprints, and datasheets from Binner Swarm cloud.

            Args:
                part_numbers: Part numbers / MPNs to look up.
            """
            return await self._run_sync(
                lookup_cloud_parts_sync,
                self.swarm,
                part_numbers=part_numbers,
            )

    def _register_resources(self) -> None:
        """Register dynamic MCP resources on the underlying MCPServer instance."""

        @self.mcp.resource("binner://status", mime_type="application/json")
        async def get_status_resource() -> Dict[str, Any]:
            """System health, version, auth identity, and aggregate inventory summary."""
            return await self._run_sync(
                get_system_status_sync,
                self.proxy,
                self.swarm,
                check_cloud=False,
            )

        @self.mcp.resource("binner://categories", mime_type="application/json")
        async def get_categories_resource() -> Dict[str, Any]:
            """Hierarchical category tree with category paths."""
            return await self._run_sync(self._get_categories_resource_sync)

        @self.mcp.resource("binner://low-stock", mime_type="application/json")
        async def get_low_stock_resource() -> Dict[str, Any]:
            """Parts at or below low-stock threshold."""
            return await self._run_sync(self._get_low_stock_resource_sync)

        @self.mcp.resource("binner://projects/{project_id}/bom", mime_type="application/json")
        async def get_project_bom_resource(project_id: str) -> Dict[str, Any]:
            """BOM line items for project."""
            return await self._run_sync(self._get_project_bom_resource_sync, project_id)

        @self.mcp.resource("binner://parts/{identifier}", mime_type="application/json")
        async def get_part_resource(identifier: str) -> Dict[str, Any]:
            """Complete specifications and category path for a single component."""
            return await self._run_sync(self._get_part_resource_sync, identifier)

    def _get_categories_resource_sync(self) -> Dict[str, Any]:
        with self.proxy._lock:
            if not self._category_cache:
                self._warm_category_cache()
            return {"categories": self._category_cache}

    def _get_low_stock_resource_sync(self) -> Dict[str, Any]:
        with self.proxy._lock:
            paginated = self.proxy.get_low_stock(results=200)
            items = [
                compact_payload({
                    "id": p.part_id,
                    "part_number": p.part_number,
                    "quantity": p.quantity,
                    "low_stock_threshold": p.low_stock_threshold,
                    "location": p.location,
                    "bin_number": p.bin_number,
                })
                for p in paginated.items
            ]
            return {
                "total_items": paginated.total_items,
                "parts": items,
            }

    def _get_project_bom_resource_sync(self, project_id: str) -> Dict[str, Any]:
        with self.proxy._lock:
            try:
                pid = int(project_id)
            except ValueError:
                return {"error": f"Invalid project_id: {project_id}"}
            bom = self.proxy.get_bom(project_id=pid)
            return compact_payload(bom)

    def _get_part_resource_sync(self, identifier: str) -> Dict[str, Any]:
        with self.proxy._lock:
            part = None
            if identifier.isdigit():
                pid = int(identifier)
                pn = self.proxy.get_part_number_by_id(pid)
                part = self.proxy.get_part_by_number(pn) if pn else self.proxy.get_part_by_id(pid)
            else:
                part = self.proxy.get_part_by_number(identifier)

            if not part:
                return {"error": f"Part '{identifier}' not found."}

            category_path = self._category_cache.get(part.part_type_id) or part.part_type
            rec = {
                "id": part.part_id,
                "part_number": part.part_number,
                "quantity": part.quantity,
                "low_stock_threshold": part.low_stock_threshold,
                "cost": part.cost,
                "currency": part.currency,
                "bin_number": part.bin_number,
                "bin_number2": part.bin_number2,
                "location": part.location,
                "package_type": part.package_type,
                "part_type": category_path,
                "manufacturer": part.manufacturer,
                "manufacturer_part_number": part.manufacturer_part_number,
                "description": part.description,
                "datasheet_url": part.datasheet_url,
                "product_url": part.product_url,
            }
            return compact_payload(rec)

    def connect(self) -> bool:
        """
        Attempt to connect to Binner, authenticate, and pre-warm caches.

        If Binner is offline, logs a warning and returns False without crashing,
        allowing the MCP server to start in disconnected mode and report offline diagnostics.
        """
        with self.proxy._lock:
            try:
                is_alive = self.proxy.ping()
            except (requests.RequestException, BinnerError, ConnectionError, OSError) as exc:
                logger.warning("Binner instance at %s is unreachable: %s", self.config.base_url, exc)
                return False

            if not is_alive:
                logger.warning(
                    "Binner instance at %s is offline or returned unhealthy status. "
                    "Starting MCP server in disconnected mode.",
                    self.config.base_url,
                )
                return False

            try:
                self.proxy.login()
                self._warm_category_cache()
                self.proxy.list_parts(results=200)
                logger.info("Connected to Binner at %s; identity and category caches hydrated.", self.config.base_url)
                return True
            except (requests.RequestException, BinnerError, ValueError, KeyError) as exc:
                logger.warning("Failed to authenticate with Binner at %s: %s", self.config.base_url, exc)
                return False

    def _warm_category_cache(self) -> None:
        """Fetch all part categories and build hierarchical category paths."""
        self.category_resolver.warm_cache(
            self.proxy,
            category_cache=self._category_cache,
            category_name_to_id=self._category_name_to_id,
        )

    def close(self) -> None:
        """Shut down background executor and close HTTP sessions."""
        self._executor.shutdown(wait=False)
        self.proxy.close()
        self.swarm.close()

    def run_stdio(self) -> None:
        """Connect and run MCP server over Standard I/O (JSON-RPC)."""
        self.connect()
        asyncio.run(self.mcp.run_stdio_async())

    def run_http(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        """Connect and run MCP server over modern Streamable HTTP transport."""
        self.connect()
        asyncio.run(self.mcp.run_streamable_http_async(host=host, port=port))

    def run_sse(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        """Connect and run MCP server over legacy SSE HTTP transport."""
        self.connect()
        asyncio.run(self.mcp.run_sse_async(host=host, port=port))
