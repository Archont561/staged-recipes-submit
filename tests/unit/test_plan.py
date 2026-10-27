"""Submission planning."""

from __future__ import annotations

import pytest

from staged_recipes_submit.discovery import discover_recipes
from staged_recipes_submit.errors import ConfigurationError
from staged_recipes_submit.models import SubmissionMode
from staged_recipes_submit.plan import branch_name, build_plan, commit_message, default_body


def _recipes(*names, factory):
    return discover_recipes([factory(name) for name in names])


def test_single_mode_creates_one_unit(recipe_factory) -> None:
    (unit,) = build_plan(_recipes("alpha", "beta", factory=recipe_factory))
    assert unit.package_names == ("alpha", "beta")
    assert unit.branch == "submit/alpha-beta"
    assert unit.title == "Add recipes for alpha, beta"


def test_per_recipe_mode_creates_one_unit_each(recipe_factory) -> None:
    units = build_plan(
        _recipes("beta", "alpha", factory=recipe_factory), mode=SubmissionMode.PER_RECIPE
    )
    assert [unit.package_names for unit in units] == [("alpha",), ("beta",)]
    assert [unit.branch for unit in units] == ["submit/alpha", "submit/beta"]
    assert units[0].title == "Add recipe for alpha"


def test_many_recipes_get_a_hashed_batch_branch(recipe_factory) -> None:
    recipes = _recipes("alpha", "beta", "gamma", "delta", factory=recipe_factory)
    (unit,) = build_plan(recipes)
    assert unit.branch.startswith("submit/batch-4-")
    assert len(unit.branch.split("-")[-1]) == 8


def test_branch_names_are_stable(recipe_factory) -> None:
    recipes = _recipes("alpha", "beta", "gamma", "delta", factory=recipe_factory)
    assert branch_name(recipes) == branch_name(list(reversed(recipes)))


def test_custom_title_and_body_win(recipe_factory) -> None:
    (unit,) = build_plan(
        _recipes("alpha", factory=recipe_factory), title="Custom", body="Body", branch_prefix="ci"
    )
    assert (unit.title, unit.body, unit.branch) == ("Custom", "Body", "ci/alpha")


def test_body_lists_every_package_and_the_handover(recipe_factory) -> None:
    body = default_body(_recipes("alpha", "beta", factory=recipe_factory))
    assert "`alpha` 1.0.0" in body
    assert "conda-forge maintainers" in body


def test_body_without_a_version(recipe_factory, recipes_dir) -> None:
    recipe = recipe_factory("alpha", document="package:\n  name: alpha\nabout:\n  summary: x\n")
    (unit,) = build_plan(discover_recipes([recipe]))
    assert "`alpha`\n" in unit.body


def test_commit_message_is_conventional(recipe_factory) -> None:
    (unit,) = build_plan(_recipes("alpha", factory=recipe_factory))
    assert commit_message(unit).startswith("feat: add recipe for alpha\n\n")


def test_commit_message_for_several_recipes(recipe_factory) -> None:
    (unit,) = build_plan(_recipes("alpha", "beta", factory=recipe_factory))
    assert commit_message(unit).startswith("feat: add recipes for alpha, beta\n\n")


def test_empty_plan_is_a_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        build_plan([])


def test_destination_directories_are_named_after_packages(recipe_factory) -> None:
    (unit,) = build_plan(_recipes("alpha", factory=recipe_factory))
    directories = unit.destination_directories
    assert list(directories) == ["recipes/alpha"]
