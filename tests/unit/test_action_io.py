"""The composite-action glue: inputs in, outputs and summaries out."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from staged_recipes_submit.action_entry import build_argv, split_paths, write_outputs
from staged_recipes_submit.action_summary import render_summary
from staged_recipes_submit.discovery import discover_recipes
from staged_recipes_submit.models import Outcome, PullRequest, SubmissionReport, UnitResult
from staged_recipes_submit.plan import build_plan


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a/recipe.yaml\nb/recipe.yaml", ["a/recipe.yaml", "b/recipe.yaml"]),
        ("a,b , c", ["a", "b", "c"]),
        ("\n\n", []),
        (" a/recipe.yaml \n, b ", ["a/recipe.yaml", "b"]),
    ],
)
def test_split_paths(raw: str, expected: list[str]) -> None:
    assert split_paths(raw) == expected


def test_build_argv_maps_every_input() -> None:
    argv = build_argv(
        {
            "INPUT_RECIPES": "recipes/a/recipe.yaml\nrecipes/b/meta.yaml",
            "INPUT_FORK": "me/staged-recipes",
            "INPUT_DRY_RUN": "true",
            "INPUT_TITLE": "Add a",
            "INPUT_DESCRIPTION": "why",
            "INPUT_MODE": "per-recipe",
            "INPUT_BRANCH_PREFIX": "ci",
            "INPUT_UPSTREAM": "conda-forge/staged-recipes",
            "INPUT_BASE_BRANCH": "main",
        }
    )
    assert argv[:4] == ["--fork", "me/staged-recipes", "--recipe", "recipes/a/recipe.yaml"]
    assert "--dry-run" in argv
    assert argv[argv.index("--mode") + 1] == "per-recipe"
    assert argv[argv.index("--branch-prefix") + 1] == "ci"
    assert "--title" in argv
    assert "--description" in argv


def test_build_argv_omits_empty_optionals() -> None:
    argv = build_argv(
        {"INPUT_RECIPES": "r/recipe.yaml", "INPUT_FORK": "me/fork", "INPUT_TITLE": "  "}
    )
    assert argv == ["--fork", "me/fork", "--recipe", "r/recipe.yaml"]


@pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE"])
def test_truthy_dry_run_values(value: str) -> None:
    argv = build_argv({"INPUT_DRY_RUN": value, "INPUT_RECIPES": "r", "INPUT_FORK": "me/f"})
    assert "--dry-run" in argv


def test_write_outputs_uses_heredocs(recipe_factory, tmp_path: Path) -> None:
    (unit,) = build_plan(discover_recipes([recipe_factory("alpha")]))
    report = SubmissionReport(
        results=(
            UnitResult(
                unit=unit, outcome=Outcome.CREATED, pull_request=PullRequest(1, "u", "submit/alpha")
            ),
        ),
        dry_run=False,
    )
    output_file = tmp_path / "github_output"
    write_outputs(report, output_file)
    text = output_file.read_text(encoding="utf-8")
    assert "pull-request-urls<<" in text
    assert "branches<<" in text
    assert "report<<" in text
    assert "submit/alpha" in text
    assert any(json.loads(line) for line in text.splitlines() if line.startswith("{"))


def test_summary_mentions_results_issues_and_the_handover() -> None:
    summary = render_summary(
        {
            "dry_run": True,
            "results": [
                {"outcome": "planned", "packages": ["alpha", "beta"], "branch": "submit/a-b"}
            ],
            "issues": [{"code": "VAL006", "message": "no version", "hint": "add one"}],
        }
    )
    assert "Dry run" in summary
    assert "| planned | alpha, beta |" in summary
    assert "`VAL006`" in summary
    assert "conda-forge" in summary


def test_summary_without_results_or_issues() -> None:
    summary = render_summary({"dry_run": False, "results": [], "issues": []})
    assert summary.startswith("## staged-recipes submission")


def test_action_entry_runs_a_dry_run_and_writes_outputs(
    recipe_factory, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from staged_recipes_submit.action_entry import main as action_main

    output = tmp_path / "github_output"
    output.touch()
    code = action_main(
        {
            "INPUT_RECIPES": f"{recipe_factory('alpha')}\n{recipe_factory('beta')}",
            "INPUT_FORK": "tester/staged-recipes",
            "INPUT_DRY_RUN": "true",
            "GITHUB_OUTPUT": str(output),
        }
    )
    assert code == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert "branches<<" in output.read_text(encoding="utf-8")


def test_action_entry_reports_invalid_input(recipe_factory, capsys) -> None:
    from staged_recipes_submit.action_entry import main as action_main

    code = action_main(
        {
            "INPUT_RECIPES": str(recipe_factory("alpha", document="package: [unclosed\n")),
            "INPUT_FORK": "tester/staged-recipes",
            "INPUT_DRY_RUN": "true",
        }
    )
    assert code == 2
    assert "VAL002" in capsys.readouterr().out


def test_action_summary_writes_the_step_summary(tmp_path: Path) -> None:
    from staged_recipes_submit.action_summary import main as summary_main

    summary = tmp_path / "summary.md"
    report = {"dry_run": False, "results": [], "issues": [{"code": "X", "message": "m"}]}
    code = summary_main({"REPORT_JSON": json.dumps(report), "GITHUB_STEP_SUMMARY": str(summary)})
    assert code == 0
    assert "`X` m" in summary.read_text(encoding="utf-8")


def test_action_summary_prints_without_a_summary_file(capsys) -> None:
    from staged_recipes_submit.action_summary import main as summary_main

    code = summary_main({"REPORT_JSON": json.dumps({"dry_run": True, "results": [], "issues": []})})
    assert code == 0
    assert "Dry run" in capsys.readouterr().out


@pytest.mark.parametrize("environment", [{}, {"REPORT_JSON": "not json"}, {"REPORT_JSON": "[]"}])
def test_action_summary_ignores_missing_or_broken_input(environment: dict[str, str]) -> None:
    from staged_recipes_submit.action_summary import main as summary_main

    assert summary_main(environment) == 0


def test_dry_run_guard_refuses_every_call() -> None:
    from staged_recipes_submit.backends import DryRunGuard

    guard = DryRunGuard()
    with pytest.raises(AssertionError, match="must not touch remote state"):
        guard.push("branch")  # type: ignore[attr-defined]
    with pytest.raises(AssertionError, match="must not touch remote state"):
        guard.prepare(upstream="a/b", fork="c/d", base_branch="main")  # type: ignore[attr-defined]


def test_token_falls_back_to_the_environment(monkeypatch, recipe_factory) -> None:
    from staged_recipes_submit import cli

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "ghp_from_environment")
    secret = cli._token_from_environment()
    assert secret.reveal() == "ghp_from_environment"
    monkeypatch.delenv("GH_TOKEN")
    with pytest.raises(Exception, match="No GitHub token"):
        cli._token_from_environment()


def test_a_missing_secret_fails_loudly_and_names_the_input(recipe_factory, capsys) -> None:
    from staged_recipes_submit import action_entry

    code = action_entry.main(
        {
            "INPUT_RECIPES": str(recipe_factory("alpha")),
            "INPUT_FORK": "octocat/staged-recipes",
            "INPUT_TOKEN": "",
            "INPUT_DRY_RUN": "false",
        }
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "No GitHub token" in captured.err
    assert "`github-token`" in captured.err
    assert "empty string" in captured.err
    assert "octocat/staged-recipes" in captured.err
    # The failure is surfaced as an annotation, so it survives a failing step.
    assert "::error::" in captured.err


def test_a_dry_run_needs_no_secret_at_all(recipe_factory, capsys) -> None:
    from staged_recipes_submit import action_entry

    code = action_entry.main(
        {
            "INPUT_RECIPES": str(recipe_factory("beta")),
            "INPUT_FORK": "octocat/staged-recipes",
            "INPUT_TOKEN": "",
            "INPUT_DRY_RUN": "true",
        }
    )
    assert code == 0
    assert "DRY RUN" in capsys.readouterr().out


def test_a_workflow_token_is_warned_about_before_the_push(recipe_factory, capsys) -> None:
    from staged_recipes_submit import action_entry

    code = action_entry.main(
        {
            "INPUT_RECIPES": str(recipe_factory("gamma")),
            "INPUT_FORK": "octocat/staged-recipes",
            "INPUT_TOKEN": "ghs_installationtoken",
            "INPUT_DRY_RUN": "true",
        }
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "::warning::" in captured.err
    assert "octocat/staged-recipes" in captured.err
    assert "secrets.GITHUB_TOKEN cannot" in captured.err
    assert "ghs_installationtoken" not in captured.err


def test_annotations_escape_newlines_and_percent_signs() -> None:
    from staged_recipes_submit import action_entry

    assert action_entry._escape("100%\ntwo") == "100%25%0Atwo"
