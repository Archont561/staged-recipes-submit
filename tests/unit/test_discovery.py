"""Recipe discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from staged_recipes_submit.discovery import discover_recipes
from staged_recipes_submit.errors import RecipeDiscoveryError
from support import write_recipe


def test_discovers_a_recipe_directory(recipe_factory) -> None:
    recipe = recipe_factory("hello-world")
    (discovered,) = discover_recipes([recipe])
    assert discovered.name == "hello-world"
    assert discovered.recipe_file == Path("recipe.yaml")
    assert discovered.relative_files() == ("recipe.yaml",)
    assert discovered.label == "hello-world-1.0.0"


def test_discovers_a_recipe_file(recipe_factory) -> None:
    recipe = recipe_factory("hello-world")
    (discovered,) = discover_recipes([recipe / "recipe.yaml"])
    assert discovered.root == recipe.resolve()


def test_discovers_several_recipes_under_a_parent(recipe_factory, recipes_dir: Path) -> None:
    recipe_factory("alpha")
    recipe_factory("beta")
    names = [recipe.name for recipe in discover_recipes([recipes_dir])]
    assert names == ["alpha", "beta"]


def test_supporting_files_are_collected(recipe_factory) -> None:
    recipe = recipe_factory("alpha")
    (recipe / "patches").mkdir()
    (recipe / "patches" / "fix.patch").write_text("--- a\n+++ b\n")
    (discovered,) = discover_recipes([recipe])
    assert "patches/fix.patch" in discovered.relative_files()


def test_junk_directories_are_skipped(recipe_factory, recipes_dir: Path) -> None:
    recipe_factory("alpha")
    junk = recipes_dir / "__pycache__"
    junk.mkdir()
    (junk / "recipe.yaml").write_text("package: {name: junk}")
    assert [recipe.name for recipe in discover_recipes([recipes_dir])] == ["alpha"]


def test_duplicate_sources_are_collapsed(recipe_factory) -> None:
    recipe = recipe_factory("alpha")
    assert len(discover_recipes([recipe, recipe, recipe / "recipe.yaml"])) == 1


def test_both_recipe_files_is_an_error(recipe_factory) -> None:
    recipe = recipe_factory("alpha")
    (recipe / "meta.yaml").write_text("package:\n  name: alpha\n")
    with pytest.raises(RecipeDiscoveryError, match=r"both recipe\.yaml and meta\.yaml"):
        discover_recipes([recipe])


def test_missing_path_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RecipeDiscoveryError, match="does not exist"):
        discover_recipes([tmp_path / "nope"])


def test_non_recipe_file_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "build.sh"
    path.write_text("echo hi\n")
    with pytest.raises(RecipeDiscoveryError, match="not a conda recipe file"):
        discover_recipes([path])


def test_empty_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RecipeDiscoveryError, match=r"No recipe\.yaml or meta\.yaml"):
        discover_recipes([tmp_path])


def test_no_sources_is_an_error() -> None:
    with pytest.raises(RecipeDiscoveryError, match="No recipe paths"):
        discover_recipes([])


def test_name_falls_back_to_the_directory_name(tmp_path: Path) -> None:
    recipe = tmp_path / "fallback-name"
    recipe.mkdir()
    (recipe / "recipe.yaml").write_text("build:\n  number: 0\n")
    (discovered,) = discover_recipes([recipe])
    assert discovered.name == "fallback-name"
    assert discovered.version is None


def test_base_directory_restricts_inputs(recipe_factory, tmp_path: Path) -> None:
    recipe = recipe_factory("alpha")
    with pytest.raises(Exception, match="outside the allowed directory"):
        discover_recipes([recipe], base=tmp_path / "somewhere-else")


def test_recipes_are_sorted(recipe_factory, recipes_dir: Path) -> None:
    for name in ("zeta", "alpha", "middle"):
        write_recipe(recipes_dir, name)
    assert [r.name for r in discover_recipes([recipes_dir])] == ["alpha", "middle", "zeta"]
