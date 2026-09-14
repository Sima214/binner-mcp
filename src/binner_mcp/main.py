"""Main entry point for the Binner MCP Server."""

import argparse
import logging
import os
import sys
from typing import Optional

from binner_mcp.common.logging import TRACE_LEVEL_NUM, setup_logging
from binner_mcp.config import BinnerConfig, load_config


def parse_args(args: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="binner-mcp",
        description="Binner MCP Server and API Client Proxy",
    )
    parser.add_argument(
        "--log-level",
        choices=["TRACE", "DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Set the logging level (overrides BINNER_LOG_LEVEL, default: INFO)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to binnermcp_config.json",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=None,
        help="MCP transport protocol (stdio or sse, default: stdio)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host address for SSE transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port for SSE transport (default: 8000)",
    )
    return parser.parse_args(args)


def main() -> int:
    """Main application entry point."""
    args = parse_args()
    config: BinnerConfig = load_config(
        config_path=args.config,
        log_level_override=args.log_level,
        transport_override=args.transport,
        host_override=args.host,
        port_override=args.port,
    )
    logger = setup_logging(level=config.log_level)
    logger.info("Binner MCP Server initialized.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
