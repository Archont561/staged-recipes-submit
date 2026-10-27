"""Git hooks: conventional commits, staged-file linting, and pre-push tests."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from common import ROOT, AutomationError, git, run

TYPES = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
)
CONVENTIONAL = re.compile(rf"^(?:{'|'.join(TYPES)})(?:\([a-z0-9-]+\))?!?: [^\n]{{3,72}}$")
IGNORED_SUBJECTS = ("Merge ", "fixup! ", "squash! ", 'Revert "')
WATCHED = (
    "staged_recipes_submit/",
    "tests/",
    "scripts/",
    "action.yml",
    "pyproject.toml",
    "pixi.toml",
)


def check_message(message: str) -> None:
    """Refuse a commit message that is not a conventional commit."""
    subject = next((line.strip() for line in message.splitlines() if line.strip()), "")
    if not subject:
        raise AutomationError("The commit message is empty.", hint="write '<type>: <summary>'")
    if subject.startswith(IGNORED_SUBJECTS):
        return
    if not CONVENTIONAL.match(subject):
        raise AutomationError(
            f"Commit message does not follow Conventional Commits: {subject!r}",
            hint=f"use '<type>: <summary>' with type in {', '.join(TYPES)}",
        )


def hook_commit_msg(args):
    if len(args) != 1:
        raise AutomationError("hook-commit-msg expects the commit-message file path.")
    text = Path(args[0]).read_text(encoding="utf-8")
    kept = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    check_message(kept)


def _staged_paths():
    output = git(["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]).stdout
    return [path for path in output.split("\0") if path]


def hook_pre_commit(_args):
    git(["diff", "--cached", "--check"])
    staged = _staged_paths()
    python_files = [path for path in staged if path.endswith(".py")]
    if not python_files:
        print("No staged Python files; Python pre-commit checks skipped.")
        return
    run(["ruff", "check", "--force-exclude", *python_files])
    run(["ruff", "format", "--check", "--force-exclude", *python_files])
    print(f"Checked {len(python_files)} staged Python file(s).")


def parse_push_updates(text):
    """Parse the four-field lines Git writes to a pre-push hook."""
    updates = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 4:
            raise AutomationError("Invalid pre-push input: expected four fields per line.")
        updates.append(tuple(fields))
    return updates


def hook_pre_push(_args):
    import sys

    updates = parse_push_updates(sys.stdin.read())
    touched: set[str] = set()
    for _local_ref, local_sha, _remote_ref, remote_sha in updates:
        zero = set(remote_sha) == {"0"}
        if zero:
            # A new ref has no remote base: every file in the pushed tree is new to it.
            output = git(["ls-tree", "-r", "--name-only", "-z", local_sha]).stdout
            revision_range = [local_sha]
        else:
            range_spec = f"{remote_sha}..{local_sha}"
            output = git(["diff", "--name-only", "-z", range_spec]).stdout
            revision_range = [range_spec]
        touched |= {path for path in output.split("\0") if path}
        # Every outgoing commit message must be conventional.
        for commit in git(["rev-list", *revision_range]).stdout.split():
            message = git(["show", "-s", "--format=%B", commit]).stdout
            subject = message.splitlines()[0] if message.splitlines() else ""
            if subject.startswith(IGNORED_SUBJECTS) or _is_initial_root_commit(commit, subject):
                continue
            check_message(message)
    if not any(path.startswith(WATCHED) for path in touched):
        print("No source changes in this push; tests skipped.")
        return
    run(["python", "-m", "pytest", "-q"], cwd=ROOT)
    print("Pre-push tests passed.")


def _is_initial_root_commit(commit: str, subject: str) -> bool:
    if subject != "Initial commit":
        return False
    return len(git(["rev-list", "--parents", "-n", "1", commit]).stdout.split()) == 1


def commit_check(args):
    options = _parse_options(args)
    base = options.get("--base")
    head = options.get("--head", "HEAD")
    if not base:
        raise AutomationError("commit-check expects --base <sha> [--head <sha>].")
    zero = set(base) == {"0"}
    revisions = [head] if zero else [f"{base}..{head}"]
    commits = git(["rev-list", *revisions]).stdout.split()
    for commit in commits:
        message = git(["show", "-s", "--format=%B", commit]).stdout
        subject = message.splitlines()[0] if message.splitlines() else ""
        if subject.startswith(IGNORED_SUBJECTS) or _is_initial_root_commit(commit, subject):
            continue
        check_message(message)
    print(f"Validated {len(commits)} commit message(s).")


def _parse_options(args):
    options = {}
    index = 0
    while index < len(args):
        option = args[index]
        if not option.startswith("--") or index + 1 >= len(args):
            raise AutomationError(f"Unsupported argument: {option}")
        options[option] = args[index + 1]
        index += 2
    return options


def watched(path: str) -> bool:
    return PurePosixPath(path).as_posix().startswith(WATCHED)
