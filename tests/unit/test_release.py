"""Unit tests for tag-only release planning and publication (`scripts/release.py`)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import release
from common import AutomationError


def _write_workspace(
    root: Path,
    *,
    version: str = "0.1.0",
    major_tag: str = "v1",
    pypi: str = "false",
    release_flag: str = "false",
    action_flag: str = "true",
) -> Path:
    (root / "config").mkdir(parents=True, exist_ok=True)
    pkg = root / "staged_recipes_submit"
    pkg.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "staged-recipes-submit"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "pixi.toml").write_text(
        f'[workspace]\nname = "staged-recipes-submit"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "config/project.toml").write_text(
        f'[project]\nname = "staged-recipes-submit"\n'
        f'repository = "Archont561/staged-recipes-submit"\nversion = "{version}"\n\n'
        f"[publish]\npypi = {pypi}\nrelease = {release_flag}\naction = {action_flag}\n\n"
        f'[action]\nmajor_tag = "{major_tag}"\n',
        encoding="utf-8",
    )
    (pkg / "_version.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (pkg / "__init__.py").write_text("from ._version import __version__\n", encoding="utf-8")
    return root


def test_load_release_target_reads_committed_workspace() -> None:
    target = release.load_release_target()
    assert target.repository == "Archont561/staged-recipes-submit"
    assert target.version == "0.1.0"
    assert target.tag == "v0.1.0"
    assert target.major_tag == "v1"
    assert target.prerelease is False


def test_prerelease_suppresses_major_tag(tmp_path: Path) -> None:
    root = _write_workspace(tmp_path, version="0.2.0-rc.1")
    target = release.load_release_target(root)
    assert target.prerelease is True
    assert target.tag == "v0.2.0-rc.1"
    assert target.major_tag == ""


def test_incompatible_major_version_is_refused(tmp_path: Path) -> None:
    root = _write_workspace(tmp_path, version="2.0.0", major_tag="v1")
    with pytest.raises(AutomationError, match=r"disagrees with action\.major_tag"):
        release.load_release_target(root)


def test_package_publishing_enabled_is_refused(tmp_path: Path) -> None:
    root = _write_workspace(tmp_path, pypi="true")
    with pytest.raises(AutomationError, match="tag-only"):
        release.load_release_target(root)


def test_inspect_remote_dereferences_annotated_tag(monkeypatch) -> None:
    responses = [
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"object": {"type": "tag", "sha": "tagobj123"}}),
        ),
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"object": {"type": "commit", "sha": "commit456"}}),
        ),
        SimpleNamespace(returncode=0, stdout='{"tagName":"v0.1.0"}'),
    ]
    monkeypatch.setattr(release, "run", lambda *a, **kw: responses.pop(0))
    sha, exists = release.inspect_remote("Archont561/staged-recipes-submit", "v0.1.0")
    assert sha == "commit456"
    assert exists is True


def test_release_plan_marks_new_version_due(tmp_path: Path) -> None:
    root = _write_workspace(tmp_path)
    out = tmp_path / "output.txt"
    code = release.release_plan(
        [],
        env={"HEAD_SHA": "a" * 40, "GITHUB_OUTPUT": str(out)},
        root=root,
        remote=lambda _repo, _tag: (None, False),
    )
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "should_release=true" in text
    assert "tag=v0.1.0" in text
    assert "major_tag=v1" in text


def test_release_plan_skips_when_already_published_on_earlier_commit(tmp_path: Path) -> None:
    root = _write_workspace(tmp_path)
    out = tmp_path / "output.txt"
    code = release.release_plan(
        [],
        env={"HEAD_SHA": "b" * 40, "GITHUB_OUTPUT": str(out)},
        root=root,
        remote=lambda _repo, _tag: ("a" * 40, True),
    )
    assert code == 0
    assert "should_release=false" in out.read_text(encoding="utf-8")


def test_release_plan_honors_dry_run(tmp_path: Path) -> None:
    root = _write_workspace(tmp_path)
    out = tmp_path / "output.txt"
    release.release_plan(
        [],
        env={"HEAD_SHA": "a" * 40, "DRY_RUN": "true", "GITHUB_OUTPUT": str(out)},
        root=root,
        remote=lambda _repo, _tag: (None, False),
    )
    assert "should_release=false" in out.read_text(encoding="utf-8")


def test_release_plan_refuses_mismatched_pushed_tag(tmp_path: Path) -> None:
    root = _write_workspace(tmp_path)
    with pytest.raises(AutomationError, match="disagrees with configured version"):
        release.release_plan(
            [],
            env={"REF_TYPE": "tag", "REF_NAME": "v9.9.9", "HEAD_SHA": "a" * 40},
            root=root,
            remote=lambda _repo, _tag: (None, False),
        )


def test_release_publish_creates_tags_release_and_summary(monkeypatch, tmp_path: Path) -> None:
    root = _write_workspace(tmp_path)
    summary = tmp_path / "summary.md"
    git_calls: list[list[str]] = []
    run_calls: list[list[str]] = []

    def fake_git(args, *, root=None, capture=True, check=True):
        git_calls.append(list(args))
        return SimpleNamespace(stdout="Archont561\n", returncode=0)

    def fake_run(args, **kwargs):
        run_calls.append(list(args))
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(release, "git", fake_git)
    monkeypatch.setattr(release, "run", fake_run)

    sha = "c" * 40
    code = release.release_publish(
        [],
        env={"TARGET_SHA": sha, "GITHUB_STEP_SUMMARY": str(summary)},
        root=root,
        remote=lambda _repo, _tag: (None, False),
    )
    assert code == 0
    assert ["push", "origin", "refs/tags/v0.1.0"] in git_calls
    assert ["push", "--force", "origin", "refs/tags/v1"] in git_calls
    assert any(cmd[:4] == ["gh", "release", "create", "v0.1.0"] for cmd in run_calls)
    assert "Archont561/staged-recipes-submit@v1" in summary.read_text(encoding="utf-8")


def test_release_publish_refuses_to_overwrite_existing_version_tag(tmp_path: Path) -> None:
    root = _write_workspace(tmp_path)
    with pytest.raises(AutomationError, match="Refusing to overwrite existing tag"):
        release.release_publish(
            [],
            env={"TARGET_SHA": "b" * 40},
            root=root,
            remote=lambda _repo, _tag: ("a" * 40, False),
        )
