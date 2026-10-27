"""Workspace setup, tool checks and Git hook installation."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime

from common import ROOT, AutomationError, git, run, tool_version, write_json

TOOLS = {
    "python": ("python", ("--version",)),
    "pixi": ("pixi", ("--version",)),
    "git": ("git", ("--version",)),
    "ruff": ("ruff", ("--version",)),
    "mypy": ("mypy", ("--version",)),
    "pytest": ("pytest", ("--version",)),
    "lefthook": ("lefthook", ("version",)),
    "actionlint": ("actionlint", ("-version",)),
    "gh": ("gh", ("--version",)),
}


def setup(_args):
    """Install the locked environment, build tools and Git hooks."""
    _require("pixi", "install Pixi first: https://pixi.sh/latest/")
    run(["pixi", "install", "--locked", "--all"])
    run(["pixi", "run", "--locked", "check-tools"])
    if (ROOT / ".git").exists():
        run(["pixi", "run", "--locked", "hooks-install"])
    print("Workspace ready. Run: pixi run ci")


def hooks_install(_args):
    git(["rev-parse", "--git-dir"])
    _require("lefthook", "run this through 'pixi run hooks-install' so lefthook is on PATH")
    run(["lefthook", "install"])
    print("Git hooks installed: commit-msg, pre-commit, pre-push.")


def check_tools(_args):
    """Record the version of every tool the hooks and CI rely on."""
    results = []
    for name, (command, arguments) in TOOLS.items():
        version = tool_version(command, *arguments)
        results.append({"tool": name, "found": version is not None, "version": version})
        print(f"{'PASS' if version else 'MISS'} {name}: {version or 'not installed'}")
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "found": sum(item["found"] for item in results),
        "total": len(results),
        "results": results,
    }
    write_json(ROOT / "reports/tool-versions.json", report)
    required = {"python", "pixi", "git", "ruff", "pytest", "lefthook"}
    missing = sorted(
        item["tool"] for item in results if not item["found"] and item["tool"] in required
    )
    if missing:
        raise AutomationError(
            f"Missing required tools: {', '.join(missing)}",
            hint="run 'pixi install --locked --all' inside the repository",
        )
    print(json.dumps({"found": report["found"], "total": report["total"]}))


def _require(tool: str, hint: str) -> None:
    if shutil.which(tool) is None:
        raise AutomationError(f"{tool} is required. {hint}")
