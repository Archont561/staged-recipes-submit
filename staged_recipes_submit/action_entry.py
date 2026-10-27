"""Translate ``action.yml`` inputs into a submission and publish the outputs.

The composite action inherits its inputs as environment variables so that a
token is never interpolated into a shell command line, and this module writes
the ``$GITHUB_OUTPUT`` / ``$GITHUB_STEP_SUMMARY`` files that follow-up steps use.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path

from . import credentials
from .cli import EXIT_INPUT, EXIT_OK, build_parser, build_request, run_request
from .errors import Secret, SubmissionError
from .models import SubmissionReport

TRUTHY = {"1", "true", "yes"}


def split_paths(value: str) -> list[str]:
    """Split a newline- or comma-separated list of recipe paths."""
    parts = [part.strip() for chunk in value.splitlines() for part in chunk.split(",")]
    return [part for part in parts if part]


def build_argv(environment: Mapping[str, str]) -> list[str]:
    """Build CLI arguments from action inputs."""
    argv = ["--fork", environment.get("INPUT_FORK", "")]
    for path in split_paths(environment.get("INPUT_RECIPES", "")):
        argv += ["--recipe", path]
    if environment.get("INPUT_DRY_RUN", "").strip().lower() in TRUTHY:
        argv.append("--dry-run")
    optional = {
        "INPUT_TITLE": "--title",
        "INPUT_DESCRIPTION": "--description",
        "INPUT_MODE": "--mode",
        "INPUT_BRANCH_PREFIX": "--branch-prefix",
        "INPUT_UPSTREAM": "--upstream",
        "INPUT_BASE_BRANCH": "--base-branch",
    }
    for variable, flag in optional.items():
        value = environment.get(variable, "").strip()
        if value:
            argv += [flag, value]
    return argv


def write_outputs(report: SubmissionReport, path: Path) -> None:
    """Append the action outputs to ``$GITHUB_OUTPUT`` using heredoc syntax."""
    urls = [result.pull_request.url for result in report.results if result.pull_request]
    branches = [result.unit.branch for result in report.results]
    entries = {
        "pull-request-urls": "\n".join(urls),
        "branches": "\n".join(branches),
        "report": _json_report(report),
    }
    with path.open("a", encoding="utf-8") as handle:
        for name, value in entries.items():
            delimiter = f"EOF_{uuid.uuid4().hex}"
            handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def main(environment: Mapping[str, str] | None = None) -> int:
    environment = os.environ if environment is None else environment
    args = build_parser().parse_args(build_argv(environment))
    request = build_request(args)
    try:
        token = _token(environment, fork=request.fork, dry_run=request.dry_run)
    except SubmissionError as error:
        annotate("error", str(error).replace("\n", " "))
        print(f"staged-recipes-submit: {error}", file=sys.stderr)
        return EXIT_INPUT
    try:
        report = run_request(
            request,
            token=token,
            workdir=Path(environment.get("RUNNER_TEMP", ".")) / "staged-recipes",
        )
    except SubmissionError as error:
        annotate("error", str(error).replace("\n", " "))
        print(f"staged-recipes-submit: {error}", file=sys.stderr)
        return EXIT_INPUT
    print(report.render())
    output_path = environment.get("GITHUB_OUTPUT")
    if output_path:
        write_outputs(report, Path(output_path))
    return EXIT_OK if report.ok else EXIT_INPUT


def _token(environment: Mapping[str, str], *, fork: str, dry_run: bool) -> Secret | None:
    """Read ``INPUT_TOKEN``, annotating problems the way a workflow displays them.

    A dry run needs no credentials at all, so an empty token there is not an error.
    """
    value = (environment.get("INPUT_TOKEN") or "").strip()
    if not value:
        if dry_run:
            return None
        raise credentials.missing_token_error(fork=fork, surface="action")
    for warning in credentials.warnings(value, fork=fork):
        annotate("warning", warning)
    return Secret(value)


def annotate(level: str, message: str) -> None:
    """Emit a GitHub Actions annotation so the message survives a later failure."""
    print(f"::{level}::{_escape(message)}", file=sys.stderr)


def _escape(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def _json_report(report: SubmissionReport) -> str:
    import json

    return json.dumps(report.to_dict(), separators=(",", ":"))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
