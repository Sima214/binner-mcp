"""Sphinx configuration for binner-mcp documentation."""

from pathlib import Path
import sys

# Ensure src/ is on sys.path for autodoc
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

project = "binner-mcp"
copyright = "2026, Anastasios Symeonidis"
author = "Anastasios Symeonidis"
version = "0.1.0"
release = "0.1.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "myst_parser",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

master_doc = "index"

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "tasklist",
]
myst_heading_anchors = 3

html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 3,
    "collapse_navigation": False,
    "sticky_navigation": True,
}

html_static_path = []
