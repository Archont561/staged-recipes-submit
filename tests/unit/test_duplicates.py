"""Duplicate detection."""

from __future__ import annotations

from pathlib import Path

from staged_recipes_submit.discovery import discover_recipes
from staged_recipes_submit.duplicates import detect_duplicates
from staged_recipes_submit.models import Severity


def test_unique_packages_have_no_duplicates(recipe_factory) -> None:
    recipes = discover_recipes([recipe_factory("alpha"), recipe_factory("beta")])
    assert detect_duplicates(recipes) == []


def test_same_package_twice_is_reported(recipe_factory, recipes_dir: Path) -> None:
    recipe_factory("alpha")
    from support import write_recipe

    second = write_recipe(recipes_dir, "elsewhere")
    (second / "recipe.yaml").write_text(
        "package:\n  name: alpha\n  version: '1.0'\nabout:\n  summary: x\n", encoding="utf-8"
    )
    recipes = discover_recipes([recipes_dir])
    (issue,) = detect_duplicates(recipes)
    assert issue.code == "DUP001"
    assert issue.severity is Severity.ERROR


def test_existing_package_in_the_checkout_is_reported(
    recipe_factory, staged_recipes_checkout
) -> None:
    (staged_recipes_checkout / "recipes" / "alpha").mkdir()
    recipes = discover_recipes([recipe_factory("alpha")])
    (issue,) = detect_duplicates(recipes, staged_recipes_root=staged_recipes_checkout / "recipes")
    assert issue.code == "DUP002"
    assert "already exists" in issue.message


def test_missing_checkout_is_ignored(recipe_factory, tmp_path: Path) -> None:
    recipes = discover_recipes([recipe_factory("alpha")])
    assert detect_duplicates(recipes, staged_recipes_root=tmp_path / "absent") == []
