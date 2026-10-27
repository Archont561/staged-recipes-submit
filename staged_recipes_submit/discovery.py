"""Find recipes and the files that support them.

A recipe is a directory holding exactly one of ``recipe.yaml`` or ``meta.yaml``
plus any patches, build scripts or test files it needs. Discovery accepts files
or directories, ignores junk, and never follows a path outside the recipe.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

from .errors import RecipeDiscoveryError
from .models import Recipe
from .parsing import RECIPE_FILENAMES, parse_recipe
from .paths import guard_user_path, is_junk, relative_files

MAX_SEARCH_DEPTH = 4


def discover_recipes(sources: Iterable[str | Path], *, base: Path | None = None) -> list[Recipe]:
    """Resolve every recipe reachable from ``sources``.

    Passing the same directory twice is not an error: results are de-duplicated
    by resolved directory so that reruns stay idempotent.
    """
    resolved: list[Path] = [
        guard_user_path(source, base=base)
        if base is not None
        else Path(source).expanduser().resolve()
        for source in sources
    ]
    sources = resolved
    if not sources:
        raise RecipeDiscoveryError(
            "No recipe paths were provided.",
            hint="pass at least one 'recipe.yaml' or 'meta.yaml' path",
        )
    found: dict[Path, Path] = {}
    for source in sources:
        if not source.exists():
            raise RecipeDiscoveryError(
                f"Recipe path does not exist: {source}",
                hint="check the 'recipes' input; paths are relative to the workflow workspace",
            )
        for root, recipe_file in _recipe_roots(source, depth=0):
            found.setdefault(root.resolve(), recipe_file)
    recipes = [_build(root, recipe_file) for root, recipe_file in found.items()]
    if not recipes:
        raise RecipeDiscoveryError(
            "No recipe.yaml or meta.yaml was found.",
            hint="point the 'recipes' input at a recipe directory or at a parent directory",
        )
    return sorted(recipes, key=lambda recipe: (recipe.name, str(recipe.root)))


def _recipe_roots(path: Path, *, depth: int) -> Iterator[tuple[Path, Path]]:
    if path.is_file():
        if path.name not in RECIPE_FILENAMES:
            raise RecipeDiscoveryError(
                f"{path.name} is not a conda recipe file.",
                hint="recipes are named recipe.yaml (v1) or meta.yaml (v0)",
            )
        yield path.parent, path
        return
    if not path.is_dir():
        raise RecipeDiscoveryError(f"{path} is neither a file nor a directory.")
    candidates = [path / name for name in RECIPE_FILENAMES if (path / name).is_file()]
    if len(candidates) > 1:
        raise RecipeDiscoveryError(
            f"{path} contains both recipe.yaml and meta.yaml.",
            hint="keep exactly one; staged-recipes accepts one recipe per directory",
        )
    if candidates:
        yield path, candidates[0]
        return
    if depth >= MAX_SEARCH_DEPTH:
        return
    for child in sorted(path.iterdir()):
        if not child.is_dir() or is_junk(child):
            continue
        yield from _recipe_roots(child, depth=depth + 1)


def _build(root: Path, recipe_file: Path) -> Recipe:
    metadata = parse_recipe(recipe_file)
    return Recipe(
        name=metadata.name or root.name,
        version=metadata.version,
        root=root.resolve(),
        recipe_file=recipe_file.relative_to(root),
        files=tuple(relative_files(root)),
        metadata=metadata,
    )
