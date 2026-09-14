"""Model Context Protocol server and Python client for local Binner inventory instances."""

__version__ = "0.1.0"

from binner_mcp.config import BinnerConfig, load_config

__all__ = ["__version__", "BinnerConfig", "load_config"]
