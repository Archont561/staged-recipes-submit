"""Property-based tests for validation outcomes."""

from __future__ import annotations

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from staged_recipes_submit.discovery import discover_recipes
from staged_recipes_submit.errors import PathSafetyError
from staged_recipes_submit.models import Severity
from staged_recipes_submit.paths import validate_package_name
from staged_recipes_submit.validation import validate_recipe
from support import fresh_dir, write_recipe

VALID_DOCUMENT = """\
package:
  name: "{name}"
  version: "{version}"
about:
  summary: x
  license: MIT
"""


@given(
    name=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=12).filter(
        lambda value: not value.startswith("-") and not value.endswith("-")
    ),
    version=st.from_regex(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", fullmatch=True),
)
def test_a_complete_recipe_never_produces_errors(tmp_path: Path, name: str, version: str) -> None:
    root = fresh_dir(tmp_path)
    recipe = write_recipe(root, name, document=VALID_DOCUMENT.format(name=name, version=version))
    (discovered,) = discover_recipes([recipe])
    issues = validate_recipe(discovered)
    assert [issue.code for issue in issues if issue.severity is Severity.ERROR] == []


@given(name=st.text(min_size=1, max_size=20))
def test_unsafe_names_are_always_reported(tmp_path: Path, name: str) -> None:
    stripped = name.strip()
    if not stripped or "\n" in stripped:
        return
    try:
        validate_package_name(stripped)
    except PathSafetyError:
        pass
    else:
        return
    recipe_dir = fresh_dir(tmp_path)
    document = VALID_DOCUMENT.format(name=stripped, version="1.0")
    (recipe_dir / "recipe.yaml").write_text(document, encoding="utf-8")
    (discovered,) = discover_recipes([recipe_dir])
    codes = {
        issue.code for issue in validate_recipe(discovered) if issue.severity is Severity.ERROR
    }
    assert codes & {"VAL002", "VAL003", "VAL004"}


@given(size=st.integers(min_value=0, max_value=3000))
def test_size_limits_are_respected(tmp_path: Path, size: int) -> None:
    root = fresh_dir(tmp_path)
    recipe = write_recipe(root, "pkg")
    (recipe / "blob.bin").write_bytes(b"x" * size)
    (discovered,) = discover_recipes([recipe])
    issues = validate_recipe(discovered, max_file_bytes=2000)
    expected = {"VAL010"} if size > 2000 else set()
    assert {issue.code for issue in issues} == expected
