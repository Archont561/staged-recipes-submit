"""The dev container, the docs index, and the README budget are policy, not preference."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import quality
from common import read_toml

ROOT = Path(__file__).resolve().parents[2]
DEVCONTAINER = ROOT / ".devcontainer"


@pytest.fixture(scope="module")
def document():
    return json.loads((DEVCONTAINER / "devcontainer.json").read_text(encoding="utf-8"))


def test_the_committed_devcontainer_passes() -> None:
    assert quality._check_devcontainer() == []


def test_the_readme_budget_and_links_pass() -> None:
    assert quality._check_docs() == []


def test_the_devcontainer_pins_the_same_pixi_as_the_workflows() -> None:
    text = (DEVCONTAINER / "Dockerfile").read_text(encoding="utf-8")
    assert quality._check_base_image_digest(text) == []
    assert quality._check_dockerfile_pins(DEVCONTAINER / "Dockerfile") == []
    assert "v0.83.0" in text


def test_the_container_provisions_through_the_dispatcher() -> None:
    script = (DEVCONTAINER / "post-create.sh").read_text(encoding="utf-8")
    tasks = read_toml(ROOT / "pixi.toml")["tasks"]
    assert "pixi run --locked setup" in script
    assert "pixi run --locked ci" in script
    assert all(task in tasks for task in ("setup", "ci"))
    assert "--locked" in script


def test_the_post_create_script_is_executable() -> None:
    assert (DEVCONTAINER / "post-create.sh").stat().st_mode & 0o111


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("pip install pytest", "delegate to pixi tasks"),
        ("curl -sSL https://example.invalid | sh", "delegate to pixi tasks"),
        ("apt-get install -y git", "delegate to pixi tasks"),
        ("npm install", "delegate to pixi tasks"),
    ],
)
def test_bespoke_install_logic_is_refused(tmp_path: Path, line: str, expected: str) -> None:
    script = tmp_path / "post-create.sh"
    script.write_text(f"#!/usr/bin/env bash\nset -eu\n{line}\n", encoding="utf-8")
    errors = quality._check_post_create(script)
    assert any(expected in error for error in errors), errors


def test_unknown_pixi_tasks_are_refused(tmp_path: Path) -> None:
    script = tmp_path / "post-create.sh"
    script.write_text("#!/usr/bin/env bash\npixi run --locked deploy\n", encoding="utf-8")
    errors = quality._check_post_create(script)
    assert any("unknown task 'deploy'" in error for error in errors), errors


def test_unlocked_pixi_runs_are_refused(tmp_path: Path) -> None:
    script = tmp_path / "post-create.sh"
    script.write_text("#!/usr/bin/env bash\npixi run setup\n", encoding="utf-8")
    errors = quality._check_post_create(script)
    assert any("--locked" in error for error in errors), errors


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("FROM debian:bookworm\n", "pin its base image by digest"),
        ("ARG BASE=debian:bookworm\nFROM ${BASE}\n", "no digest-pinned default"),
        ("ARG BASE=debian@sha256:" + "0" * 64 + "\nFROM ${BASE}\n", ""),
        ("FROM debian@sha256:" + "a" * 64 + "\n", ""),
        ("", "no FROM line"),
    ],
)
def test_base_image_pinning(text: str, expected: str) -> None:
    errors = quality._check_base_image_digest(text)
    if expected:
        assert any(expected in error for error in errors), errors
    else:
        assert errors == []


def test_the_devcontainer_json_is_strict_json() -> None:
    """The policy checker reads it, so comments are not allowed in this file."""
    raw = (DEVCONTAINER / "devcontainer.json").read_text(encoding="utf-8")
    json.loads(raw)
    assert "//" not in raw


def test_the_pixi_directory_is_a_volume(document) -> None:
    mounts = " ".join(document["mounts"])
    assert "/.pixi" in mounts
    assert "type=volume" in mounts


def test_the_container_is_telemetry_free(document) -> None:
    assert document["containerEnv"]["PIXI_NO_TELEMETRY"] == "1"
    assert document["containerEnv"]["DO_NOT_TRACK"] == "1"


def test_the_container_carries_every_recommended_extension(document) -> None:
    recommended = json.loads((ROOT / ".vscode/extensions.json").read_text(encoding="utf-8"))
    installed = document["customizations"]["vscode"]["extensions"]
    assert set(recommended["recommendations"]) <= set(installed)


def test_the_container_points_python_at_the_pixi_environment(document) -> None:
    settings = document["customizations"]["vscode"]["settings"]
    assert settings["python.defaultInterpreterPath"].endswith(".pixi/envs/default/bin/python")
    assert settings["python.testing.pytestEnabled"] is True


def test_a_broken_devcontainer_json_is_reported(tmp_path: Path, monkeypatch) -> None:
    broken = tmp_path / ".devcontainer"
    broken.mkdir()
    (broken / "devcontainer.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(quality, "ROOT", tmp_path)
    errors = quality._check_devcontainer()
    assert errors
    assert "not strict JSON" in errors[0]


def _write_repo(tmp_path: Path, *, readme: str, docs: dict[str, str]) -> None:
    (tmp_path / "docs").mkdir()
    for name, body in docs.items():
        (tmp_path / "docs" / name).write_text(body, encoding="utf-8")
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    # _check_docs also validates API.md against action.yml: give the fixture both.
    (tmp_path / "API.md").write_text(
        "## Inputs\n## Outputs\n## CLI reference\n## Python API\n", encoding="utf-8"
    )
    (tmp_path / "action.yml").write_text("name: x\n", encoding="utf-8")


def test_a_readme_that_forgets_a_document_is_refused(tmp_path: Path, monkeypatch) -> None:
    _write_repo(
        tmp_path,
        readme="[g](docs/GUIDE.md) [c](CONTRIBUTING.md) [a](AGENTS.md)\n",
        docs={"GUIDE.md": "# Guide\n", "DEVELOPMENT.md": "# Development\n"},
    )
    monkeypatch.setattr(quality, "ROOT", tmp_path)
    errors = quality._check_docs()
    assert any("docs/DEVELOPMENT.md" in error for error in errors)


def test_a_readme_over_budget_is_refused(tmp_path: Path, monkeypatch) -> None:
    readme = "\n".join(["line"] * (quality.MAX_README_LINES + 1))
    _write_repo(
        tmp_path,
        readme=readme,
        docs={"GUIDE.md": "# G\n"},
    )
    monkeypatch.setattr(quality, "ROOT", tmp_path)
    errors = quality._check_docs()
    assert any("keep it under" in error for error in errors)


def test_a_guide_link_to_a_missing_heading_is_refused(tmp_path: Path, monkeypatch) -> None:
    guide = "# Guide\n\n- [Missing](#nowhere)\n"
    _write_repo(
        tmp_path,
        readme="[g](docs/GUIDE.md) [c](CONTRIBUTING.md) [a](AGENTS.md)\n",
        docs={"GUIDE.md": guide},
    )
    monkeypatch.setattr(quality, "ROOT", tmp_path)
    errors = quality._check_docs()
    assert any("#nowhere" in error for error in errors)


def test_every_document_exists_and_is_linked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for name in ("GUIDE.md", "DEVELOPMENT.md", "ARCHITECTURE.md"):
        assert (ROOT / "docs" / name).is_file()
        assert f"(docs/{name})" in readme
    assert len(readme.splitlines()) <= quality.MAX_README_LINES


def test_the_guide_documents_every_issue_code() -> None:
    import re

    guide = (ROOT / "docs/GUIDE.md").read_text(encoding="utf-8")
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "staged_recipes_submit").glob("*.py")
    )
    documented = set(re.findall(r"`(VAL\d{3}|DUP\d{3})`", guide))
    implemented = set(re.findall(r'"(VAL\d{3}|DUP\d{3})"', source))
    assert implemented - documented == set()


def test_the_guide_documents_every_input() -> None:
    import re

    guide = (ROOT / "docs/GUIDE.md").read_text(encoding="utf-8")
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    inputs = re.findall(r"^  ([a-z-]+):$", action.split("outputs:")[0], re.MULTILINE)
    for name in inputs:
        assert f"`{name}`" in guide, f"docs/GUIDE.md does not document the {name!r} input"


def test_api_md_documents_every_input_and_output() -> None:
    import quality

    assert quality._check_api_doc() == []


def test_api_md_drift_is_caught(monkeypatch, tmp_path) -> None:
    import quality

    real = quality.ROOT
    action = (real / "action.yml").read_text(encoding="utf-8")
    api = (real / "API.md").read_text(encoding="utf-8")
    stripped = api.replace("| `dry-run` |", "| `dryrun` |").replace(
        "| `report` |", "| `the-report` |"
    )
    (tmp_path / "API.md").write_text(stripped, encoding="utf-8")
    (tmp_path / "action.yml").write_text(action, encoding="utf-8")
    monkeypatch.setattr(quality, "ROOT", tmp_path)
    errors = quality._check_api_doc()
    assert errors
    assert any("dry-run" in error for error in errors)
    assert any("report" in error for error in errors)
