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
        choices=["stdio", "http", "sse"],
        default=None,
        help="MCP transport protocol (stdio, http [Streamable HTTP], or sse, default: stdio)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host address for HTTP/SSE transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port for HTTP/SSE transport (default: 8000)",
    )
    parser.add_argument(
        "--category-delimiter",
        type=str,
        default=None,
        help="Delimiter for hierarchical category paths (default: '::')",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Optional path to write log output in addition to sys.stderr",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=None,
        help="Delay in seconds between retry attempts for transient network errors (default: 3.0)",
    )
    parser.add_argument(
        "--retry-count",
        type=int,
        default=None,
        help="Maximum retry attempts for transient network errors (default: 1)",
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
        category_delimiter_override=args.category_delimiter,
        log_file_override=args.log_file,
        retry_delay_override=args.retry_delay,
        retry_count_override=args.retry_count,
    )
    logger = setup_logging(level=config.log_level, log_file=config.log_file)
    logger.info("Starting Binner MCP Server (transport=%s)...", config.transport)

    from binner_mcp.mcp.server import BinnerMCPServer

    server = BinnerMCPServer(config=config)

    if config.transport == "http":
        logger.info("Listening on Streamable HTTP %s:%d...", config.host, config.port)
        server.run_http(host=config.host, port=config.port)
    elif config.transport == "sse":
        logger.info("Listening on legacy SSE %s:%d...", config.host, config.port)
        server.run_sse(host=config.host, port=config.port)
    else:
        logger.info("Listening on Standard I/O (stdio)...")
        server.run_stdio()

    return 0


if __name__ == "__main__":
    sys.exit(main())
