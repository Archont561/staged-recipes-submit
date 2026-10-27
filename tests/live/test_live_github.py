"""Opt-in, read-only checks against the real GitHub API.

Run with ``pytest --run-live tests/live`` and a GITHUB_TOKEN that can read
conda-forge/staged-recipes. These tests never write: they only list pull
requests, so a mistaken invocation cannot create a branch or a pull request.
"""

from __future__ import annotations

import os

import pytest

from staged_recipes_submit.errors import Secret
from staged_recipes_submit.github import GitHubPullRequests

pytestmark = pytest.mark.live


@pytest.fixture
def client() -> GitHubPullRequests:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        pytest.skip("GITHUB_TOKEN is required for live tests")
    return GitHubPullRequests(token=Secret(token), upstream="conda-forge/staged-recipes")


def test_no_open_pull_request_for_an_impossible_branch(client: GitHubPullRequests) -> None:
    assert (
        client.find_open(head="conda-forge:does-not-exist-staged-recipes-submit", base="main")
        is None
    )
