"""Actionable failures.

Every error carries a human-readable message and, where it helps, a ``hint``
that tells the user what to change. Errors never contain credentials.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import Issue


class SubmissionError(Exception):
    """Base class for every expected failure of this action."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message}\n  hint: {self.hint}" if self.hint else self.message


class ConfigurationError(SubmissionError):
    """The action was invoked with inputs that cannot work."""


class PathSafetyError(SubmissionError, ValueError):
    """A path escaped the directory it was allowed to touch."""


class RecipeDiscoveryError(SubmissionError):
    """Recipe files could not be located or were ambiguous."""


class RecipeValidationError(SubmissionError):
    """One or more recipes failed validation."""

    def __init__(self, issues: Iterable[Issue]) -> None:
        self.issues = tuple(issues)
        errors = [issue for issue in self.issues if issue.severity.value == "error"]
        super().__init__(
            f"{len(errors)} recipe problem(s) must be fixed before a submission is possible:\n"
            + "\n".join(f"  {issue.render()}" for issue in errors)
        )


class DuplicateRecipeError(SubmissionError):
    """A package already exists upstream or appears twice in one submission."""


class GitError(SubmissionError):
    """A local or remote Git operation failed."""


class PullRequestError(SubmissionError):
    """The GitHub API refused the pull-request operation."""


class Secret:
    """A credential that refuses to render itself.

    The value is available through :meth:`reveal` for the one place that needs
    it (an auth header), and every other string conversion is redacted, so a
    token cannot reach a log line by accident.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not value.strip():
            raise ConfigurationError(
                "A GitHub token is required.",
                hint="pass the 'github-token' input or set GITHUB_TOKEN in the environment",
            )
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    __str__ = __repr__

    def __bool__(self) -> bool:
        return True
