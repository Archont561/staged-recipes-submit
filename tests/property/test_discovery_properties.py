"""Property-based tests for recipe discovery."""

from __future__ import annotations

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from staged_recipes_submit.discovery import discover_recipes
from support import fresh_dir, write_recipe


def _package_names():
    return st.lists(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8).filter(
            lambda name: name.strip() == name
        ),
        min_size=1,
        max_size=4,
        unique=True,
    )


@given(names=_package_names())
def test_every_recipe_under_a_parent_is_found(tmp_path: Path, names: list[str]) -> None:
    root = fresh_dir(tmp_path)
    for name in names:
        write_recipe(root, name)
    discovered = discover_recipes([root])
    assert sorted(recipe.name for recipe in discovered) == sorted(names)


@given(names=_package_names())
def test_discovery_is_idempotent(tmp_path: Path, names: list[str]) -> None:
    root = fresh_dir(tmp_path)
    for name in names:
        write_recipe(root, name)
    first = discover_recipes([root])
    second = discover_recipes([root, *[recipe.root for recipe in first]])
    assert [recipe.root for recipe in first] == [recipe.root for recipe in second]


@given(names=_package_names())
def test_discovery_is_ordered(tmp_path: Path, names: list[str]) -> None:
    root = fresh_dir(tmp_path)
    for name in names:
        write_recipe(root, name)
    discovered = discover_recipes([root])
    assert [recipe.name for recipe in discovered] == sorted(recipe.name for recipe in discovered)


@given(names=_package_names(), filename=st.sampled_from(["recipe.yaml", "meta.yaml"]))
def test_file_inputs_and_directory_inputs_agree(
    tmp_path: Path, names: list[str], filename: str
) -> None:
    root = fresh_dir(tmp_path)
    directories = [write_recipe(root, name, filename=filename) for name in names]
    from_files = discover_recipes([directory / filename for directory in directories])
    from_directories = discover_recipes(directories)
    assert [recipe.root for recipe in from_files] == [recipe.root for recipe in from_directories]
