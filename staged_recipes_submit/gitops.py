"""Real Git operations, isolated behind :class:`~.backends.GitBackend`.

Two rules shape this module:

* the token never appears in a command line or a URL, only in an in-process
  ``http.extraheader`` configuration entry;
* nothing is written outside ``recipes/<package-name>``, and an existing recipe
  directory is only replaced when it declares the same package.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from .credentials import remote_hint
from .errors import GitError, Secret
from .models import SubmissionUnit
from .parsing import RECIPE_FILENAMES, parse_recipe
from .paths import JUNK_DIRECTORIES, JUNK_FILES, safe_relative

COMMIT_NAME = "staged-recipes-submit"
COMMIT_EMAIL = "staged-recipes-submit@users.noreply.github.com"


def github_url(slug: str) -> str:
    """Map ``owner/name`` to its clone URL."""
    return f"https://github.com/{slug}.git"


class SubprocessGit:
    """A small, explicit Git backend built on argument vectors."""

    def __init__(
        self,
        *,
        workdir: Path,
        token: Secret | None = None,
        url_for: Callable[[str], str] = github_url,
        git: str = "git",
        timeout: int = 600,
    ) -> None:
        self.workdir = Path(workdir)
        self._token = token
        self._url_for = url_for
        self._git = git
        self._timeout = timeout
        self._base_branch = "main"
        self._fork = "the fork"
        self._remote_exists: dict[str, bool] = {}

    # -- backend protocol -------------------------------------------------
    def prepare(self, *, upstream: str, fork: str, base_branch: str) -> Path:
        self._base_branch = base_branch
        self._fork = fork
        if not (self.workdir / ".git").is_dir():
            self.workdir.parent.mkdir(parents=True, exist_ok=True)
            self._run("clone", self._url_for(fork), str(self.workdir), cwd=self.workdir.parent)
        self._run("remote", "set-url", "origin", self._url_for(fork))
        self._ensure_remote("upstream", self._url_for(upstream))
        self._run("fetch", "--prune", "upstream", base_branch)
        return self.workdir

    def checkout_or_create(self, branch: str) -> None:
        if self.branch_exists(branch):
            self._run("fetch", "origin", f"{branch}:refs/remotes/origin/{branch}")
            self._run("checkout", "--force", "-B", branch, f"refs/remotes/origin/{branch}")
        else:
            self._run(
                "checkout", "--force", "-B", branch, f"refs/remotes/upstream/{self._base_branch}"
            )

    def materialize(self, unit: SubmissionUnit) -> bool:
        changed = False
        for package_name, source in _destinations(unit):
            target = self.workdir / "recipes" / package_name
            safe_relative(self.workdir, Path("recipes") / package_name)
            if target.exists():
                _assert_same_package(target, package_name)
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                source,
                target,
                ignore=lambda _directory, names: [
                    name for name in names if name in JUNK_DIRECTORIES or name in JUNK_FILES
                ],
            )
            status = self._run("status", "--porcelain", "--", f"recipes/{package_name}")
            changed = changed or bool(status.stdout.strip())
        return changed

    def commit(self, message: str) -> bool:
        self._run("add", "--all", "--", "recipes")
        if self._run("diff", "--cached", "--quiet", check=False).returncode == 0:
            return False
        self._run(
            "-c",
            f"user.name={COMMIT_NAME}",
            "-c",
            f"user.email={COMMIT_EMAIL}",
            "commit",
            "--message",
            message,
        )
        return True

    def push(self, branch: str) -> None:
        result = self._run(
            "push", "--force-with-lease", "origin", f"HEAD:refs/heads/{branch}", check=False
        )
        if result.returncode != 0:
            raise GitError(
                f"git push of {branch} failed with exit code {result.returncode}: "
                f"{self._scrub(result.stderr.strip())}",
                hint=remote_hint(result.stderr, fork=self._fork),
            )
        # Reruns in the same process must see the branch they just created.
        self._remote_exists[branch] = True

    # -- helpers ----------------------------------------------------------
    def branch_exists(self, branch: str) -> bool:
        if branch not in self._remote_exists:
            result = self._run("ls-remote", "--exit-code", "--heads", "origin", branch, check=False)
            self._remote_exists[branch] = result.returncode == 0
        return self._remote_exists[branch]

    def _ensure_remote(self, name: str, url: str) -> None:
        remotes = self._run("remote").stdout.split()
        if name in remotes:
            self._run("remote", "set-url", name, url)
        else:
            self._run("remote", "add", name, url)

    def _run(
        self, *args: str, cwd: Path | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        command = [self._git, *args]
        try:
            result = subprocess.run(
                command,
                cwd=cwd or self.workdir,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
                env=self._environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GitError(
                f"git {args[0]} failed: {self._scrub(str(error))}",
                hint="ensure git is installed and the fork is reachable",
            ) from error
        if check and result.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed with exit code {result.returncode}: "
                f"{self._scrub(result.stderr.strip())}",
                hint=remote_hint(result.stderr, fork=self._fork),
            )
        return result

    def _environment(self) -> dict[str, str]:
        import os

        environment = {
            key: value for key, value in os.environ.items() if key not in {"GIT_ASKPASS"}
        }
        environment["GIT_TERMINAL_PROMPT"] = "0"
        if self._token is not None:
            encoded = base64.b64encode(f"x-access-token:{self._token.reveal()}".encode()).decode()
            environment.update(
                GIT_CONFIG_COUNT="1",
                GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {encoded}",
            )
        return environment

    def _scrub(self, text: str) -> str:
        return text.replace(self._token.reveal(), "***") if self._token else text


def _destinations(unit: SubmissionUnit) -> list[tuple[str, Path]]:
    return sorted((recipe.name, recipe.root) for recipe in unit.recipes)


def _assert_same_package(target: Path, package_name: str) -> None:
    for filename in RECIPE_FILENAMES:
        candidate = target / filename
        if candidate.is_file() and parse_recipe(candidate).name == package_name:
            return
    raise GitError(
        f"Refusing to overwrite {target}: it does not declare the package {package_name!r}.",
        hint="remove the directory in your fork or rename the submitted package",
    )
