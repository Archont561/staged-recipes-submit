"""Property-based tests for path and name hygiene."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from staged_recipes_submit.errors import PathSafetyError
from staged_recipes_submit.paths import branch_component, safe_relative, validate_package_name

SAFE_BRANCH = re.compile(r"^[a-z0-9._/-]+$")
SAFE_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")


def _names():
    alphabet = st.sampled_from(list("abcdefghijklmnopqrstuvwxyz0123456789._-"))
    return st.text(alphabet, min_size=1, max_size=20)


@given(_names())
def test_validate_package_name_accepts_exactly_the_safe_alphabet(name: str) -> None:
    if SAFE_NAME.match(name) and len(name) <= 64:
        assert validate_package_name(name) == name
    else:
        with pytest.raises(PathSafetyError):
            validate_package_name(name)


@given(st.text(max_size=40))
def test_branch_components_are_always_usable(text: str) -> None:
    slug = branch_component(text)
    assert slug
    assert SAFE_BRANCH.match(slug)
    assert len(slug) <= 48
    assert slug[0] not in "-._"
    assert slug[-1] not in "-._"


@given(st.lists(st.text(min_size=1, max_size=8), min_size=1, max_size=4))
def test_branch_component_is_stable(parts: list[str]) -> None:
    assert branch_component("-".join(parts)) == branch_component("-".join(parts))


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=12))
def test_safe_relative_keeps_children_inside(name: str) -> None:
    root = Path("/tmp/root")
    assert safe_relative(root, Path("recipes") / name) == Path("recipes") / name


@given(st.integers(min_value=1, max_value=6))
def test_safe_relative_rejects_any_escape_depth(depth: int) -> None:
    root = Path("/tmp/root")
    with pytest.raises(PathSafetyError):
        safe_relative(root, Path("../" * depth) / "escape")
