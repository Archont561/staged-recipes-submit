"""Path and name hygiene."""

from __future__ import annotations

from pathlib import Path

import pytest

from staged_recipes_submit.errors import PathSafetyError
from staged_recipes_submit.paths import (
    branch_component,
    destination,
    guard_user_path,
    relative_files,
    safe_relative,
    validate_package_name,
)


@pytest.mark.parametrize("name", ["numpy", "scikit-learn", "foo_bar", "a", "x1.y2", "py-opencv"])
def test_package_names_are_accepted(name: str) -> None:
    assert validate_package_name(name) == name


@pytest.mark.parametrize(
    "name",
    ["", "NumPy", "-numpy", "numpy-", "nu mpy", "nu/mpy", "..", "numpy\n", "a" * 65],
)
def test_package_names_are_rejected(name: str) -> None:
    with pytest.raises(PathSafetyError):
        validate_package_name(name)


def test_guard_user_path_rejects_escapes(tmp_path: Path) -> None:
    inside = tmp_path / "inside"
    inside.mkdir()
    (inside / "recipe.yaml").write_text("package: {name: ok, version: '1'}")

    assert (
        guard_user_path(inside / "recipe.yaml", base=inside) == (inside / "recipe.yaml").resolve()
    )
    with pytest.raises(PathSafetyError, match="outside the allowed directory"):
        guard_user_path(tmp_path / "elsewhere", base=inside)


def test_guard_user_path_rejects_nul_bytes(tmp_path: Path) -> None:
    with pytest.raises(PathSafetyError, match="NUL"):
        guard_user_path("recipe\x00.yaml", base=tmp_path)


@pytest.mark.parametrize("candidate", ["../escape", "recipes/../../escape"])
def test_safe_relative_rejects_parent_traversal(tmp_path: Path, candidate: str) -> None:
    with pytest.raises(PathSafetyError, match="outside"):
        safe_relative(tmp_path, Path(candidate))


def test_safe_relative_returns_posix_path(tmp_path: Path) -> None:
    assert safe_relative(tmp_path, Path("recipes/numpy")) == Path("recipes/numpy")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello World", "hello-world"),
        ("Łódź", "odz"),
        ("a" * 80, "a" * 48),
        ("", "recipes"),
        ("...", "recipes"),
    ],
)
def test_branch_component(text: str, expected: str) -> None:
    assert branch_component(text) == expected


def test_relative_files_skips_junk_and_nested_caches(tmp_path: Path) -> None:
    (tmp_path / "recipe.yaml").write_text("package: {name: pkg}")
    (tmp_path / "patches").mkdir()
    (tmp_path / "patches" / "fix.patch").write_text("--- a\n+++ b\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    (tmp_path / ".DS_Store").write_bytes(b"\x00")

    assert list(relative_files(tmp_path)) == [Path("patches/fix.patch"), Path("recipe.yaml")]


def test_relative_files_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    (recipe / "recipe.yaml").write_text("package: {name: pkg}")
    (recipe / "leak.txt").symlink_to(outside)

    with pytest.raises(PathSafetyError, match="links outside"):
        list(relative_files(recipe))


def test_destination_stays_inside_recipes(tmp_path: Path) -> None:
    assert destination(tmp_path, "numpy") == tmp_path / "recipes" / "numpy"
    with pytest.raises(PathSafetyError):
        destination(tmp_path, "../numpy")
