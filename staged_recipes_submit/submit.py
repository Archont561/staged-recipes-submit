"""The submission workflow: discover, validate, plan, write, open a pull request."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .backends import GitBackend, PullRequestBackend
from .discovery import discover_recipes
from .duplicates import detect_duplicates
from .errors import ConfigurationError
from .models import (
    Issue,
    Outcome,
    Recipe,
    Severity,
    SubmissionMode,
    SubmissionReport,
    SubmissionUnit,
    UnitResult,
)
from .plan import build_plan, commit_message
from .validation import validate_recipes

DEFAULT_UPSTREAM = "conda-forge/staged-recipes"
DEFAULT_BASE_BRANCH = "main"
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")


@dataclass(frozen=True, slots=True)
class SubmissionRequest:
    """Validated action inputs."""

    recipes: tuple[str | Path, ...]
    fork: str
    upstream: str = DEFAULT_UPSTREAM
    base_branch: str = DEFAULT_BASE_BRANCH
    mode: SubmissionMode = SubmissionMode.SINGLE
    title: str | None = None
    body: str | None = None
    branch_prefix: str = "submit"
    dry_run: bool = False
    base_dir: Path | None = None
    staged_recipes_root: Path | None = None
    extra_issues: tuple[Issue, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not _SLUG.match(self.fork):
            raise ConfigurationError(
                f"{self.fork!r} is not a 'owner/name' fork.",
                hint="use the fork that staged-recipes should receive the branch from",
            )
        if not _SLUG.match(self.upstream):
            raise ConfigurationError(f"{self.upstream!r} is not a 'owner/name' repository.")


def inspect(
    request: SubmissionRequest,
) -> tuple[list[Recipe], list[Issue], list[SubmissionUnit]]:
    """Discover, validate and plan without writing anything."""
    recipes = discover_recipes(request.recipes, base=request.base_dir)
    issues, _valid = validate_recipes(recipes)
    issues.extend(detect_duplicates(recipes, staged_recipes_root=request.staged_recipes_root))
    issues.extend(request.extra_issues)
    if any(issue.severity is Severity.ERROR for issue in issues):
        return recipes, issues, []
    units = build_plan(
        recipes,
        mode=request.mode,
        title=request.title,
        body=request.body,
        branch_prefix=request.branch_prefix,
    )
    return recipes, issues, units


def run_submission(
    request: SubmissionRequest,
    *,
    git: GitBackend,
    pull_requests: PullRequestBackend,
) -> SubmissionReport:
    """Execute the submission and report what happened to every unit."""
    _recipes, issues, units = inspect(request)
    if not units:
        return SubmissionReport(results=(), issues=tuple(issues), dry_run=request.dry_run)
    if request.dry_run:
        planned = tuple(UnitResult(unit=unit, outcome=Outcome.PLANNED) for unit in units)
        return SubmissionReport(results=planned, issues=tuple(issues), dry_run=True)

    owner = request.fork.split("/", 1)[0]
    git.prepare(upstream=request.upstream, fork=request.fork, base_branch=request.base_branch)
    results: list[UnitResult] = []
    for unit in units:
        results.append(
            _submit_unit(unit, request=request, git=git, pull_requests=pull_requests, owner=owner)
        )
    return SubmissionReport(results=tuple(results), issues=tuple(issues), dry_run=False)


def _submit_unit(
    unit: SubmissionUnit,
    *,
    request: SubmissionRequest,
    git: GitBackend,
    pull_requests: PullRequestBackend,
    owner: str,
) -> UnitResult:
    head = f"{owner}:{unit.branch}"
    git.checkout_or_create(unit.branch)
    git.materialize(unit)
    committed = git.commit(commit_message(unit))
    existing = pull_requests.find_open(head=head, base=request.base_branch)
    if existing is not None:
        if committed:
            git.push(unit.branch)
        outcome = Outcome.UPDATED if committed else Outcome.REUSED
        detail = "branch updated" if committed else "nothing to change"
        return UnitResult(unit=unit, outcome=outcome, pull_request=existing, detail=detail)
    git.push(unit.branch)
    created = pull_requests.create(unit=unit, head=head, base=request.base_branch)
    return UnitResult(unit=unit, outcome=Outcome.CREATED, pull_request=created)
