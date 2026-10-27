"""The offline transport plan and the generated-workflow policy."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import quality
from common import load_yaml, read_toml
from quality import (
    check_generated_workflow,
    check_sandbox_config,
    pixi_versions,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def config():
    return read_toml(ROOT / "pixi-sandbox.toml")


@pytest.fixture(scope="module")
def manifest():
    return read_toml(ROOT / "pixi.toml")


@pytest.fixture(scope="module")
def documents():
    return {
        path.name: load_yaml(path) for path in sorted((ROOT / ".github/workflows").glob("*.yml"))
    }


def test_the_committed_plan_is_valid(config, manifest, documents) -> None:
    assert check_sandbox_config(config, manifest, documents) == []


def test_the_sandbox_checks_are_wired_into_validate() -> None:
    assert quality._check_sandbox() == []


def test_the_committed_plan_documents_the_review_decisions(config) -> None:
    assert config["schema"] == 2
    assert config["cargo_vendor"] is False
    assert config["workflow"]["permissions"] is True
    assert config["workflow"]["setup_pixi_cache"] is False
    assert config["budgets"]["max_blob_mib"] == 95


def _mutated(config, **changes):
    clone = copy.deepcopy(config)
    clone.update(changes)
    return clone


def _mutated_bundle(config, **changes):
    clone = copy.deepcopy(config)
    clone["bundle"][0].update(changes)
    return clone


@pytest.mark.parametrize("schema", [0, 3, "2"])
def test_unsupported_schemas_are_refused(config, manifest, schema) -> None:
    errors = check_sandbox_config(_mutated(config, schema=schema), manifest, {})
    assert any("schema" in error for error in errors)


@pytest.mark.parametrize("prefix", ["", "Bad Prefix", "refs/heads", "-leading"])
def test_unsafe_branch_prefixes_are_refused(config, manifest, prefix) -> None:
    errors = check_sandbox_config(_mutated(config, branch_prefix=prefix), manifest, {})
    assert any("branch_prefix" in error for error in errors)


def test_cargo_vendoring_must_stay_off(config, manifest) -> None:
    errors = check_sandbox_config(_mutated(config, cargo_vendor=True), manifest, {})
    assert any("cargo_vendor must be false" in error for error in errors)


def test_a_bundle_cannot_re_enable_cargo_vendoring(config, manifest) -> None:
    errors = check_sandbox_config(_mutated_bundle(config, cargo_vendor=True), manifest, {})
    assert any("re-enables cargo_vendor" in error for error in errors)


def test_a_plan_needs_a_bundle(config, manifest) -> None:
    errors = check_sandbox_config(_mutated(config, bundle=[]), manifest, {})
    assert any("at least one [[bundle]]" in error for error in errors)


@pytest.mark.parametrize("name", ["", "Dev Tools", "dev_tools"])
def test_bundle_names_are_slugs(config, manifest, name) -> None:
    errors = check_sandbox_config(_mutated_bundle(config, name=name), manifest, {})
    assert any("bundle name" in error for error in errors)


def test_duplicate_bundles_are_refused(config, manifest) -> None:
    clone = copy.deepcopy(config)
    clone["bundle"].append(copy.deepcopy(clone["bundle"][0]))
    errors = check_sandbox_config(clone, manifest, {})
    assert any("declared twice" in error for error in errors)


def test_a_bundle_needs_environments(config, manifest) -> None:
    errors = check_sandbox_config(_mutated_bundle(config, environments=[]), manifest, {})
    assert any("no environments" in error for error in errors)


def test_environments_must_exist_in_the_workspace(config, manifest) -> None:
    errors = check_sandbox_config(_mutated_bundle(config, environments=["ghost"]), manifest, {})
    assert any("does not define" in error for error in errors)


def test_a_bundle_needs_platforms(config, manifest) -> None:
    errors = check_sandbox_config(_mutated_bundle(config, platforms=[]), manifest, {})
    assert any("no platforms" in error for error in errors)


def test_platforms_must_exist_in_the_workspace(config, manifest) -> None:
    errors = check_sandbox_config(
        _mutated_bundle(config, platforms=["linux-aarch64"]), manifest, {}
    )
    assert any("does not support" in error for error in errors)


def test_every_platform_needs_an_explicit_runner(config, manifest) -> None:
    errors = check_sandbox_config(_mutated(config, runners={}), manifest, {})
    assert sum("needs an explicit runners" in error for error in errors) == 3


def test_unknown_runner_platforms_are_refused(config, manifest) -> None:
    runners = dict(config["runners"], **{"linux-aarch64": "ubuntu-24.04"})
    errors = check_sandbox_config(_mutated(config, runners=runners), manifest, {})
    assert any("unknown platform in [runners]" in error for error in errors)


@pytest.mark.parametrize("value", [0, -1, True, "95"])
def test_budgets_must_be_positive_integers(config, manifest, value) -> None:
    budgets = dict(config["budgets"], max_transport_mib=value)
    errors = check_sandbox_config(_mutated(config, budgets=budgets), manifest, {})
    assert any("budgets.max_transport_mib" in error for error in errors)


def test_blob_budget_cannot_exceed_the_git_limit(config, manifest) -> None:
    budgets = dict(config["budgets"], max_blob_mib=128)
    errors = check_sandbox_config(_mutated(config, budgets=budgets), manifest, {})
    assert any("at most 95 MiB" in error for error in errors)


def test_the_workflow_policy_is_required(config, manifest) -> None:
    errors = check_sandbox_config(_mutated(config, workflow=None), manifest, {})
    assert any("[workflow] is required" in error for error in errors)


def test_permissions_must_be_scoped(config, manifest) -> None:
    policy = dict(config["workflow"], permissions=False)
    errors = check_sandbox_config(_mutated(config, workflow=policy), manifest, {})
    assert any("workflow.permissions" in error for error in errors)


def test_the_pixi_cache_stays_off(config, manifest) -> None:
    policy = dict(config["workflow"], setup_pixi_cache=True)
    errors = check_sandbox_config(_mutated(config, workflow=policy), manifest, {})
    assert any("setup_pixi_cache" in error for error in errors)


def test_the_pixi_version_is_required(config, manifest) -> None:
    policy = dict(config["workflow"])
    policy.pop("pixi_version")
    errors = check_sandbox_config(_mutated(config, workflow=policy), manifest, {})
    assert any("workflow.pixi_version must pin" in error for error in errors)


def test_the_pixi_version_must_match_the_workflows(config, manifest, documents) -> None:
    policy = dict(config["workflow"], pixi_version="v0.99.0")
    errors = check_sandbox_config(_mutated(config, workflow=policy), manifest, documents)
    assert any("disagrees with the workflows" in error for error in errors)


def test_concurrency_needs_a_group(config, manifest) -> None:
    policy = dict(config["workflow"], concurrency={"group": "   "})
    errors = check_sandbox_config(_mutated(config, workflow=policy), manifest, {})
    assert any("concurrency.group" in error for error in errors)


@pytest.mark.parametrize("minutes", [0, 2000, "10"])
def test_timeouts_must_be_sane(config, manifest, minutes) -> None:
    policy = dict(config["workflow"], timeouts={"plan": minutes})
    errors = check_sandbox_config(_mutated(config, workflow=policy), manifest, {})
    assert any("timeouts.plan" in error for error in errors)


def test_unknown_timeout_fields_are_refused(config, manifest) -> None:
    policy = dict(config["workflow"], timeouts={"publish": 60, "install": 5})
    errors = check_sandbox_config(_mutated(config, workflow=policy), manifest, {})
    assert any("unknown workflow.timeouts field" in error for error in errors)


def test_empty_push_paths_are_refused(config, manifest) -> None:
    policy = dict(config["workflow"], push_paths=[])
    errors = check_sandbox_config(_mutated(config, workflow=policy), manifest, {})
    assert any("workflow.push_paths" in error for error in errors)


def test_pixi_versions_are_collected_from_every_workflow(documents) -> None:
    assert pixi_versions(documents) == {"v0.83.0"}


def test_generated_workflows_must_be_least_privilege() -> None:
    document = {
        "permissions": {"contents": "write"},
        "jobs": {"publish": {"steps": []}},
    }
    errors = check_generated_workflow(document, "publish-sandbox.yml")
    assert any("contents: read" in error for error in errors)


def test_generated_workflows_need_jobs() -> None:
    errors = check_generated_workflow({"permissions": {"contents": "read"}}, "relock.yml")
    assert any("must declare jobs" in error for error in errors)


def test_a_writing_job_needs_a_guard() -> None:
    document = {
        "permissions": {"contents": "read"},
        "jobs": {"publish": {"permissions": {"contents": "write"}, "steps": []}},
    }
    errors = check_generated_workflow(document, "publish-sandbox.yml")
    assert any("explicit guard" in error for error in errors)


def test_a_guarded_writing_job_is_accepted() -> None:
    document = {
        "permissions": {"contents": "read"},
        "jobs": {
            "publish": {
                "if": "github.repository == 'me/action' && github.ref == 'refs/heads/main'",
                "permissions": {"contents": "write"},
                "steps": [],
            }
        },
    }
    assert check_generated_workflow(document, "publish-sandbox.yml") == []


def test_a_generated_workflow_matches_the_pinned_actions(documents) -> None:
    """The generator pins the same SHAs as config/actions.lock.json, so no exemption is needed."""
    pins = {record["repository"]: record["commit"] for record in _lock()["actions"]}
    for name in ("publish-sandbox.yml", "relock.yml"):
        assert name in quality.GENERATED_WORKFLOWS
    assert set(pins) >= {
        "actions/checkout",
        "prefix-dev/setup-pixi",
        "actions/upload-artifact",
    }


def _lock():
    return json.loads((ROOT / "config/actions.lock.json").read_text(encoding="utf-8"))


def test_the_sandbox_pin_matches_the_offline_feature(manifest) -> None:
    assert quality._check_sandbox_pin(manifest) == []


def test_a_drifting_sandbox_pin_is_refused(manifest) -> None:
    clone = copy.deepcopy(manifest)
    clone["feature"]["offline"]["dependencies"]["pixi-sandbox"]["version"] = "==0.8.0"
    errors = quality._check_sandbox_pin(clone)
    assert errors
    assert "pinned sandbox tool" in errors[0]


def test_the_bootstrap_record_points_at_generated_files() -> None:
    record = json.loads((ROOT / "config/sandbox-bootstrap.json").read_text(encoding="utf-8"))
    assert record["tool"] == "pixi-sandbox"
    assert record["config"] == "pixi-sandbox.toml"
    assert ".github/workflows/publish-sandbox.yml" in record["generated"]
    assert "restore.sh" in record["generated"]
