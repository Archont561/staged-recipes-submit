"""End-to-end submission flow against in-memory backends."""

from __future__ import annotations

import pytest

from staged_recipes_submit.discovery import discover_recipes
from staged_recipes_submit.errors import ConfigurationError
from staged_recipes_submit.models import Issue, Outcome, SubmissionMode
from staged_recipes_submit.submit import SubmissionRequest, inspect, run_submission


def _request(recipes, **kwargs) -> SubmissionRequest:
    return SubmissionRequest(recipes=tuple(recipes), fork="tester/staged-recipes", **kwargs)


def test_a_valid_recipe_creates_one_pull_request(
    recipe_factory, fake_git, fake_pull_requests
) -> None:
    request = _request([recipe_factory("alpha")])
    report = run_submission(request, git=fake_git, pull_requests=fake_pull_requests)

    assert report.ok
    (result,) = report.results
    assert result.outcome is Outcome.CREATED
    assert result.unit.branch == "submit/alpha"
    assert fake_git.pushed == ["submit/alpha"]
    assert fake_git.prepared == ("conda-forge/staged-recipes", "tester/staged-recipes", "main")
    assert (fake_git.workdir / "recipes" / "alpha" / "recipe.yaml").is_file()
    assert len(fake_pull_requests.created) == 1


def test_several_recipes_share_one_pull_request(
    recipe_factory, fake_git, fake_pull_requests
) -> None:
    request = _request([recipe_factory("alpha"), recipe_factory("beta")])
    report = run_submission(request, git=fake_git, pull_requests=fake_pull_requests)

    (result,) = report.results
    assert result.outcome is Outcome.CREATED
    assert result.unit.package_names == ("alpha", "beta")
    assert len(fake_pull_requests.created) == 1


def test_per_recipe_mode_creates_one_pull_request_each(
    recipe_factory, fake_git, fake_pull_requests
) -> None:
    request = _request(
        [recipe_factory("alpha"), recipe_factory("beta")], mode=SubmissionMode.PER_RECIPE
    )
    report = run_submission(request, git=fake_git, pull_requests=fake_pull_requests)

    assert [result.outcome for result in report.results] == [Outcome.CREATED, Outcome.CREATED]
    assert len(fake_pull_requests.created) == 2
    assert fake_git.pushed == ["submit/alpha", "submit/beta"]


def test_dry_run_never_touches_a_backend(recipe_factory, fake_git, fake_pull_requests) -> None:
    request = _request([recipe_factory("alpha")], dry_run=True)
    report = run_submission(request, git=fake_git, pull_requests=fake_pull_requests)

    assert report.dry_run is True
    assert [result.outcome for result in report.results] == [Outcome.PLANNED]
    assert fake_git.calls == []
    assert fake_pull_requests.calls == []


def test_invalid_recipes_block_every_write(recipe_factory, fake_git, fake_pull_requests) -> None:
    request = _request([recipe_factory("alpha", document="package: [unclosed\n")])
    report = run_submission(request, git=fake_git, pull_requests=fake_pull_requests)

    assert not report.ok
    assert report.results == ()
    assert fake_git.calls == []
    assert fake_pull_requests.calls == []


def test_duplicate_package_blocks_every_write(
    recipe_factory, staged_recipes_checkout, fake_git, fake_pull_requests
) -> None:
    (staged_recipes_checkout / "recipes" / "alpha").mkdir()
    request = _request(
        [recipe_factory("alpha")], staged_recipes_root=staged_recipes_checkout / "recipes"
    )
    report = run_submission(request, git=fake_git, pull_requests=fake_pull_requests)

    assert not report.ok
    assert {issue.code for issue in report.issues} == {"DUP002"}
    assert fake_git.calls == []


def test_a_rerun_reuses_the_open_pull_request(recipe_factory, fake_git, fake_pull_requests) -> None:
    request = _request([recipe_factory("alpha")])
    first = run_submission(request, git=fake_git, pull_requests=fake_pull_requests)
    second = run_submission(request, git=fake_git, pull_requests=fake_pull_requests)

    assert first.results[0].outcome is Outcome.CREATED
    assert second.results[0].outcome is Outcome.REUSED
    assert len(fake_pull_requests.created) == 1
    assert fake_git.pushed == ["submit/alpha"]


def test_a_changed_recipe_updates_the_existing_branch(
    recipe_factory, fake_git, fake_pull_requests
) -> None:
    recipe = recipe_factory("alpha")
    request = _request([recipe])
    run_submission(request, git=fake_git, pull_requests=fake_pull_requests)
    (recipe / "extra.patch").write_text("--- a\n+++ b\n", encoding="utf-8")
    report = run_submission(_request([recipe]), git=fake_git, pull_requests=fake_pull_requests)

    assert report.results[0].outcome is Outcome.UPDATED
    assert fake_git.pushed == ["submit/alpha", "submit/alpha"]


def test_extra_issues_from_the_action_wrapper_are_reported(
    recipe_factory, fake_git, fake_pull_requests
) -> None:
    request = _request(
        [recipe_factory("alpha")], extra_issues=(Issue("ACT001", "token lacks scope"),)
    )
    report = run_submission(request, git=fake_git, pull_requests=fake_pull_requests)
    assert not report.ok
    assert fake_git.calls == []


def test_inspect_reports_plan_without_writing(recipe_factory, fake_git) -> None:
    recipes, issues, units = inspect(_request([recipe_factory("alpha"), recipe_factory("beta")]))
    assert [recipe.name for recipe in recipes] == ["alpha", "beta"]
    assert issues == []
    assert [unit.branch for unit in units] == ["submit/alpha-beta"]
    assert fake_git.calls == []


def test_explicit_slugs_are_validated() -> None:
    with pytest.raises(ConfigurationError):
        SubmissionRequest(recipes=("x",), fork="nonsense")
    with pytest.raises(ConfigurationError):
        SubmissionRequest(recipes=("x",), fork="me/fork", upstream="../../etc")


def test_report_renders_outcomes(recipe_factory, fake_git, fake_pull_requests) -> None:
    report = run_submission(
        _request([recipe_factory("alpha")]), git=fake_git, pull_requests=fake_pull_requests
    )
    assert (
        "created  alpha -> https://github.com/conda-forge/staged-recipes/pull/1" in report.render()
    )
    assert report.to_dict()["results"][0]["packages"] == ["alpha"]


def test_report_renders_nothing_to_do() -> None:
    from staged_recipes_submit.models import SubmissionReport

    assert "nothing to do" in SubmissionReport(results=()).render()


def test_recipe_discovery_happens_once_per_run(
    recipe_factory, fake_git, fake_pull_requests
) -> None:
    request = _request([recipe_factory("alpha"), recipe_factory("beta")])
    run_submission(request, git=fake_git, pull_requests=fake_pull_requests)
    assert fake_git.calls.count("prepare") == 1
    assert sorted(discover_recipes([recipe_factory("gamma")])[0].relative_files()) == [
        "recipe.yaml"
    ]
