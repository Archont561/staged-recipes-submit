"""Gherkin scenarios for the submission workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from staged_recipes_submit.models import Outcome, SubmissionReport
from staged_recipes_submit.submit import SubmissionRequest, run_submission
from support import FakeGit, FakePullRequests, write_recipe

scenarios("features/submission.feature")

FORK = "archont561/staged-recipes"


@dataclass
class State:
    """Everything one scenario needs, rebuilt per test."""

    sources: Path
    workdir: Path
    staged_recipes: Path
    fork: str = FORK
    recipes: list[Path] = field(default_factory=list)
    staged_root: Path | None = None
    reports: list[SubmissionReport] = field(default_factory=list)
    dry_run: bool = False

    @property
    def git(self) -> FakeGit:
        return self._git

    @property
    def pull_requests(self) -> FakePullRequests:
        return self._pull_requests

    @property
    def report(self) -> SubmissionReport:
        return self.reports[-1]


@pytest.fixture
def state(tmp_path: Path) -> State:
    sources = tmp_path / "sources"
    sources.mkdir()
    workdir = tmp_path / "fork"
    (workdir / "recipes").mkdir(parents=True)
    staged = tmp_path / "staged-recipes"
    (staged / "recipes").mkdir(parents=True)
    created = State(sources=sources, workdir=workdir, staged_recipes=staged)
    created._git = FakeGit(workdir=workdir)
    created._pull_requests = FakePullRequests()
    return created


@given(parsers.parse('a fork "{fork}"'))
def _fork(state: State, fork: str) -> None:
    state.fork = fork


@given(parsers.parse('a valid recipe "{name}" version "{version}"'))
def _valid_recipe(state: State, name: str, version: str) -> None:
    state.recipes.append(write_recipe(state.sources, name, version=version))


@given(parsers.parse('a recipe "{name}" without a package section'))
def _broken_recipe(state: State, name: str) -> None:
    document = "build:\n  number: 0\n"
    state.recipes.append(write_recipe(state.sources, name, document=document))


@given(parsers.parse('the upstream already has a recipe for "{name}"'))
def _existing_upstream_recipe(state: State, name: str) -> None:
    (state.staged_recipes / "recipes" / name).mkdir(parents=True)
    state.staged_root = state.staged_recipes / "recipes"


@when("I submit the recipe")
def _submit(state: State) -> None:
    request = SubmissionRequest(
        recipes=tuple(state.recipes),
        fork=state.fork,
        dry_run=state.dry_run,
        staged_recipes_root=state.staged_root,
    )
    state.reports.append(
        run_submission(request, git=state._git, pull_requests=state._pull_requests)
    )


@when("I submit the recipe again")
def _submit_again(state: State) -> None:
    _submit(state)


@when("I submit the recipe as a dry run")
def _submit_dry_run(state: State) -> None:
    state.dry_run = True
    _submit(state)


@then("one pull request is created")
def _one_pull_request(state: State) -> None:
    assert len(state._pull_requests.created) == 1
    assert any(result.pull_request for result in state.report.results)


@then(parsers.parse('the branch is "{branch}"'))
def _branch(state: State, branch: str) -> None:
    assert state.report.results[0].unit.branch == branch
    assert state._git.pushed == [branch]


@then(parsers.parse('the recipe lands in "{directory}"'))
def _recipe_lands(state: State, directory: str) -> None:
    assert (state.workdir / directory / "recipe.yaml").is_file()


@then(parsers.parse('the pull request mentions "{first}" and "{second}"'))
def _mentions(state: State, first: str, second: str) -> None:
    (result,) = state.report.results
    assert first in result.unit.title
    assert second in result.unit.title
    assert first in result.unit.body
    assert second in result.unit.body


@then(parsers.parse('the submission fails with code "{code}"'))
def _fails_with(state: State, code: str) -> None:
    assert not state.report.ok
    assert code in {issue.code for issue in state.report.issues}


@then("the hint explains the next step")
def _hint(state: State) -> None:
    assert all(issue.hint for issue in state.report.issues)


@then("no pull request is created")
def _no_pull_request(state: State) -> None:
    assert state._pull_requests.created == []


@then("no branch is pushed")
def _no_push(state: State) -> None:
    assert state._git.pushed == []


@then("the report is a dry run")
def _dry_run(state: State) -> None:
    assert state.report.dry_run is True
    assert [result.outcome for result in state.report.results] == [Outcome.PLANNED]


@then("the second run reuses it")
def _reused(state: State) -> None:
    assert state.reports[-1].results[0].outcome is Outcome.REUSED
    assert state.reports[-1].results[0].pull_request is not None
