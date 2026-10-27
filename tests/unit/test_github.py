"""The GitHub pull-request client, driven through an injected transport."""

from __future__ import annotations

from typing import Any

import pytest

from staged_recipes_submit.discovery import discover_recipes
from staged_recipes_submit.errors import PullRequestError, Secret
from staged_recipes_submit.github import GitHubPullRequests
from staged_recipes_submit.plan import build_plan

TOKEN = "ghp_example_token_value"


class Recorder:
    def __init__(self, responses: list[tuple[int, Any]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def __call__(self, method: str, url: str, payload: dict[str, Any] | None):
        self.calls.append((method, url, payload))
        return self.responses.pop(0)


def _client(recorder: Recorder) -> GitHubPullRequests:
    return GitHubPullRequests(
        token=Secret(TOKEN), upstream="conda-forge/staged-recipes", transport=recorder
    )


def test_find_open_returns_none_for_an_empty_list() -> None:
    recorder = Recorder([(200, [])])
    assert _client(recorder).find_open(head="me:submit/alpha", base="main") is None
    method, url, payload = recorder.calls[0]
    assert method == "GET"
    assert "state=open" in url
    assert "head=me%3Asubmit%2Falpha" in url
    assert payload is None


def test_find_open_maps_the_first_match() -> None:
    payload = [
        {"number": 7, "html_url": "https://github.com/x/y/pull/7", "head": {"ref": "submit/alpha"}}
    ]
    recorder = Recorder([(200, payload)])
    found = _client(recorder).find_open(head="me:submit/alpha", base="main")
    assert found is not None
    assert (found.number, found.url, found.head) == (
        7,
        "https://github.com/x/y/pull/7",
        "submit/alpha",
    )


def test_create_sends_the_unit(recipe_factory) -> None:
    (unit,) = build_plan(discover_recipes([recipe_factory("alpha")]))
    recorder = Recorder([(201, {"number": 9, "html_url": "u", "head": {"ref": "submit/alpha"}})])
    pull_request = _client(recorder).create(unit=unit, head="me:submit/alpha", base="main")
    method, url, payload = recorder.calls[0]
    assert (method, url) == (
        "POST",
        "https://api.github.com/repos/conda-forge/staged-recipes/pulls",
    )
    assert payload is not None
    assert payload["head"] == "me:submit/alpha"
    assert payload["title"] == "Add recipe for alpha"
    assert payload["maintainer_can_modify"] is True
    assert pull_request.number == 9


def test_token_never_appears_in_the_url() -> None:
    recorder = Recorder([(200, [])])
    _client(recorder).find_open(head="me:x", base="main")
    assert TOKEN not in recorder.calls[0][1]


@pytest.mark.parametrize(
    ("status", "message", "fragment"),
    [
        (401, "nope", "invalid, expired or revoked"),
        (403, "nope", "not allowed to do this"),
        (403, "API rate limit exceeded", "rate limit"),
        (404, "nope", "fork"),
        (422, "nope", "already exists"),
    ],
)
def test_error_statuses_become_actionable(status: int, message: str, fragment: str) -> None:
    recorder = Recorder([(status, {"message": message})])
    with pytest.raises(PullRequestError) as error:
        _client(recorder).find_open(head="me:x", base="main")
    assert fragment in (error.value.hint or "")
    assert str(status) in error.value.message


def test_a_429_is_reported_as_a_rate_limit() -> None:
    recorder = Recorder([(429, {"message": "too many"})])
    with pytest.raises(PullRequestError) as error:
        _client(recorder).find_open(head="me:x", base="main")
    assert "rate limit" in (error.value.hint or "")


def test_unexpected_listing_payload_is_rejected() -> None:
    with pytest.raises(PullRequestError, match="unexpected payload"):
        _client(Recorder([(200, {"not": "a list"})])).find_open(head="me:x", base="main")


def test_incomplete_pull_request_payload_is_rejected() -> None:
    with pytest.raises(PullRequestError, match="incomplete"):
        _client(Recorder([(200, [{"number": 1}])])).find_open(head="me:x", base="main")


def test_secret_redacts_itself() -> None:
    secret = Secret(TOKEN)
    assert str(secret) == "Secret(***)"
    assert repr(secret) == "Secret(***)"
    assert TOKEN not in f"{secret!r} {secret}"
    assert secret.reveal() == TOKEN
    with pytest.raises(Exception, match="token is required"):
        Secret("   ")
