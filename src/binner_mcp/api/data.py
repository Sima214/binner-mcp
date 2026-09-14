"""Data export, multipart file import, CSV ingestion, and bulk ingestion endpoints for Binner API."""

import csv
import io
import logging
from pathlib import Path
from typing import Any, Dict, List, Union
import zipfile
import requests

from binner_mcp.api.exceptions import BinnerAPIError, BinnerConnectionError
from binner_mcp.api.models import (
    BinnerExportArchive,
    BulkImportItem,
    BulkImportResponse,
    PartResponse,
)
from binner_mcp.common.logging import log_trace

logger = logging.getLogger("binner_mcp.api.client")


class DataMixin:
    """Mixin implementing Binner data export and batch ingestion REST endpoints."""

    def export_data(
        self,
        export_format: str = "csv",
        populate_cache: bool = True,
    ) -> BinnerExportArchive:
        """
        Export all database tables from Binner (GET /api/export).

        Returns a BinnerExportArchive object mirroring the ZIP archive filesystem structure.
        If populate_cache is True and Parts.csv is in the archive, rapidly populates
        the in-memory part_id <-> part_number cache.
        """
        resp = self._execute_request("GET", "/api/export", params={"exportFormat": export_format})
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        files_dict: Dict[str, str] = {}
        for name in zf.namelist():
            try:
                files_dict[name] = zf.read(name).decode("utf-8-sig")
            except UnicodeDecodeError:
                files_dict[name] = zf.read(name).decode("latin-1", errors="replace")

        archive = BinnerExportArchive(files=files_dict)

        if populate_cache and archive.parts_csv:
            with self._lock:
                try:
                    reader = csv.DictReader(io.StringIO(archive.parts_csv))
                    hydrated_count = 0
                    for row in reader:
                        raw_id = row.get("#PartId") or row.get("PartId")
                        pnum = row.get("PartNumber")
                        if raw_id is not None and pnum:
                            try:
                                pid = int(raw_id)
                                self._cache_part(pid, pnum)
                                hydrated_count += 1
                            except ValueError:
                                continue
                    logger.debug("Hydrated %d parts into cache from export archive", hydrated_count)
                except Exception as err:
                    logger.warning("Failed to populate part cache from export archive: %s", err)

        return archive

    def import_data_file(
        self,
        file_path_or_content: Union[str, bytes, Path],
        filename: str = "Parts.csv",
    ) -> Dict[str, Any]:
        """
        Upload and import a CSV or ZIP file into Binner (POST /api/data/import).

        Accepts either a filesystem path or raw bytes/str content.
        Uses multipart/form-data.
        """
        if isinstance(file_path_or_content, (str, Path)) and Path(file_path_or_content).is_file():
            p = Path(file_path_or_content)
            filename = p.name
            file_bytes = p.read_bytes()
        elif isinstance(file_path_or_content, str):
            file_bytes = file_path_or_content.encode("utf-8")
        else:
            file_bytes = bytes(file_path_or_content)

        files = [
            ("files", (filename, file_bytes, "application/octet-stream")),
        ]

        with self._lock:
            if not self._is_logged_in:
                self.login()

            url = f"{self.base_url}/api/data/import"
            headers = {
                "Authorization": f"Bearer {self.jwt_token}",
                "Content-Type": None,
            }
            log_trace(logger, "POST multipart %s [file=%s, size=%d]", url, filename, len(file_bytes))

            try:
                resp = self.session.post(url, files=files, headers=headers)
            except requests.RequestException as exc:
                raise BinnerConnectionError(f"Connection failed during file import: {exc}") from exc

            if resp.status_code == 401:
                self._handle_token_refresh()
                headers = {
                    "Authorization": f"Bearer {self.jwt_token}",
                    "Content-Type": None,
                }
                try:
                    files = [("files", (filename, file_bytes, "application/octet-stream"))]
                    resp = self.session.post(url, files=files, headers=headers)
                except requests.RequestException as exc:
                    raise BinnerConnectionError(f"Connection failed during file import: {exc}") from exc

            if resp.status_code >= 400:
                raise BinnerAPIError(f"File import failed ({resp.status_code}): {resp.text}", status_code=resp.status_code)

            return resp.json()

    def import_parts_csv(
        self,
        csv_content_or_path: Union[str, Path],
    ) -> List[PartResponse]:
        """
        Client-side CSV batch importer. Reads CSV rows and creates parts sequentially via create_part.

        Expects CSV headers matching CreatePartRequest fields (e.g., partNumber, description, quantity).
        Automatically updates the in-memory cache as parts are created.
        """
        if isinstance(csv_content_or_path, (str, Path)) and Path(csv_content_or_path).is_file():
            content = Path(csv_content_or_path).read_text(encoding="utf-8-sig")
        else:
            content = str(csv_content_or_path)

        reader = csv.DictReader(io.StringIO(content))
        created_parts: List[PartResponse] = []

        for row in reader:
            part_number = row.get("partNumber") or row.get("PartNumber") or row.get("part_number")
            if not part_number:
                continue

            part_data: Dict[str, Any] = {"partNumber": part_number.strip()}

            desc = row.get("description") or row.get("Description")
            if desc:
                part_data["description"] = desc.strip()

            qty = row.get("quantity") or row.get("Quantity")
            if qty is not None and str(qty).strip() != "":
                try:
                    part_data["quantity"] = int(float(qty))
                except ValueError:
                    pass

            loc = row.get("location") or row.get("Location")
            if loc:
                part_data["location"] = loc.strip()

            bin1 = row.get("binNumber") or row.get("BinNumber")
            if bin1:
                part_data["binNumber"] = bin1.strip()

            bin2 = row.get("binNumber2") or row.get("BinNumber2")
            if bin2:
                part_data["binNumber2"] = bin2.strip()

            created = self.create_part(part_data)
            created_parts.append(created)

        return created_parts

    def bulk_import_parts(
        self,
        parts: List[Union[BulkImportItem, Dict[str, Any]]],
    ) -> BulkImportResponse:
        """
        Import multiple components in a batch via Binner's free batch ingestion endpoint (POST /api/part/bulk).

        Automatically resolves categories and updates inventory. Hydrates cache with added and updated parts.
        """
        items: List[Dict[str, Any]] = []
        for p in parts:
            if isinstance(p, BulkImportItem):
                items.append(p.model_dump(by_alias=True, exclude_none=True))
            else:
                validated = BulkImportItem.model_validate(p)
                items.append(validated.model_dump(by_alias=True, exclude_none=True))

        resp = self._execute_request("POST", "/api/part/bulk", json={"parts": items})
        bulk_resp = BulkImportResponse.model_validate(resp.json())

        # Hydrate cache with both added and updated parts
        all_parts = bulk_resp.added + bulk_resp.updated
        if all_parts:
            self._cache_parts(all_parts)

        return bulk_resp
