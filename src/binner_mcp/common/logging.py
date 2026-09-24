"""Protocol-safe logging, custom TRACE level, and sensitive payload sanitization."""

import logging
import os
import sys
from typing import Any, Optional

TRACE_LEVEL_NUM = 5


def setup_trace_level() -> None:
    """Register custom TRACE level (below DEBUG) with Python logging if not already set."""
    if logging.getLevelName(TRACE_LEVEL_NUM) != "TRACE":
        logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")

    def trace(self: logging.Logger, message: str, *args: Any, **kwargs: Any) -> None:
        """Log a message with severity 'TRACE'."""
        if self.isEnabledFor(TRACE_LEVEL_NUM):
            self._log(TRACE_LEVEL_NUM, message, args, **kwargs)

    logging.Logger.trace = trace  # type: ignore[attr-defined]


# Ensure TRACE level is available upon module import
setup_trace_level()


def log_trace(logger: logging.Logger, msg: str, *args: Any, **kwargs: Any) -> None:
    """Helper to emit TRACE log messages if the logger has TRACE enabled."""
    if logger.isEnabledFor(TRACE_LEVEL_NUM):
        logger._log(TRACE_LEVEL_NUM, msg, args, **kwargs)


def sanitize_for_trace(data: Any) -> Any:
    """
    Mask sensitive tokens, passwords, or API keys from trace logs.

    Recursively cleans dicts and lists.
    """
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            lower_k = str(k).lower()
            if any(secret in lower_k for secret in ("password", "token", "authorization", "secret", "apikey", "api-key")):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_for_trace(v)
        return sanitized
    if isinstance(data, list):
        return [sanitize_for_trace(item) for item in data]
    return data


def setup_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """
    Configure lean, protocol-safe logging.

    All terminal output is strictly directed to sys.stderr to avoid polluting
    sys.stdout, which is reserved for MCP JSON-RPC stdio transport.
    Optionally attaches a FileHandler if log_file is specified.

    Log Levels:
      - INFO:    App lifecycle events (server startup, shutdown, ready state)
      - DEBUG:   Token refresh operations, state changes, loaded config path
      - WARNING: Non-critical fallbacks, ignored or unmapped fields
      - ERROR:   Unexpected API responses, network disconnects, auth failures
      - TRACE:   Every raw HTTP request/response call and payload
    """
    setup_trace_level()

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

    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setFormatter(logging.Formatter(fmt=log_format, datefmt=date_format))

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.handlers.clear()
    root_logger.addHandler(stderr_handler)

    target_log_file = log_file or os.environ.get("BINNER_LOG_FILE")
    if target_log_file:
        from pathlib import Path
        log_path = Path(target_log_file).expanduser().resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(fmt=log_format, datefmt=date_format))
        root_logger.addHandler(file_handler)

    logger = logging.getLogger("binner_mcp")
    return logger
