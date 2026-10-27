"""The seams that keep the action testable without touching GitHub.

``submit`` talks only to these protocols. Tests pass in doubles; the CLI passes
the real implementations from :mod:`staged_recipes_submit.gitops` and
:mod:`staged_recipes_submit.github`. A dry run passes guards that fail loudly
if anything tries to write.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import PullRequest, SubmissionUnit


class GitBackend(Protocol):
    """The Git operations a submission needs."""

    def prepare(self, *, upstream: str, fork: str, base_branch: str) -> Path:
        """Clone or refresh the fork checkout and return its path."""

    def checkout_or_create(self, branch: str) -> None:
        """Check out ``branch`` from the base branch, creating it if needed."""

    def materialize(self, unit: SubmissionUnit) -> bool:
        """Copy each recipe into ``recipes/<name>/``; return True when files changed."""

    def commit(self, message: str) -> bool:
        """Commit the staged changes; return False when the tree was already clean."""

    def push(self, branch: str) -> None:
        """Push the branch to the fork."""


class PullRequestBackend(Protocol):
    """The pull-request operations a submission needs."""

    def find_open(self, *, head: str, base: str) -> PullRequest | None:
        """Return the open pull request for ``head`` if one exists."""

    def create(self, *, unit: SubmissionUnit, head: str, base: str) -> PullRequest:
        """Open a pull request for ``unit`` and return it."""


class DryRunGuard:
    """A backend that refuses every write, proving a dry run changed nothing."""

    def __getattr__(self, name: str) -> object:
        def refuse(*_args: object, **_kwargs: object) -> object:
            raise AssertionError(f"dry-run called {name}(); dry-run must not touch remote state")

        return refuse
