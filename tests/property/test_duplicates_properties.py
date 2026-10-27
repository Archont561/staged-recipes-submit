"""Property-based tests for duplicate detection."""

from __future__ import annotations

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from staged_recipes_submit.discovery import discover_recipes
from staged_recipes_submit.duplicates import detect_duplicates
from support import fresh_dir, write_recipe

NAMES = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8)


@given(names=st.lists(NAMES, min_size=1, max_size=5, unique=True))
def test_unique_batches_have_no_duplicates(tmp_path: Path, names: list[str]) -> None:
    root = fresh_dir(tmp_path)
    for name in names:
        write_recipe(root, name)
    assert detect_duplicates(discover_recipes([root])) == []


@given(names=st.lists(NAMES, min_size=2, max_size=4))
def test_each_collision_is_reported_once(tmp_path: Path, names: list[str]) -> None:
    root = fresh_dir(tmp_path)
    directories = [root / f"copy-{index}" for index in range(len(names))]
    for directory, name in zip(directories, names, strict=True):
        directory.mkdir()
        (directory / "recipe.yaml").write_text(
            f"package:\n  name: \"{name}\"\n  version: '1.0'\nabout:\n  summary: x\n",
            encoding="utf-8",
        )
    recipes = discover_recipes([root])
    issues = detect_duplicates(recipes)
    assert len(issues) == len(names) - len(set(names))
    assert {issue.code for issue in issues} <= {"DUP001"}


@given(names=st.lists(NAMES, min_size=1, max_size=4, unique=True))
def test_existing_packages_are_each_reported(tmp_path: Path, names: list[str]) -> None:
    root = fresh_dir(tmp_path)
    staged = root / "staged"
    sources = root / "sources"
    for name in names:
        write_recipe(sources, name)
        (staged / name).mkdir(parents=True)
    recipes = discover_recipes([sources])
    issues = detect_duplicates(recipes, staged_recipes_root=staged)
    assert len(issues) == len(names)
    assert all(issue.code == "DUP002" for issue in issues)
