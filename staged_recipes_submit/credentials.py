"""Turn credential problems into messages that name the thing to fix.

The most common failure is not a wrong token but no token at all: a workflow that
references an unset or misnamed secret receives an empty string, and GitHub
reports nothing. Every message here is written for the surface it appears on --
the composite action talks about inputs and secrets, the CLI talks about flags
and environment variables -- and none of them can contain the token itself.
"""

from __future__ import annotations

from .errors import ConfigurationError, Secret

TOKEN_KINDS = (
    ("github_pat_", "a fine-grained personal access token"),
    ("ghp_", "a classic personal access token"),
    ("ghs_", "a GitHub App installation token"),
    ("ghu_", "a GitHub App user token"),
    ("gho_", "an OAuth token"),
    ("ghr_", "a GitHub App refresh token"),
)
PREFIXES = ", ".join(prefix for prefix, _ in TOKEN_KINDS)


def classify(token: str) -> str:
    """Name the token family so a message can say what was actually supplied."""
    for prefix, label in TOKEN_KINDS:
        if token.startswith(prefix):
            return label
    return "an unrecognised credential"


def warnings(token: str, *, fork: str) -> list[str]:
    """Describe tokens that may be structurally unable to push to ``fork``.

    Warnings, not errors: a GitHub App installed on the fork *can* push with a
    ``ghs_`` token, and GitHub may add token prefixes this code does not know.
    """
    if token.startswith("ghs_"):
        return [
            f"the token looks like {classify(token)}, which GitHub issues for a single "
            f"repository. It can only push to {fork} if that app is installed on the fork; "
            "the workflow's own secrets.GITHUB_TOKEN cannot."
        ]
    if not token.startswith(tuple(prefix for prefix, _ in TOKEN_KINDS)):
        return [
            f"the token is {classify(token)}: it starts with none of {PREFIXES}. "
            "Check for stray whitespace or a value copied from the wrong field."
        ]
    return []


def missing_token_error(*, fork: str, surface: str) -> ConfigurationError:
    """Explain an absent token in the vocabulary of the caller's surface."""
    if surface == "action":
        hint = (
            "set the `github-token` input, e.g. `github-token: ${{ secrets.CONDA_FORGE_TOKEN }}`, "
            "and define that secret under Settings > Secrets and variables > Actions. "
            "An unset or misspelled secret expands to an empty string, so this is also what a "
            "missing secret looks like. Note that `secrets.GITHUB_TOKEN` is scoped to the "
            "repository running the workflow and cannot push to a fork: use a personal access "
            "token (classic `public_repo`, or fine-grained with Contents and Pull requests write "
            f"on {fork}) or a GitHub App token for an app installed on that fork."
        )
    else:
        hint = (
            "pass --token, or set GITHUB_TOKEN (GH_TOKEN also works). "
            f"The token needs contents: write on {fork} and pull_requests: write on the upstream."
        )
    return ConfigurationError(f"No GitHub token was provided for pushing to {fork}.", hint=hint)


def resolve(value: str | None, *, fork: str, surface: str) -> Secret:
    """Return a token or raise with a message tailored to ``surface``."""
    token = (value or "").strip()
    if not token:
        raise missing_token_error(fork=fork, surface=surface)
    return Secret(token)


def remote_hint(stderr: str, *, fork: str) -> str:
    """Explain a failed remote operation by looking at what git actually said.

    Git's own words are the only reliable signal here -- it prints the same
    "could not read Username ... terminal prompts disabled" for a missing token,
    an expired token and a fork that does not exist.
    """
    lowered = stderr.lower()
    markers = (
        "could not read username",
        "authentication failed",
        "invalid username or password",
        "terminal prompts disabled",
        "permission to",
        "denied",
        "403",
    )
    if any(marker in lowered for marker in markers):
        return (
            f"the credentials cannot write to {fork}: the token needs contents: read and write "
            "there and must belong to the fork's owner or to an app installed on the fork. "
            "Check that the fork exists and that the secret is not empty."
        )
    return f"check the fork name ({fork}), the network, and branch protection on the fork"
