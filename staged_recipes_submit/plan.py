"""Turn validated recipes into submission units.

A unit is the atomic thing the action creates: one branch, one commit set, one
pull request. Branch names are derived from package names only, so rerunning a
submission targets the same branch instead of creating a second one.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from .errors import ConfigurationError
from .models import Recipe, SubmissionMode, SubmissionUnit
from .paths import branch_component

MAX_INLINE_NAMES = 3
CLAIM = (
    "Submitted with the staged-recipes submit action. Review, CI, merging and any "
    "package publication stay with conda-forge maintainers and the normal staged-recipes process."
)


def build_plan(
    recipes: Sequence[Recipe],
    *,
    mode: SubmissionMode = SubmissionMode.SINGLE,
    title: str | None = None,
    body: str | None = None,
    branch_prefix: str = "submit",
) -> list[SubmissionUnit]:
    """Return the units to create, in a deterministic order."""
    if not recipes:
        raise ConfigurationError("There is nothing to submit.", hint="pass at least one recipe")
    ordered = tuple(sorted(recipes, key=lambda recipe: recipe.name))
    groups = [ordered] if mode is SubmissionMode.SINGLE else [(recipe,) for recipe in ordered]
    return [
        SubmissionUnit(
            branch=branch_name(group, prefix=branch_prefix),
            title=title or default_title(group, mode=mode),
            body=body or default_body(group),
            recipes=tuple(group),
        )
        for group in groups
    ]


def branch_name(recipes: Sequence[Recipe], *, prefix: str = "submit") -> str:
    names = [recipe.name for recipe in recipes]
    prefix = branch_component(prefix, limit=24)
    if len(names) == 1:
        return f"{prefix}/{branch_component(names[0])}"
    if len(names) <= MAX_INLINE_NAMES:
        return f"{prefix}/{branch_component('-'.join(names))}"
    digest = hashlib.sha256("\n".join(sorted(names)).encode()).hexdigest()[:8]
    return f"{prefix}/batch-{len(names)}-{digest}"


def default_title(recipes: Sequence[Recipe], *, mode: SubmissionMode) -> str:
    names = ", ".join(recipe.name for recipe in recipes)
    if len(recipes) == 1:
        return f"Add recipe for {names}"
    if mode is SubmissionMode.PER_RECIPE:  # pragma: no cover - kept for callers that pre-split
        return f"Add recipe for {names}"
    return f"Add recipes for {names}"


def default_body(recipes: Sequence[Recipe]) -> str:
    lines = ["Adds the following conda recipes to staged-recipes:", ""]
    for recipe in recipes:
        version = f" {recipe.version}" if recipe.version else ""
        lines.append(f"- `{recipe.name}`{version}")
    lines += [
        "",
        "### Checklist",
        "",
        "- [x] Recipes were validated locally before submission",
        "- [x] No existing package was overwritten",
        f"- [ ] Maintainers: {CLAIM}",
    ]
    return "\n".join(lines)


def commit_message(unit: SubmissionUnit) -> str:
    names = ", ".join(unit.package_names)
    subject = (
        f"feat: add recipe for {names}"
        if len(unit.recipes) == 1
        else f"feat: add recipes for {names}"
    )
    return f"{subject}\n\n{unit.body}\n"
