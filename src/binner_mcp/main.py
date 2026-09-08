"""Main entry point for the Binner MCP Server."""

import argparse
import logging
import os
import sys
from typing import Optional

from binner_mcp.config import BinnerConfig, load_config

# Register custom TRACE logging level (below DEBUG) for raw API calls and payloads
TRACE_LEVEL_NUM = 5
logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")


def trace(self: logging.Logger, message: str, *args, **kwargs) -> None:
    """Log a message with severity 'TRACE'."""
    if self.isEnabledFor(TRACE_LEVEL_NUM):
        self._log(TRACE_LEVEL_NUM, message, args, **kwargs)


logging.Logger.trace = trace  # type: ignore[attr-defined]


def setup_logging(level: Optional[str] = None) -> logging.Logger:
    """
    Configure lean, protocol-safe logging.

    All output is strictly directed to sys.stderr to avoid polluting
    sys.stdout, which is reserved for MCP JSON-RPC stdio transport.

    Log Levels:
      - INFO:    App lifecycle events (server startup, shutdown, ready state)
      - DEBUG:   Token refresh operations, state changes, loaded config path
      - WARNING: Non-critical fallbacks, ignored or unmapped fields
      - ERROR:   Unexpected API responses, network disconnects, auth failures
      - TRACE:   Every raw HTTP request/response call and payload
    """
    log_level_name = (
        level
        or os.environ.get("BINNER_LOG_LEVEL")
        or "INFO"
    ).upper()

    if log_level_name == "TRACE":
        numeric_level = TRACE_LEVEL_NUM
    else:
        numeric_level = getattr(logging, log_level_name, logging.INFO)

    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(fmt=log_format, datefmt=date_format))

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    logger = logging.getLogger("binner_mcp")
    return logger


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
