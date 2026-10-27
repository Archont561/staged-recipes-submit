"""Tag-only release automation for the composite GitHub Action.

Nothing is built or uploaded to a package index: a release consists solely of
verifying version parity and CI gates, pushing the immutable ``v<version>`` tag,
advancing the configured major tag (for stable releases), and creating an
assetless GitHub Release with generated notes.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import quality
from common import ROOT, AutomationError, git, read_toml, run

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?$")
MAJOR_TAG = re.compile(r"^v(0|[1-9]\d*)$")
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


@dataclass(frozen=True)
class ReleaseTarget:
    """Resolved release identity read from ``config/project.toml``."""

    repository: str
    version: str
    tag: str
    major_tag: str
    prerelease: bool


RemoteInspector = Callable[[str, str], tuple[str | None, bool]]


def load_release_target(root: Path = ROOT) -> ReleaseTarget:
    """Validate version parity and publish policy, returning the release target."""
    errors = _check_versions_at(root)
    if errors:
        raise AutomationError("; ".join(errors))

    config = read_toml(root / "config/project.toml")
    project = config.get("project", {})
    publish = config.get("publish", {})
    if publish.get("pypi") is not False or publish.get("release") is not False:
        raise AutomationError(
            "config/project.toml enables package or asset publishing; "
            "scripts/release.py is tag-only."
        )
    if publish.get("action") is not True:
        raise AutomationError("config/project.toml must set publish.action = true.")

    version = str(project.get("version", "")).strip()
    match = SEMVER.fullmatch(version)
    if match is None:
        raise AutomationError(
            f"Invalid semantic version {version!r}; expected MAJOR.MINOR.PATCH[-PRERELEASE]."
        )
    major = int(match.group(1))
    prerelease = match.group(4) is not None
    configured_major = str(config.get("action", {}).get("major_tag", "")).strip()
    major_tag = ""
    if configured_major and not prerelease:
        major_match = MAJOR_TAG.fullmatch(configured_major)
        if major_match is None:
            raise AutomationError(
                f"Invalid action.major_tag {configured_major!r}; expected 'v<major>'."
            )
        major_line = int(major_match.group(1))
        compatible = (major_line == 1 and major in (0, 1)) or major == major_line
        if not compatible:
            raise AutomationError(
                f"Version {version} disagrees with action.major_tag {configured_major!r}; "
                "update [action].major_tag in config/project.toml."
            )
        major_tag = configured_major

    repository = str(project.get("repository", "")).strip()
    if "/" not in repository:
        raise AutomationError("config/project.toml must declare project.repository as owner/repo.")

    return ReleaseTarget(
        repository=repository,
        version=version,
        tag=f"v{version}",
        major_tag=major_tag,
        prerelease=prerelease,
    )


def _check_versions_at(root: Path) -> list[str]:
    if root == ROOT:
        return list(quality._check_versions())
    project = read_toml(root / "pyproject.toml")["project"]["version"]
    manifest = read_toml(root / "pixi.toml")["workspace"]["version"]
    identity = read_toml(root / "config/project.toml")["project"]["version"]
    source = (root / quality.PACKAGE / "_version.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"', source, re.MULTILINE)
    if match is None:
        return [f"{quality.PACKAGE}/_version.py has no __version__"]
    reexport = (root / quality.PACKAGE / "__init__.py").read_text(encoding="utf-8")
    if "from ._version import __version__" not in reexport:
        return [f"{quality.PACKAGE}/__init__.py must re-export __version__ from _version.py"]
    versions = {project, manifest, identity, match.group(1)}
    if len(versions) != 1:
        return [f"versions disagree: {sorted(versions)}"]
    return []


def inspect_remote(repository: str, tag: str) -> tuple[str | None, bool]:
    """Return ``(tag_commit_sha_or_none, github_release_exists)`` from GitHub."""
    ref = run(
        ["gh", "api", f"repos/{repository}/git/ref/tags/{tag}"],
        capture=True,
        check=False,
    )
    tag_sha: str | None = None
    if ref.returncode == 0 and ref.stdout.strip():
        payload = json.loads(ref.stdout)
        obj = payload.get("object", {})
        sha = obj.get("sha")
        if obj.get("type") == "tag" and sha:
            annotated = run(
                ["gh", "api", f"repos/{repository}/git/tags/{sha}"],
                capture=True,
                check=False,
            )
            if annotated.returncode == 0 and annotated.stdout.strip():
                sha = json.loads(annotated.stdout).get("object", {}).get("sha", sha)
        tag_sha = sha

    release = run(
        ["gh", "release", "view", tag, "--repo", repository, "--json", "tagName"],
        capture=True,
        check=False,
    )
    return tag_sha, release.returncode == 0


def release_plan(
    args: list[str],
    *,
    env: Mapping[str, str] | None = None,
    root: Path = ROOT,
    remote: RemoteInspector = inspect_remote,
) -> int:
    """Decide whether a release is due and write step outputs when in Actions."""
    if args:
        raise AutomationError("release-plan takes no positional arguments.")
    environment = os.environ if env is None else env
    target = load_release_target(root)
    repository = environment.get("GITHUB_REPOSITORY", "").strip() or target.repository
    ref_type = environment.get("REF_TYPE", "").strip()
    ref_name = environment.get("REF_NAME", "").strip()
    dry_run = environment.get("DRY_RUN", "false").strip().lower() == "true"
    head_sha = (
        environment.get("HEAD_SHA", "").strip()
        or git(["rev-parse", "HEAD"], root=root).stdout.strip()
    )

    if ref_type == "tag" and ref_name != target.tag:
        raise AutomationError(
            f"Pushed tag {ref_name!r} disagrees with configured version {target.version!r} "
            f"(expected {target.tag!r})."
        )

    tag_sha, release_exists = remote(repository, target.tag)
    if tag_sha is not None and tag_sha != head_sha:
        if ref_type == "tag":
            raise AutomationError(
                f"Tag {target.tag} resolves to {tag_sha}, expected HEAD {head_sha}."
            )
        should_release = False
        print(
            f"Tag {target.tag} already exists at {tag_sha[:7]} (HEAD is {head_sha[:7]}); "
            "bump the project version to cut a new release."
        )
    elif tag_sha is not None and release_exists:
        should_release = False
        print(f"Release {target.tag} is already published at {tag_sha[:7]}; nothing to do.")
    elif dry_run:
        should_release = False
        print(
            f"Dry run: {target.tag} at {head_sha[:7]} is ready to release "
            f"(major tag: {target.major_tag or 'none'})."
        )
    else:
        should_release = True
        print(
            f"Release {target.tag} at {head_sha[:7]} is due "
            f"(major tag: {target.major_tag or 'none'})."
        )

    _write_outputs(
        environment.get("GITHUB_OUTPUT"),
        {
            "should_release": "true" if should_release else "false",
            "version": target.version,
            "tag": target.tag,
            "major_tag": target.major_tag,
        },
    )
    return 0


def release_publish(
    args: list[str],
    *,
    env: Mapping[str, str] | None = None,
    root: Path = ROOT,
    remote: RemoteInspector = inspect_remote,
) -> int:
    """Push the version tag, advance the major tag, and create the GitHub Release."""
    if args:
        raise AutomationError("release-publish takes no positional arguments.")
    environment = os.environ if env is None else env
    target = load_release_target(root)
    repository = environment.get("GITHUB_REPOSITORY", "").strip() or target.repository
    requested_tag = environment.get("RELEASE_TAG", "").strip() or target.tag
    if requested_tag != target.tag:
        raise AutomationError(
            f"RELEASE_TAG {requested_tag!r} disagrees with configured {target.tag!r}."
        )
    major_tag = environment.get("MAJOR_TAG", target.major_tag).strip()
    if target.prerelease and major_tag:
        raise AutomationError("Prereleases must not move the major tag.")
    if major_tag and major_tag != target.major_tag:
        raise AutomationError(
            f"MAJOR_TAG {major_tag!r} disagrees with configured {target.major_tag!r}."
        )

    target_sha = (
        environment.get("TARGET_SHA", "").strip()
        or git(["rev-parse", "HEAD"], root=root).stdout.strip()
    )
    tag_sha, release_exists = remote(repository, target.tag)
    if tag_sha is not None and tag_sha != target_sha:
        raise AutomationError(
            f"Refusing to overwrite existing tag {target.tag} ({tag_sha} != {target_sha})."
        )

    _ensure_git_identity(root)

    if tag_sha is None:
        git(
            ["tag", "-a", "-f", target.tag, target_sha, "-m", f"Release {target.tag}"],
            root=root,
        )
        git(["push", "origin", f"refs/tags/{target.tag}"], root=root)
        print(f"Pushed tag {target.tag} -> {target_sha}.")
    else:
        print(f"Tag {target.tag} already points to {target_sha}.")

    if major_tag:
        git(
            ["tag", "-a", "-f", major_tag, target_sha, "-m", f"Move {major_tag} to {target.tag}"],
            root=root,
        )
        git(["push", "--force", "origin", f"refs/tags/{major_tag}"], root=root)
        print(f"Moved major tag {major_tag} -> {target.tag} ({target_sha}).")

    if not release_exists:
        command = [
            "gh",
            "release",
            "create",
            target.tag,
            "--repo",
            repository,
            "--verify-tag",
            "--title",
            target.tag,
            "--generate-notes",
        ]
        if target.prerelease:
            command.append("--prerelease")
        run(command, cwd=root)
        print(f"Created GitHub Release {target.tag}.")
    else:
        print(f"GitHub Release {target.tag} already exists.")

    _write_summary(
        environment.get("GITHUB_STEP_SUMMARY"),
        repository=repository,
        target=target,
        major_tag=major_tag,
        target_sha=target_sha,
    )
    return 0


def _ensure_git_identity(root: Path) -> None:
    name = git(["config", "--get", "user.name"], root=root, check=False).stdout.strip()
    email = git(["config", "--get", "user.email"], root=root, check=False).stdout.strip()
    if not name:
        git(["config", "user.name", BOT_NAME], root=root)
    if not email:
        git(["config", "user.email", BOT_EMAIL], root=root)


def _write_outputs(output_path: str | None, values: Mapping[str, str]) -> None:
    if not output_path:
        return
    lines = [f"{key}={value}\n" for key, value in values.items()]
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.writelines(lines)


def _write_summary(
    summary_path: str | None,
    *,
    repository: str,
    target: ReleaseTarget,
    major_tag: str,
    target_sha: str,
) -> None:
    if not summary_path:
        return
    pin_ref = major_tag or target.tag
    body = (
        f"## Released `{target.tag}`\n\n"
        f"| Field | Value |\n"
        f"| --- | --- |\n"
        f"| Version | `{target.version}` |\n"
        f"| Immutable tag | `{target.tag}` |\n"
        f"| Moving major tag | `{major_tag or '—'}` |\n"
        f"| Commit | `{target_sha}` |\n"
        f"| Consumer reference | `uses: {repository}@{pin_ref}` |\n"
    )
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write(body)
