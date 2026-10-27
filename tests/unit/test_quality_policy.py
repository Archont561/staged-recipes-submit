"""The action contract: run this repository's scripts, publish nothing."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import quality
from common import load_yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def action():
    return load_yaml(ROOT / "action.yml")


def test_the_committed_action_satisfies_the_contract(action) -> None:
    assert quality._check_action_contract(action) == []


def test_the_action_runs_the_shared_dispatcher(action) -> None:
    commands = {
        step["run"].split()[-1]
        for step in action["runs"]["steps"]
        if quality.DISPATCHER in step.get("run", "")
    }
    assert commands == {"action", "summary"}
    assert commands <= quality._dispatcher_commands()


def test_the_action_declares_no_distribution_inputs(action) -> None:
    assert not {"version", "install-from", "wheel-url", "wheel-sha256"} & set(action["inputs"])


def test_a_published_package_is_refused(action) -> None:
    project = (ROOT / "config/project.toml").read_text(encoding="utf-8")
    assert "pypi = false" in project
    assert "release = false" in project


def test_installing_the_checkout_is_refused(action) -> None:
    mutated = copy.deepcopy(action)
    mutated["runs"]["steps"].append(
        {"name": "Install", "shell": "bash", "run": 'python -m pip install "$ACTION_PATH"'}
    )
    errors = quality._check_action_contract(mutated)
    assert any("must not install the checkout" in error for error in errors)


def test_a_step_outside_the_dispatcher_is_refused(action) -> None:
    mutated = copy.deepcopy(action)
    mutated["runs"]["steps"].append(
        {"name": "Rogue", "shell": "bash", "run": "python -m staged_recipes_submit.action_entry"}
    )
    errors = quality._check_action_contract(mutated)
    assert any(
        "must run the dispatcher" in error or "must call the dispatcher" in error
        for error in errors
    )


def test_a_wrong_pythonpath_is_refused(action) -> None:
    mutated = copy.deepcopy(action)
    for step in mutated["runs"]["steps"]:
        if "env" in step and "PYTHONPATH" in step["env"]:
            step["env"]["PYTHONPATH"] = "."
    errors = quality._check_action_contract(mutated)
    assert any("PYTHONPATH" in error for error in errors)


def test_an_unknown_dispatcher_command_is_refused(action) -> None:
    mutated = copy.deepcopy(action)
    for step in mutated["runs"]["steps"]:
        if quality.DISPATCHER in step.get("run", ""):
            step["run"] = 'python "$ACTION_PATH/scripts/run.py" deploy'
    errors = quality._check_action_contract(mutated)
    assert any("deploy" in error for error in errors)


def test_a_non_composite_action_is_refused(action) -> None:
    mutated = copy.deepcopy(action)
    mutated["runs"]["using"] = "node20"
    errors = quality._check_action_contract(mutated)
    assert any("composite" in error for error in errors)


def test_the_missing_summary_step_is_refused(action) -> None:
    mutated = copy.deepcopy(action)
    mutated["runs"]["steps"] = [
        step for step in mutated["runs"]["steps"] if "summary" not in step.get("run", "")
    ]
    errors = quality._check_action_contract(mutated)
    assert any("summary" in error for error in errors)


def test_the_runtime_pin_must_match_the_config(action) -> None:
    pinned = quality.read_toml(ROOT / "config/project.toml")["runtime"]["pyyaml"]
    installs = " ".join(step.get("run", "") for step in action["runs"]["steps"])
    assert f"pyyaml=={pinned}" in installs
    assert quality._check_runtime_pin(action["runs"]["steps"]) == []


def test_a_drifting_runtime_pin_is_refused(action) -> None:
    steps = copy.deepcopy(action["runs"]["steps"])
    for step in steps:
        step["run"] = step.get("run", "").replace("pyyaml==6.0.2", "pyyaml==5.4.1")
    errors = quality._check_runtime_pin(steps)
    assert errors
    assert "pyyaml==6.0.2" in errors[0]


def test_the_workflow_set_is_ci_and_tag_release() -> None:
    assert {"ci.yml", "release.yml"} == quality.REQUIRED_WORKFLOWS
    release_doc = load_yaml(ROOT / ".github/workflows/release.yml")
    assert quality._check_release_workflow(release_doc) == []


def test_release_workflow_rejects_unguarded_writes_and_asset_uploads() -> None:
    release_doc = load_yaml(ROOT / ".github/workflows/release.yml")
    mutated = copy.deepcopy(release_doc)
    mutated["jobs"]["publish"].pop("if")
    mutated["jobs"]["publish"]["steps"].append(
        {"name": "Upload wheel", "run": "pixi run --locked gh release upload"}
    )
    errors = quality._check_release_workflow(mutated)
    assert any("contents: write job must guard" in error for error in errors)
    assert any("forbidden build/asset operation" in error for error in errors)


def test_there_is_no_src_layout() -> None:
    assert not (ROOT / "src").exists()
    assert (ROOT / quality.PACKAGE / "__init__.py").is_file()


def test_the_package_is_importable_from_the_repository_root() -> None:
    import staged_recipes_submit

    assert Path(staged_recipes_submit.__file__).parent.parent == ROOT


def test_no_bootstrap_script_remains_and_release_stays_tag_only() -> None:
    scripts = {path.name for path in (ROOT / "scripts").glob("*.py")}
    assert "bootstrap_action.py" not in scripts
    assert {"run.py", "action.py", "quality.py", "hooks.py", "release.py"} <= scripts


def test_the_token_mapping_is_part_of_the_contract(action) -> None:
    for step in action["runs"]["steps"]:
        if "env" in step and step.get("run", "").rstrip().endswith(" action"):
            step["env"].pop("INPUT_TOKEN")
    errors = quality._check_action_contract(action)
    assert errors
    assert any("INPUT_TOKEN" in error for error in errors)
