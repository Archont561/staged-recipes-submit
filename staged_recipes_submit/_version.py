"""The single source of truth for the version string.

``__init__`` re-exports it, ``cli --version`` prints it, and ``pixi run validate`` refuses a
``pyproject.toml``, ``pixi.toml`` or ``config/project.toml`` that disagrees with it.
"""

from __future__ import annotations

__version__ = "0.1.0"
