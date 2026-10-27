"""Credential diagnostics: the message matters more than the failure."""

from __future__ import annotations

import pytest

from staged_recipes_submit import credentials
from staged_recipes_submit.errors import ConfigurationError

FORK = "octocat/staged-recipes"


@pytest.mark.parametrize(
    ("token", "label"),
    [
        ("ghp_abc", "a classic personal access token"),
        ("github_pat_abc", "a fine-grained personal access token"),
        ("ghs_abc", "a GitHub App installation token"),
        ("gho_abc", "an OAuth token"),
        ("hunter2", "an unrecognised credential"),
    ],
)
def test_tokens_are_classified_without_being_revealed(token: str, label: str) -> None:
    assert credentials.classify(token) == label
    assert token not in credentials.classify(token)


def test_a_personal_access_token_raises_no_warning() -> None:
    assert credentials.warnings("ghp_abc", fork=FORK) == []
    assert credentials.warnings("github_pat_abc", fork=FORK) == []


def test_the_workflow_token_is_flagged_as_repository_scoped() -> None:
    (warning,) = credentials.warnings("ghs_abc", fork=FORK)
    assert "installation token" in warning
    assert FORK in warning
    assert "secrets.GITHUB_TOKEN" in warning


def test_an_unrecognisable_token_is_flagged_without_echoing_it() -> None:
    (warning,) = credentials.warnings("hunter2", fork=FORK)
    assert "hunter2" not in warning
    assert "ghp_" in warning


def test_the_action_hint_names_the_input_and_the_secret_store() -> None:
    error = credentials.missing_token_error(fork=FORK, surface="action")
    hint = error.hint or ""
    assert "`github-token`" in hint
    assert "secrets." in hint
    assert "Settings > Secrets and variables > Actions" in hint
    assert "empty string" in hint
    assert "cannot push to a fork" in hint
    assert FORK in hint


def test_the_cli_hint_names_the_flag_and_the_environment() -> None:
    error = credentials.missing_token_error(fork=FORK, surface="cli")
    hint = error.hint or ""
    assert "--token" in hint
    assert "GITHUB_TOKEN" in hint
    assert FORK in hint


@pytest.mark.parametrize("value", ["", "   ", None])
def test_resolve_refuses_an_empty_value(value: str | None) -> None:
    with pytest.raises(ConfigurationError, match="No GitHub token"):
        credentials.resolve(value, fork=FORK, surface="action")


def test_resolve_strips_whitespace_around_a_secret() -> None:
    assert credentials.resolve("  ghp_abc\n", fork=FORK, surface="action").reveal() == "ghp_abc"


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
            "cannot write to octocat/staged-recipes",
        ),
        ("remote: Permission to octocat/staged-recipes.git denied to someone.", "cannot write to"),
        (
            "error: failed to push some refs to 'https://github.com/octocat/staged-recipes.git'",
            "branch protection",
        ),
    ],
)
def test_remote_failures_are_explained_from_gits_own_words(stderr: str, expected: str) -> None:
    assert expected in credentials.remote_hint(stderr, fork=FORK)
