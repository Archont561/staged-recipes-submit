"""Tolerant conda-recipe parsing.

Never executes a recipe, never runs conda-build: this module only turns a
``recipe.yaml``/``meta.yaml`` file into metadata that the rest of the package
can reason about. Parsing failures are *returned*, not raised, so a single run
can report every problem at once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

RECIPE_FILENAMES: tuple[str, ...] = ("recipe.yaml", "meta.yaml")
_TEMPLATE = re.compile(r"\$\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")


@dataclass(frozen=True, slots=True)
class RecipeMetadata:
    """What we could read out of a recipe file."""

    name: str | None = None
    version: str | None = None
    document: dict[str, Any] | None = None
    error: str | None = None


def parse_recipe(path: Path) -> RecipeMetadata:
    """Read one recipe file without raising on bad input."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return RecipeMetadata(error=f"{path.name} is not valid UTF-8")
    except OSError as error:
        return RecipeMetadata(error=f"{path.name} cannot be read: {error.strerror}")
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        first_line = str(error).splitlines()[0]
        return RecipeMetadata(error=f"{path.name} is not valid YAML: {first_line}")
    if document is None:
        return RecipeMetadata(error=f"{path.name} is empty")
    if not isinstance(document, dict):
        return RecipeMetadata(error=f"{path.name} must contain a mapping at the top level")
    context = document.get("context")
    context = context if isinstance(context, dict) else {}
    package = document.get("package")
    if not isinstance(package, dict):
        return RecipeMetadata(document=document, error=f"{path.name} has no 'package' section")
    name = _string(package.get("name"))
    version = _string(package.get("version"))
    return RecipeMetadata(
        name=_resolve(name, context) or None,
        version=_resolve(version, context) or None,
        document=document,
    )


def _string(value: Any) -> str:
    """Coerce a YAML scalar to text; unquoted numbers and booleans are common."""
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int | float):
        return str(value)
    return value.strip() if isinstance(value, str) else ""


def _resolve(value: str, context: dict[str, Any]) -> str:
    """Expand ``${{ version }}``-style templates against the recipe context."""

    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        replacement = context.get(key)
        return str(replacement) if replacement is not None else match.group(0)

    return _TEMPLATE.sub(substitute, value)
