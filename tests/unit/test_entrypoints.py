"""`scripts/action.py`: the wrappers the composite action and the dispatcher share."""

from __future__ import annotations

import action
import pytest
from common import AutomationError


def test_submit_forwards_arguments_and_returns_zero(monkeypatch) -> None:
    seen = {}

    def fake_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr("staged_recipes_submit.cli.main", fake_main)
    assert action.submit(["--recipe", "r/recipe.yaml", "--fork", "me/fork", "--dry-run"]) == 0
    assert seen["argv"] == ["--recipe", "r/recipe.yaml", "--fork", "me/fork", "--dry-run"]


def test_submit_turns_a_failure_into_an_actionable_error(monkeypatch) -> None:
    monkeypatch.setattr("staged_recipes_submit.cli.main", lambda argv: 2)
    with pytest.raises(AutomationError, match="exited with code 2"):
        action.submit([])


def test_action_reads_the_environment(monkeypatch, tmp_path) -> None:
    from staged_recipes_submit import action_entry

    recipe = tmp_path / "pkg"
    recipe.mkdir()
    (recipe / "recipe.yaml").write_text(
        "package:\n  name: pkg\n  version: '1'\nabout:\n  summary: x\n"
    )
    monkeypatch.setenv("INPUT_RECIPES", str(recipe))
    monkeypatch.setenv("INPUT_FORK", "me/fork")
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    assert action.action([]) == 0
    assert action_entry.split_paths(str(recipe)) == [str(recipe)]


def test_action_returns_the_submission_exit_code(monkeypatch) -> None:
    monkeypatch.setenv("INPUT_RECIPES", "/nonexistent/recipe.yaml")
    monkeypatch.setenv("INPUT_FORK", "me/fork")
    monkeypatch.setenv("INPUT_DRY_RUN", "true")
    assert action.action([]) != 0


def test_summary_is_a_no_op_without_a_report(monkeypatch) -> None:
    monkeypatch.delenv("REPORT_JSON", raising=False)
    assert action.summary([]) == 0


def test_summary_renders_a_report(monkeypatch, tmp_path) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("REPORT_JSON", '{"dry_run": true, "results": [], "issues": []}')
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert action.summary([]) == 0
    assert "Dry run" in summary.read_text(encoding="utf-8")


def test_the_dispatcher_passes_integer_results_through(capsys) -> None:
    import run

    assert run.main(["help"]) == 0
    assert "Scripts:" in capsys.readouterr().out
    assert run.main(["nope"]) == 2


def test_the_dispatcher_exposes_the_action_commands() -> None:
    import run

    assert {"action", "submit", "summary"} <= set(run.COMMANDS)


def test_every_dispatched_module_imports() -> None:
    import importlib

    import run

    for module, function in run.COMMANDS.values():
        target = getattr(importlib.import_module(module), function)
        assert callable(target)
