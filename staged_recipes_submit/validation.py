"""Structural validation of recipes before anything touches the network.

These checks are deliberately cheap and static: they catch the mistakes that
waste a maintainer's review time without pretending to replace conda-forge CI.
"""

from __future__ import annotations

from collections.abc import Iterable

from .errors import PathSafetyError, RecipeValidationError
from .models import Issue, Recipe, Severity
from .parsing import RECIPE_FILENAMES
from .paths import validate_package_name

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_RECIPE_BYTES = 10 * 1024 * 1024


def validate_recipe(
    recipe: Recipe,
    *,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_recipe_bytes: int = MAX_RECIPE_BYTES,
) -> list[Issue]:
    """Return every finding for one recipe; an empty list means it is clean."""
    issues: list[Issue] = []
    relative = recipe.recipe_file.as_posix()
    if recipe.recipe_file.name not in RECIPE_FILENAMES:
        issues.append(
            Issue(
                "VAL001",
                f"{relative} is not a recognised recipe filename.",
                path=relative,
                hint="use recipe.yaml (v1) or meta.yaml (v0)",
            )
        )
    metadata = recipe.metadata
    if metadata.error:
        issues.append(
            Issue("VAL002", metadata.error, path=relative, hint="fix the YAML and run again")
        )
    if metadata.document is None:
        return issues
    if metadata.name is None:
        issues.append(
            Issue(
                "VAL003",
                "The recipe does not declare a package name.",
                path=relative,
                hint="add a 'package:' section with a 'name:' field",
            )
        )
    else:
        try:
            validate_package_name(metadata.name)
        except PathSafetyError as error:
            issues.append(Issue("VAL004", str(error), path=relative, hint=error.hint))
        if metadata.name != recipe.root.name:
            issues.append(
                Issue(
                    "VAL005",
                    f"Recipe directory is {recipe.root.name!r} but the package is "
                    f"{metadata.name!r}.",
                    severity=Severity.WARNING,
                    path=relative,
                    hint=f"the pull request will create recipes/{metadata.name}/",
                )
            )
    if metadata.version is None:
        issues.append(
            Issue(
                "VAL006",
                "The recipe does not declare a version.",
                severity=Severity.WARNING,
                path=relative,
                hint="a missing version usually breaks the feedstock bot later",
            )
        )
    if "about" not in metadata.document:
        issues.append(
            Issue(
                "VAL007",
                "The recipe has no 'about' section.",
                severity=Severity.WARNING,
                path=relative,
                hint="conda-forge expects summary, license and home metadata",
            )
        )
    if recipe.recipe_file.name == "meta.yaml" and "source" not in metadata.document:
        issues.append(
            Issue(
                "VAL008",
                "The v0 recipe has no 'source' section.",
                severity=Severity.WARNING,
                path=relative,
                hint="add a source url or path, or explain why the package has none",
            )
        )
    for relative_file in recipe.files:
        path = recipe.path_to(relative_file)
        size = path.stat().st_size
        if size > max_file_bytes:
            issues.append(
                Issue(
                    "VAL010",
                    f"{relative_file.as_posix()} is {size} bytes, above the "
                    f"{max_file_bytes} byte per-file limit.",
                    path=relative_file.as_posix(),
                    hint="commit sources as a url in the recipe instead of vendoring large files",
                )
            )
    total = recipe.total_bytes
    if total > max_recipe_bytes:
        issues.append(
            Issue(
                "VAL011",
                f"The recipe totals {total} bytes, above the "
                f"{max_recipe_bytes} byte per-recipe limit.",
                path=relative,
                hint="keep only the files the build actually needs",
            )
        )
    return issues


def validate_recipes(
    recipes: Iterable[Recipe],
    *,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_recipe_bytes: int = MAX_RECIPE_BYTES,
) -> tuple[list[Issue], list[Recipe]]:
    """Validate a batch and return ``(issues, valid_recipes)``."""
    issues: list[Issue] = []
    valid: list[Recipe] = []
    for recipe in recipes:
        findings = validate_recipe(
            recipe, max_file_bytes=max_file_bytes, max_recipe_bytes=max_recipe_bytes
        )
        issues.extend(findings)
        if not any(finding.severity is Severity.ERROR for finding in findings):
            valid.append(recipe)
    return issues, valid


def raise_for_errors(issues: Iterable[Issue]) -> None:
    """Raise one aggregated, actionable error when any finding is fatal."""
    errors = [issue for issue in issues if issue.severity is Severity.ERROR]
    if errors:
        raise RecipeValidationError(errors)
