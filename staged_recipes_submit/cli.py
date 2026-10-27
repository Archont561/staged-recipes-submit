"""Command-line entry point used by ``action.yml`` and by humans."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from . import credentials
from ._version import __version__
from .backends import DryRunGuard
from .errors import (
    ConfigurationError,
    PathSafetyError,
    RecipeDiscoveryError,
    Secret,
    SubmissionError,
)
from .github import GitHubPullRequests
from .gitops import SubprocessGit
from .models import SubmissionMode, SubmissionReport
from .submit import DEFAULT_BASE_BRANCH, DEFAULT_UPSTREAM, SubmissionRequest, run_submission

DEFAULT_WORKDIR = Path(".staged-recipes")
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_INPUT = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="staged-recipes-submit",
        description=(
            "Validate conda recipes and open a pull request against "
            "conda-forge/staged-recipes. Never merges and never publishes."
        ),
    )
    parser.add_argument(
        "--recipe",
        "-r",
        dest="recipes",
        action="append",
        required=True,
        metavar="PATH",
        help="recipe directory or recipe.yaml/meta.yaml file; repeat for several recipes",
    )
    parser.add_argument("--fork", required=True, metavar="OWNER/REPO", help="the fork to push to")
    parser.add_argument("--token", metavar="TOKEN", help="GitHub token; defaults to $GITHUB_TOKEN")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    parser.add_argument("--title", help="pull-request title")
    parser.add_argument("--description", "--body", dest="body", help="pull-request description")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in SubmissionMode],
        default=SubmissionMode.SINGLE.value,
        help="one pull request for all recipes, or one per recipe",
    )
    parser.add_argument("--branch-prefix", default="submit", help="prefix for submission branches")
    parser.add_argument("--upstream", default=DEFAULT_UPSTREAM, metavar="OWNER/REPO")
    parser.add_argument("--base-branch", default=DEFAULT_BASE_BRANCH)
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path(".staged-recipes"),
        help="where the fork is cloned (default: ./.staged-recipes)",
    )
    parser.add_argument(
        "--staged-recipes-root",
        type=Path,
        help="an existing staged-recipes checkout, used to detect packages that already exist",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_request(build_request(args), token=_token_from(args), workdir=args.workdir)
    except SubmissionError as error:
        print(f"staged-recipes-submit: {error}", file=sys.stderr)
        return (
            EXIT_INPUT
            if isinstance(error, ConfigurationError | PathSafetyError | RecipeDiscoveryError)
            else EXIT_FAILURE
        )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.render())
    return EXIT_OK if report.ok else EXIT_INPUT


def build_request(args: argparse.Namespace) -> SubmissionRequest:
    """Translate parsed arguments into a submission request."""
    return SubmissionRequest(
        recipes=tuple(args.recipes),
        fork=args.fork,
        upstream=args.upstream,
        base_branch=args.base_branch,
        mode=SubmissionMode(args.mode),
        title=args.title,
        body=args.body,
        branch_prefix=args.branch_prefix,
        dry_run=args.dry_run,
        staged_recipes_root=args.staged_recipes_root,
    )


def run_request(
    request: SubmissionRequest,
    *,
    token: Secret | None = None,
    workdir: Path | None = None,
) -> SubmissionReport:
    """Run a request against real or guard backends, depending on ``dry_run``."""
    if request.dry_run:
        guard = DryRunGuard()
        return run_submission(request, git=guard, pull_requests=guard)  # type: ignore[arg-type]
    secret = token or _token_from_environment(fork=request.fork)
    git = SubprocessGit(workdir=workdir or DEFAULT_WORKDIR, token=secret)
    pull_requests = GitHubPullRequests(token=secret, upstream=request.upstream)
    return run_submission(request, git=git, pull_requests=pull_requests)


def _token_from(args: argparse.Namespace) -> Secret | None:
    return Secret(args.token) if args.token else None


def _token_from_environment(*, fork: str = "the fork") -> Secret:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name)
        if value:
            return Secret(value)
    raise credentials.missing_token_error(fork=fork, surface="cli")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
