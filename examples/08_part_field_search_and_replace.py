#!/usr/bin/env python3
"""
Search and replace text within specified fields across Binner inventory parts.

Command-line tool supporting regex and literal matching, field scoping, and dry-run preview.
Uses the Binner API Proxy (binner_mcp.api).
"""

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from binner_mcp.api.client import BinnerAPIProxy
from binner_mcp.api.exceptions import (
    BinnerAPIError,
    BinnerAuthError,
    BinnerConnectionError,
    BinnerError,
)
from binner_mcp.api.models import PartResponse, UpdatePartRequest
from binner_mcp.config import BinnerConfig, load_config

# Setup logging targeting sys.stderr exclusively
logger = logging.getLogger("partsr")

KNOWN_PART_FIELDS = {
    "part_number",
    "description",
    "location",
    "bin_number",
    "bin_number2",
    "package_type",
    "manufacturer",
    "manufacturer_part_number",
    "value",
    "keywords",
    "product_url",
    "datasheet_url",
    "lowest_cost_supplier",
    "lowest_cost_supplier_url",
    "symbol_name",
    "footprint_name",
    "digi_key_part_number",
    "mouser_part_number",
    "arrow_part_number",
    "tme_part_number",
    "element14_part_number",
}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse and validate command line arguments."""
    parser = argparse.ArgumentParser(
        description="Search and replace patterns within part fields across Binner inventory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run: preview replacing 'SMD' with 'Surface Mount' in descriptions
  python examples/08_part_field_search_and_replace.py "SMD" "Surface Mount" --fields description --dry

  # Case-insensitive search and replace across multiple fields
  python examples/08_part_field_search_and_replace.py "Drawer A" "DRAWER-A" --fields location bin_number

  # Regex search and replace with capture group backreference
  python examples/08_part_field_search_and_replace.py "BOX-(\\d+)" "BIN-\\1" --fields bin_number --regex
""",
    )

    # Positional search and replace patterns
    parser.add_argument(
        "find_pattern",
        help="Search substring or regular expression pattern to find in target fields.",
    )
    parser.add_argument(
        "replace_pattern",
        help="Replacement string to substitute in target fields.",
    )

    # Core required parameters
    parser.add_argument(
        "-f",
        "--fields",
        nargs="+",
        required=True,
        help="Target part field(s) to search and replace (e.g. description location bin_number).",
    )
    parser.add_argument(
        "-d",
        "--dry",
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Dry run: scan and report matches without applying database updates in Binner.",
    )

    # Matching options
    parser.add_argument(
        "-r",
        "--regex",
        action="store_true",
        default=False,
        help="Treat find_pattern as a regular expression.",
    )
    parser.add_argument(
        "-i",
        "--ignore-case",
        action="store_true",
        default=False,
        help="Perform case-insensitive matching.",
    )

    # Filtering & config options
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default=None,
        help="Path to binnermcp_config.json configuration file.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose debug logging output.",
    )

    args = parser.parse_args(argv)

    # Normalize fields (support comma-delimited or space-separated)
    normalized_fields: List[str] = []
    for item in args.fields:
        for sub_item in item.split(","):
            cleaned = sub_item.strip().lower()
            if cleaned:
                normalized_fields.append(cleaned)

    # Validate specified fields against known part model attributes
    unknown_fields = [f for f in normalized_fields if f not in KNOWN_PART_FIELDS]
    if unknown_fields:
        parser.error(
            f"Unrecognized part field(s): {', '.join(unknown_fields)}. "
            f"Valid fields are: {', '.join(sorted(KNOWN_PART_FIELDS))}"
        )
    args.fields = normalized_fields

    return args


def setup_client(config_path: Optional[str] = None) -> BinnerAPIProxy:
    """Initialize, ping, and authenticate Binner instance using BinnerAPIProxy."""
    config: BinnerConfig = load_config(config_path=config_path)
    client = BinnerAPIProxy(
        base_url=config.base_url,
        username=config.username,
        password=config.password,
    )
    # Connectivity pre-flight check
    try:
        is_alive = client.ping()
    except (requests.RequestException, BinnerError, ConnectionError, OSError) as exc:
        raise BinnerConnectionError(
            f"Unable to reach Binner instance at {config.base_url}: {exc}"
        ) from exc

    if not is_alive:
        raise BinnerConnectionError(
            f"Binner instance at {config.base_url} is offline or returned unhealthy status."
        )

    # Authenticate immediately after ping
    try:
        client.login()
        logger.info(
            "Successfully authenticated with Binner at %s as '%s'.",
            config.base_url,
            config.username,
        )
    except BinnerAuthError as exc:
        logger.error(
            "Authentication failed for user '%s' at %s: %s",
            config.username,
            config.base_url,
            exc,
        )
        raise
    except (
        requests.RequestException,
        BinnerConnectionError,
        ConnectionError,
        OSError,
    ) as exc:
        logger.error(
            "Connection dropped during authentication with %s: %s", config.base_url, exc
        )
        raise BinnerConnectionError(
            f"Connection failed during authentication with {config.base_url}: {exc}"
        ) from exc
    except (BinnerError, ValueError, KeyError) as exc:
        logger.error("Unexpected error during login to %s: %s", config.base_url, exc)
        raise BinnerAuthError(f"Login failed: {exc}") from exc

    return client


def replace_in_value(
    value: Any,
    find_pattern: str,
    replace_pattern: str,
    is_regex: bool,
    ignore_case: bool,
    field_name: str,
) -> Tuple[Any, bool]:
    """
    Apply search and replace to a single attribute value.
    Returns (new_value, was_modified).
    """
    if value is None:
        return None, False

    # Handle string field
    if isinstance(value, str):
        flags = re.IGNORECASE if ignore_case else 0
        if is_regex:
            new_val, count = re.subn(find_pattern, replace_pattern, value, flags=flags)
        else:
            if ignore_case:
                pattern = re.compile(re.escape(find_pattern), flags=re.IGNORECASE)
                new_val, count = pattern.subn(replace_pattern, value)
            else:
                count = value.count(find_pattern)
                new_val = value.replace(find_pattern, replace_pattern)

        if count > 0 and new_val != value:
            # Enforce bin number uppercase invariant
            if field_name in ("bin_number", "bin_number2"):
                new_val = new_val.upper()
            return new_val, True
        return value, False

    # Handle list of strings (e.g. keywords)
    if isinstance(value, list):
        modified = False
        new_list = []
        for elem in value:
            if isinstance(elem, str):
                new_elem, elem_mod = replace_in_value(
                    elem,
                    find_pattern,
                    replace_pattern,
                    is_regex,
                    ignore_case,
                    field_name,
                )
                new_list.append(new_elem)
                if elem_mod:
                    modified = True
            else:
                new_list.append(elem)
        return new_list, modified

    return value, False


def run_search_and_replace(
    client: BinnerAPIProxy,
    fields: List[str],
    find_pattern: str,
    replace_pattern: str,
    dry_run: bool = False,
    is_regex: bool = False,
    ignore_case: bool = False,
) -> int:
    """Execute search and replace over Binner inventory parts."""
    # Validate regex compilation early if in regex mode.
    if is_regex:
        try:
            flags = re.IGNORECASE if ignore_case else 0
            re.compile(find_pattern, flags=flags)
        except re.error as err:
            logger.error("Invalid regular expression '%s': %s", find_pattern, err)
            return 1

    logger.debug(
        "Scanning parts (fields: %s, pattern: '%s' -> '%s', mode: %s)...",
        ", ".join(fields),
        find_pattern,
        replace_pattern,
        "DRY RUN" if dry_run else "APPLY",
    )

    # Retrieve parts from Binner
    response = client.list_parts(results=-1)
    parts = response.items
    part_count = len(parts)
    assert(response.total_items == part_count)

    parts_matched = 0
    fields_modified_count = 0
    update_failures = 0

    for part in parts:
        part_modified = False
        modifications: Dict[str, Tuple[Any, Any]] = {}
        updated_data = part.model_dump(by_alias=False, exclude_none=True)

        for field in fields:
            current_val = getattr(part, field, None)
            new_val, was_modified = replace_in_value(
                current_val, find_pattern, replace_pattern, is_regex, ignore_case, field
            )
            if was_modified:
                part_modified = True
                modifications[field] = (current_val, new_val)
                updated_data[field] = new_val

        if part_modified:
            parts_matched += 1
            fields_modified_count += len(modifications)

            logger.info("Match in Part #%s (ID: %s):", part.part_number, part.part_id)
            for f_name, (old_v, new_v) in modifications.items():
                logger.info("  [%s]", f_name)
                logger.info("    - %s", old_v)
                logger.info("    + %s", new_v)

            if not dry_run:
                try:
                    # Ensure foreign key IDs are strings for UpdatePartRequest
                    if (
                        "part_type_id" in updated_data
                        and updated_data["part_type_id"] is not None
                    ):
                        updated_data["part_type_id"] = str(updated_data["part_type_id"])
                    if (
                        "mounting_type_id" in updated_data
                        and updated_data["mounting_type_id"] is not None
                    ):
                        updated_data["mounting_type_id"] = str(
                            updated_data["mounting_type_id"]
                        )

                    req = UpdatePartRequest.model_validate(updated_data)
                    client.update_part(req)
                    logger.info("  -> Updated successfully.")
                except (BinnerAPIError, ValueError) as err:
                    update_failures += 1
                    logger.error(
                        "Failed to update part #%s (ID: %s): %s",
                        part.part_number,
                        part.part_id,
                        err,
                    )

    # Print summary report
    logger.info("=" * 50)
    logger.info("Search & Replace Summary:")
    logger.info("  Total parts inspected:  %d", part_count)
    logger.info("  Parts matched:          %d", parts_matched)
    logger.info("  Fields modified:        %d", fields_modified_count)
    if not dry_run:
        logger.info("  Update failures:        %d", update_failures)
    logger.info(
        "  Execution mode:         %s",
        "DRY RUN (no database changes)" if dry_run else "APPLIED",
    )
    logger.info("=" * 50)

    return 1 if update_failures > 0 else 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entrypoint."""
    args = parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        client = setup_client(config_path=args.config)
    except (BinnerError, FileNotFoundError, ValueError, OSError) as err:
        logger.error("Initialization error: %s", err)
        return 1

    return run_search_and_replace(
        client=client,
        fields=args.fields,
        find_pattern=args.find_pattern,
        replace_pattern=args.replace_pattern,
        dry_run=args.dry_run,
        is_regex=args.regex,
        ignore_case=args.ignore_case
    )


if __name__ == "__main__":
    sys.exit(main())
