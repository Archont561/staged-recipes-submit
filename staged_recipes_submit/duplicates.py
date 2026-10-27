"""Duplicate detection.

Two kinds of duplicate matter: the same package twice in one invocation, and a
package that already exists in the target checkout (already a feedstock, or
already submitted by another pull request).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .models import Issue, Recipe


def detect_duplicates(
    recipes: Iterable[Recipe], *, staged_recipes_root: Path | None = None
) -> list[Issue]:
    """Report packages that must not be submitted again."""
    recipes = list(recipes)
    issues: list[Issue] = []
    seen: dict[str, Recipe] = {}
    for recipe in recipes:
        key = recipe.name.casefold()
        previous = seen.get(key)
        if previous is None:
            seen[key] = recipe
            continue
        issues.append(
            Issue(
                "DUP001",
                f"Package {recipe.name!r} appears twice in this submission "
                f"({previous.root} and {recipe.root}).",
                path=str(recipe.root),
                hint="remove one of the duplicate recipe paths",
            )
        )
    if staged_recipes_root is None or not staged_recipes_root.is_dir():
        return issues
    for recipe in recipes:
        existing = staged_recipes_root / recipe.name
        if existing.is_dir():
            issues.append(
                Issue(
                    "DUP002",
                    f"Package {recipe.name!r} already exists at {existing}.",
                    path=str(existing),
                    hint="update the existing feedstock instead of submitting a new recipe",
                )
            )
    return issues
