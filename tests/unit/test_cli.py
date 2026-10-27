"""The command-line surface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from staged_recipes_submit.cli import EXIT_INPUT, EXIT_OK, build_parser, build_request, main
from staged_recipes_submit.models import SubmissionMode


def _argv(recipe: Path, *extra: str) -> list[str]:
    return ["--recipe", str(recipe), "--fork", "tester/staged-recipes", *extra]


def test_dry_run_reports_the_plan(recipe_factory, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(_argv(recipe_factory("alpha"), "--dry-run"))
    output = capsys.readouterr().out
    assert code == EXIT_OK
    assert "DRY RUN submission report" in output
    assert "planned  alpha -> submit/alpha" in output


def test_dry_run_json_output(recipe_factory, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(_argv(recipe_factory("alpha"), "--dry-run", "--json"))
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK
    assert payload["dry_run"] is True
    assert payload["results"][0]["branch"] == "submit/alpha"


def test_invalid_recipe_exits_with_input_error(
    recipe_factory, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(_argv(recipe_factory("alpha", document="package: [unclosed\n"), "--dry-run"))
    report = capsys.readouterr().out
    assert code == EXIT_INPUT
    assert "VAL002" in report


def test_discovery_failure_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["--recipe", str(tmp_path / "absent"), "--fork", "tester/staged-recipes", "--dry-run"]
    )
    assert code == EXIT_INPUT
    assert "does not exist" in capsys.readouterr().err


def test_missing_token_is_a_configuration_error(recipe_factory, monkeypatch, capsys) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    code = main(_argv(recipe_factory("alpha")))
    assert code == EXIT_INPUT
    assert "No GitHub token" in capsys.readouterr().err


def test_bad_fork_is_a_configuration_error(recipe_factory, capsys) -> None:
    code = main(["--recipe", str(recipe_factory("alpha")), "--fork", "nonsense", "--dry-run"])
    assert code == EXIT_INPUT
    assert "is not a 'owner/name' fork" in capsys.readouterr().err


def test_mode_and_prefix_reach_the_request(recipe_factory) -> None:
    args = build_parser().parse_args(
        _argv(recipe_factory("alpha"), "--dry-run", "--mode", "per-recipe", "--branch-prefix", "ci")
    )
    request = build_request(args)
    assert request.mode is SubmissionMode.PER_RECIPE
    assert request.branch_prefix == "ci"
    assert request.dry_run is True


def test_description_alias_sets_the_body(recipe_factory) -> None:
    args = build_parser().parse_args(_argv(recipe_factory("alpha"), "--description", "why"))
    assert build_request(args).body == "why"


def test_workdir_default_fixture_is_not_created_by_dry_run(
    recipe_factory, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    main(_argv(recipe_factory("alpha"), "--dry-run"))
    assert not (tmp_path / ".staged-recipes").exists()


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["--version"])
    assert exit_info.value.code == 0
    assert "0.1.0" in capsys.readouterr().out
