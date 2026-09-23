"""Configuration loader for Binner MCP Server."""

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("binner_mcp.config")

CONFIG_FILENAME = "binnermcp_config.json"


class BinnerConfig(BaseModel):
    """Configuration settings for Binner MCP Server and API Proxy."""

    base_url: str = Field(default="http://localhost:8090", description="Base URL of Binner instance")
    username: str = Field(default="admin", description="Binner username")
    password: str = Field(default="admin", description="Binner password")
    log_level: str = Field(default="INFO", description="Logging level")
    transport: str = Field(default="stdio", description="MCP transport mode ('stdio', 'http', or 'sse')")
    host: str = Field(default="127.0.0.1", description="Host address for HTTP/SSE transport")
    port: int = Field(default=8000, description="Port for HTTP/SSE transport")
    category_delimiter: str = Field(
        default="::",
        description="Delimiter for hierarchical category paths (e.g. '::' or '#')",
    )


def find_config_file(explicit_path: Optional[str] = None) -> Optional[Path]:
    """
    Locate binnermcp_config.json in prioritized order:
    1. Explicit path from CLI argument (raises FileNotFoundError if missing)
    2. Path from BINNER_MCP_CONFIG environment variable (raises FileNotFoundError if missing)
    3. Current working directory
    4. Script / project root directory
    5. Package directory
    6. User configuration path (~/.config/binnermcp/binnermcp_config.json)
    7. System-wide configuration path (/etc/binnermcp/binnermcp_config.json)
    """
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(f"Configuration file not found: {explicit_path}")

    if env_path := os.environ.get("BINNER_MCP_CONFIG"):
        path = Path(env_path).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(
            f"Configuration file specified in BINNER_MCP_CONFIG not found: {env_path}"
        )

    search_paths = [
        Path.cwd() / CONFIG_FILENAME,
        Path(__file__).resolve().parent.parent.parent / CONFIG_FILENAME,
        Path(__file__).resolve().parent / CONFIG_FILENAME,
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "binnermcp" / CONFIG_FILENAME,
        Path("/etc/binnermcp") / CONFIG_FILENAME,
    ]

    for candidate in search_paths:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError as e:
            logger.debug(f"Skipping inaccessible candidate path {candidate}: {e}")
            continue

    return None


def load_config(
    config_path: Optional[str] = None,
    log_level_override: Optional[str] = None,
    transport_override: Optional[str] = None,
    host_override: Optional[str] = None,
    port_override: Optional[int] = None,
    category_delimiter_override: Optional[str] = None,
) -> BinnerConfig:
    """
    Load configuration with strict precedence:
    1. Built-in defaults
    2. binnermcp_config.json (if found)
    3. Environment variables (BINNER_BASE_URL, BINNER_USERNAME, BINNER_PASSWORD, BINNER_LOG_LEVEL,
       BINNER_MCP_TRANSPORT, BINNER_MCP_HOST, BINNER_MCP_PORT, BINNER_CATEGORY_DELIMITER)
    4. Explicit overrides (e.g. CLI arguments)
    """
    config_data: dict[str, Any] = {}

    file_path = find_config_file(config_path)
    if file_path:
        logger.debug(f"Loading configuration from {file_path}")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except json.JSONDecodeError as jde:
            raise ValueError(f"Malformed JSON in configuration file {file_path}: {jde}") from jde
        except OSError as oe:
            raise OSError(f"Unable to read configuration file {file_path}: {oe}") from oe
    else:
        logger.debug(f"No {CONFIG_FILENAME} found; relying on environment variables and defaults.")

    if env_base_url := os.environ.get("BINNER_BASE_URL"):
        config_data["base_url"] = env_base_url
    if env_user := os.environ.get("BINNER_USERNAME"):
        config_data["username"] = env_user
    if env_pass := os.environ.get("BINNER_PASSWORD"):
        config_data["password"] = env_pass
    if env_log := os.environ.get("BINNER_LOG_LEVEL"):
        config_data["log_level"] = env_log
    if env_transport := os.environ.get("BINNER_MCP_TRANSPORT"):
        config_data["transport"] = env_transport
    if env_host := os.environ.get("BINNER_MCP_HOST"):
        config_data["host"] = env_host
    if env_delim := os.environ.get("BINNER_CATEGORY_DELIMITER"):
        config_data["category_delimiter"] = env_delim
    if env_port := os.environ.get("BINNER_MCP_PORT"):
        try:
            config_data["port"] = int(env_port)
        except ValueError as ve:
            raise ValueError(f"Invalid integer for BINNER_MCP_PORT '{env_port}': {ve}") from ve

    if log_level_override:
        config_data["log_level"] = log_level_override
    if transport_override:
        config_data["transport"] = transport_override
    if host_override:
        config_data["host"] = host_override
    if port_override is not None:
        config_data["port"] = port_override
    if category_delimiter_override is not None:
        config_data["category_delimiter"] = category_delimiter_override

    if "log_level" in config_data and isinstance(config_data["log_level"], str):
        config_data["log_level"] = config_data["log_level"].upper()

    if "transport" in config_data and isinstance(config_data["transport"], str):
        config_data["transport"] = config_data["transport"].lower()

    if "base_url" in config_data and isinstance(config_data["base_url"], str):
        config_data["base_url"] = config_data["base_url"].rstrip("/")

    return BinnerConfig(**config_data)
