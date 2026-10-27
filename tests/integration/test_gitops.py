"""Git operations against a real (local) bare repository."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from staged_recipes_submit.discovery import discover_recipes
from staged_recipes_submit.errors import GitError
from staged_recipes_submit.gitops import SubprocessGit
from staged_recipes_submit.models import SubmissionUnit
from staged_recipes_submit.plan import build_plan, commit_message
from support import FakePullRequests, write_recipe


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout


@pytest.fixture
def bare_fork(tmp_path: Path) -> Path:
    bare = tmp_path / "fork.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(bare))
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "--initial-branch=main")
    (seed / "README.md").write_text("staged-recipes\n")
    _git(seed, "add", ".")
    _git(
        seed,
        "-c",
        "user.name=seed",
        "-c",
        "user.email=seed@example.invalid",
        "commit",
        "-m",
        "init",
    )
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "origin", "main")
    return bare


@pytest.fixture
def backend(tmp_path: Path, bare_fork: Path) -> SubprocessGit:
    return SubprocessGit(workdir=tmp_path / "checkout", url_for=lambda _slug: str(bare_fork))


def _unit(recipes_dir: Path, name: str = "alpha") -> SubmissionUnit:
    (unit,) = build_plan(discover_recipes([write_recipe(recipes_dir, name)]))
    return unit


def test_prepare_is_idempotent(backend: SubprocessGit) -> None:
    first = backend.prepare(
        upstream="conda-forge/staged-recipes", fork="me/fork", base_branch="main"
    )
    second = backend.prepare(
        upstream="conda-forge/staged-recipes", fork="me/fork", base_branch="main"
    )
    assert first == second
    remotes = _git(first, "remote").split()
    assert {"origin", "upstream"} <= set(remotes)


def test_materialize_commit_and_push(
    backend: SubprocessGit, tmp_path: Path, bare_fork: Path
) -> None:
    unit = _unit(tmp_path)
    backend.prepare(upstream="conda-forge/staged-recipes", fork="me/fork", base_branch="main")
    backend.checkout_or_create(unit.branch)
    assert backend.materialize(unit) is True
    assert backend.commit(commit_message(unit)) is True
    assert backend.commit(commit_message(unit)) is False
    backend.push(unit.branch)

    heads = _git(tmp_path, "ls-remote", "--heads", str(bare_fork))
    assert "refs/heads/submit/alpha" in heads
    tree = _git(bare_fork, "ls-tree", "-r", "--name-only", "submit/alpha")
    assert "recipes/alpha/recipe.yaml" in tree
    assert "README.md" in tree


def test_branch_exists_reflects_the_remote(backend: SubprocessGit, tmp_path: Path) -> None:
    unit = _unit(tmp_path)
    backend.prepare(upstream="conda-forge/staged-recipes", fork="me/fork", base_branch="main")
    assert backend.branch_exists(unit.branch) is False
    backend.checkout_or_create(unit.branch)
    backend.materialize(unit)
    backend.commit(commit_message(unit))
    backend.push(unit.branch)
    assert (
        SubprocessGit(
            workdir=backend.workdir,
            url_for=lambda _slug: str(Path(backend.workdir).parent / "fork.git"),
        ).branch_exists(unit.branch)
        is True
    )


def test_second_checkout_reuses_the_pushed_branch(backend: SubprocessGit, tmp_path: Path) -> None:
    unit = _unit(tmp_path)
    backend.prepare(upstream="conda-forge/staged-recipes", fork="me/fork", base_branch="main")
    backend.checkout_or_create(unit.branch)
    backend.materialize(unit)
    backend.commit(commit_message(unit))
    backend.push(unit.branch)
    backend.checkout_or_create(unit.branch)
    assert backend.materialize(unit) is False


def test_refuses_to_overwrite_an_unrelated_recipe(backend: SubprocessGit, tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    (seed / "recipes" / "alpha").mkdir(parents=True)
    (seed / "recipes" / "alpha" / "recipe.yaml").write_text(
        "package:\n  name: something-else\n  version: '1.0'\n", encoding="utf-8"
    )
    _git(seed, "add", "recipes")
    _git(seed, "-c", "user.name=seed", "-c", "user.email=s@e.invalid", "commit", "-m", "conflict")
    _git(seed, "push", "origin", "main")

    unit = _unit(tmp_path)
    backend.prepare(upstream="conda-forge/staged-recipes", fork="me/fork", base_branch="main")
    backend.checkout_or_create(unit.branch)
    with pytest.raises(GitError, match="Refusing to overwrite"):
        backend.materialize(unit)


def test_git_failures_are_actionable(tmp_path: Path) -> None:
    backend = SubprocessGit(workdir=tmp_path / "missing", url_for=lambda slug: str(tmp_path / slug))
    with pytest.raises(GitError, match=r"git clone .* failed"):
        backend.prepare(upstream="x/y", fork="nope/nope", base_branch="main")


def test_run_submission_writes_a_real_branch(
    backend: SubprocessGit, tmp_path: Path, bare_fork: Path
) -> None:
    from staged_recipes_submit.submit import SubmissionRequest, run_submission

    recipe = write_recipe(tmp_path, "alpha")
    request = SubmissionRequest(recipes=(recipe,), fork="me/fork")
    pull_requests = FakePullRequests()
    report = run_submission(request, git=backend, pull_requests=pull_requests)

    assert report.ok
    assert "refs/heads/submit/alpha" in _git(tmp_path, "ls-remote", "--heads", str(bare_fork))
    assert pull_requests.created[0].head == "submit/alpha"


def test_a_rejected_push_explains_the_credential_problem(tmp_path: Path) -> None:
    """A push rejected for auth reasons says which credential to fix, not just "exit 1"."""
    fake = tmp_path / "git"
    fake.write_text(
        "#!/bin/sh\n"
        'for arg in "$@"; do\n'
        '  if [ "$arg" = "push" ]; then\n'
        '    echo "remote: Permission to me/fork.git denied." >&2\n'
        "    exit 128\n"
        "  fi\n"
        "done\n"
        'if [ "$1" = "remote" ]; then echo "origin upstream"; fi\n'
        "exit 0\n"
    )
    fake.chmod(0o755)
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    backend = SubprocessGit(workdir=checkout, git=str(fake))
    backend.prepare(upstream="conda-forge/staged-recipes", fork="me/fork", base_branch="main")
    with pytest.raises(GitError) as error:
        backend.push("submit/alpha")
    assert "me/fork" in error.value.message
    assert "cannot write to me/fork" in (error.value.hint or "")
