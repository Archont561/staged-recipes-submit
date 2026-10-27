"""A minimal GitHub REST client for pull requests.

Only two calls are needed, and both are injectable: tests replace the transport,
so nothing in the suite depends on a live API.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from .errors import PullRequestError, Secret
from .models import PullRequest, SubmissionUnit

API_URL = "https://api.github.com"
Transport = Callable[[str, str, "dict[str, Any] | None"], "tuple[int, Any]"]


class GitHubPullRequests:
    """Open and find pull requests against ``upstream``."""

    def __init__(
        self,
        *,
        token: Secret,
        upstream: str,
        api_url: str = API_URL,
        transport: Transport | None = None,
        timeout: int = 30,
    ) -> None:
        self._token = token
        self._upstream = upstream
        self._api_url = api_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport or self._urllib_transport

    def find_open(self, *, head: str, base: str) -> PullRequest | None:
        query = urllib.parse.urlencode({"state": "open", "head": head, "base": base})
        payload = self._call("GET", f"/repos/{self._upstream}/pulls?{query}")
        if not isinstance(payload, list):
            raise PullRequestError(
                "GitHub returned an unexpected payload when listing pull requests."
            )
        return _pull_request(payload[0]) if payload else None

    def create(self, *, unit: SubmissionUnit, head: str, base: str) -> PullRequest:
        payload = self._call(
            "POST",
            f"/repos/{self._upstream}/pulls",
            {
                "title": unit.title,
                "body": unit.body,
                "head": head,
                "base": base,
                "draft": False,
                "maintainer_can_modify": True,
            },
        )
        if not isinstance(payload, dict):
            raise PullRequestError(
                "GitHub returned an unexpected payload when creating a pull request."
            )
        return _pull_request(payload)

    def _call(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self._api_url}{path}"
        status, data = self._transport(method, url, payload)
        if status >= 400:
            message = data.get("message") if isinstance(data, dict) else None
            raise PullRequestError(
                f"GitHub API returned HTTP {status} for {method} {path}"
                + (f": {message}" if message else ""),
                hint=_hint_for(status, message),
            )
        return data

    def _urllib_transport(  # pragma: no cover - only exercised against a live API
        self, method: str, url: str, payload: dict[str, Any] | None
    ) -> tuple[int, Any]:
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("Authorization", f"Bearer {self._token.reveal()}")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                data = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                data = None
            return error.code, data
        except urllib.error.URLError as error:
            raise PullRequestError(
                f"Cannot reach the GitHub API: {error.reason}",
                hint="check the network and the runner's proxy settings",
            ) from error


def _pull_request(payload: dict[str, Any]) -> PullRequest:
    try:
        return PullRequest(
            number=int(payload["number"]),
            url=str(payload["html_url"]),
            head=str(payload["head"]["ref"]),
            state=str(payload.get("state", "open")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PullRequestError("GitHub returned an incomplete pull-request object.") from error


def _hint_for(status: int, message: str | None = None) -> str:
    """Say what the status means for the credentials, not just what happened."""
    detail = (message or "").lower()
    if status == 401:
        return (
            "GitHub rejected the token outright: it is invalid, expired or revoked. "
            "Create a new one and update the secret"
        )
    if status in {403, 429}:
        if "rate limit" in detail or "abuse" in detail or status == 429:
            return (
                "the token hit a rate limit: retry later, or use a token with a higher quota "
                "(secrets.GITHUB_TOKEN has the lowest)"
            )
        return (
            "the token was accepted but is not allowed to do this: it needs contents: write on "
            "the fork and pull_requests: write on the upstream, and must belong to the fork's "
            "owner or to an app installed on the fork"
        )
    if status == 404:
        return "check the fork and upstream names, and whether the token can see the repository"
    if status == 422:
        return (
            "a pull request for this branch probably already exists, or the branch was not pushed"
        )
    return "retry; if it persists, run with --dry-run and inspect the plan"
