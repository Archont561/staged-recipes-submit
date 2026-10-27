"""Structural validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from staged_recipes_submit.discovery import discover_recipes
from staged_recipes_submit.errors import RecipeValidationError
from staged_recipes_submit.models import Severity
from staged_recipes_submit.validation import raise_for_errors, validate_recipe, validate_recipes
from support import V0_TEMPLATE, V1_TEMPLATE


def _issues(recipe: Path, **kwargs):
    (discovered,) = discover_recipes([recipe])
    return validate_recipe(discovered, **kwargs)


def _codes(issues) -> set[str]:
    return {issue.code for issue in issues}


def test_a_complete_recipe_has_no_findings(recipe_factory) -> None:
    assert _issues(recipe_factory("alpha")) == []


def test_missing_version_is_a_warning(recipe_factory) -> None:
    document = "package:\n  name: alpha\nabout:\n  summary: x\n"
    issues = _issues(recipe_factory("alpha", document=document))
    assert _codes(issues) == {"VAL006"}
    assert issues[0].severity is Severity.WARNING


def test_missing_about_is_a_warning(recipe_factory) -> None:
    document = "package:\n  name: alpha\n  version: '1.0'\nbuild:\n  number: 0\n"
    assert _codes(_issues(recipe_factory("alpha", document=document))) == {"VAL007"}


def test_missing_source_in_v0_recipe_is_a_warning(recipe_factory) -> None:
    document = "package:\n  name: alpha\n  version: '1.0'\nabout:\n  summary: x\n"
    issues = _issues(recipe_factory("alpha", filename="meta.yaml", document=document))
    assert _codes(issues) == {"VAL008"}


def test_invalid_package_name_is_an_error(recipe_factory) -> None:
    document = "package:\n  name: Bad Name\n  version: '1.0'\nabout:\n  summary: x\n"
    issues = _issues(recipe_factory("alpha", document=document))
    assert "VAL004" in _codes(issues)
    assert all(issue.hint for issue in issues if issue.severity is Severity.ERROR)


def test_directory_name_mismatch_is_a_warning(recipe_factory) -> None:
    recipe = recipe_factory("other-directory")
    document = V1_TEMPLATE.format(name="actual-name", version="1.0.0", module="actual_name")
    (recipe / "recipe.yaml").write_text(document, encoding="utf-8")
    issues = _issues(recipe)
    assert _codes(issues) == {"VAL005"}
    assert "recipes/actual-name/" in issues[0].hint


def test_broken_document_reports_parse_and_missing_name(recipe_factory) -> None:
    issues = _issues(recipe_factory("alpha", document="package: [unclosed\n"))
    assert _codes(issues) == {"VAL002"}
    assert issues[0].severity is Severity.ERROR


def test_missing_package_section_is_reported(recipe_factory) -> None:
    issues = _issues(recipe_factory("alpha", document="build:\n  number: 0\n"))
    assert {"VAL002", "VAL003"} <= _codes(issues)


def test_missing_about_and_version_for_an_empty_mapping(recipe_factory) -> None:
    issues = _issues(recipe_factory("alpha", document="package:\n  name: alpha\n"))
    assert "VAL006" in _codes(issues)


def test_oversized_file_is_an_error(recipe_factory) -> None:
    recipe = recipe_factory("alpha")
    (recipe / "big.patch").write_bytes(b"x" * 2048)
    issues = _issues(recipe, max_file_bytes=1024)
    assert "VAL010" in _codes(issues)


def test_oversized_recipe_is_an_error(recipe_factory) -> None:
    recipe = recipe_factory("alpha")
    (recipe / "patch.patch").write_bytes(b"x" * 2048)
    issues = _issues(recipe, max_recipe_bytes=1024)
    assert "VAL011" in _codes(issues)


def test_unrecognised_recipe_filename_is_an_error(tmp_path: Path) -> None:
    recipe = tmp_path / "alpha"
    recipe.mkdir()
    (recipe / "recipe.yaml").write_text("package:\n  name: alpha\n  version: '1'\n")
    (discovered,) = discover_recipes([recipe])
    tampered = type(discovered)(
        name=discovered.name,
        version=discovered.version,
        root=discovered.root,
        recipe_file=Path("notes.txt"),
        files=discovered.files,
        metadata=discovered.metadata,
    )
    assert "VAL001" in _codes(validate_recipe(tampered))


def test_validate_recipes_partitions_valid_recipes(recipe_factory) -> None:
    good = recipe_factory("good")
    bad = recipe_factory("bad", document="package: [unclosed\n")
    issues, valid = validate_recipes(discover_recipes([good, bad]))
    assert [recipe.name for recipe in valid] == ["good"]
    assert {issue.code for issue in issues} >= {"VAL002"}


def test_raise_for_errors_is_silent_on_warnings(recipe_factory) -> None:
    issues = _issues(recipe_factory("alpha", document="package:\n  name: alpha\n"))
    raise_for_errors(issues)


def test_raise_for_errors_aggregates_messages(recipe_factory) -> None:
    issues = _issues(recipe_factory("alpha", document="package: [unclosed\n"))
    with pytest.raises(RecipeValidationError) as error:
        raise_for_errors(issues)
    assert "recipe problem(s)" in str(error.value)
    assert "VAL002" in str(error.value)


def test_v0_recipe_with_source_is_clean(recipe_factory) -> None:
    document = V0_TEMPLATE.format(name="alpha", version="1.0")
    assert _issues(recipe_factory("alpha", filename="meta.yaml", document=document)) == []


def test_recipe_bytes_are_summed(recipe_factory) -> None:
    recipe = recipe_factory("alpha")
    (recipe / "a.txt").write_text("a")
    (recipe / "b.txt").write_text("bb")
    (discovered,) = discover_recipes([recipe])
    expected = sum((recipe / name).stat().st_size for name in ("recipe.yaml", "a.txt", "b.txt"))
    assert discovered.total_bytes == expected


def test_path_to_resolves_inside_the_recipe(recipe_factory) -> None:
    recipe = recipe_factory("alpha")
    (discovered,) = discover_recipes([recipe])
    assert discovered.path_to(Path("recipe.yaml")) == recipe.resolve() / "recipe.yaml"
