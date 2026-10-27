#!/usr/bin/env python3
"""Usage: pixi run scripts <script name> [arguments ...]."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

# Importable from any working directory: `python scripts/run.py …` works from the repository root
# and `python "$ACTION_PATH/scripts/run.py …"` works from a workflow workspace.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common import AutomationError  # noqa: E402  (the path above must be set first)

COMMANDS = {
    "action": ("action", "action"),
    "setup": ("workspace", "setup"),
    "check-tools": ("workspace", "check_tools"),
    "hooks-install": ("workspace", "hooks_install"),
    "hook-commit-msg": ("hooks", "hook_commit_msg"),
    "hook-pre-commit": ("hooks", "hook_pre_commit"),
    "hook-pre-push": ("hooks", "hook_pre_push"),
    "commit-check": ("hooks", "commit_check"),
    "submit": ("action", "submit"),
    "summary": ("action", "summary"),
    "fmt": ("quality", "python_format"),
    "fmt-check": ("quality", "python_format_check"),
    "lint": ("quality", "python_lint"),
    "type-check": ("quality", "python_type_check"),
    "test": ("quality", "python_test"),
    "coverage": ("quality", "coverage"),
    "validate": ("quality", "validate"),
    "ci": ("quality", "ci"),
    "sandbox": ("sandbox", "sandbox"),
    "release-plan": ("release", "release_plan"),
    "release-publish": ("release", "release_publish"),
}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in {"--help", "-h", "help"}:
        print(__doc__)
        print("\nScripts:\n  " + "\n  ".join(sorted(COMMANDS)))
        return 0
    command = argv[0]
    if command not in COMMANDS:
        print(f"Unknown script: {command}. Use pixi run scripts --help.", file=sys.stderr)
        return 2
    module_name, function_name = COMMANDS[command]
    try:
        function = getattr(importlib.import_module(module_name), function_name)
        result = function(argv[1:])
    except subprocess.CalledProcessError as error:
        if error.stdout:
            print(error.stdout, file=sys.stderr)
        if error.stderr:
            print(error.stderr, file=sys.stderr)
        print(f"Command failed (exit {error.returncode}).", file=sys.stderr)
        return error.returncode if 0 < error.returncode < 126 else 1
    except (AutomationError, RuntimeError, OSError, ValueError, KeyError) as error:
        print(f"staged-recipes-submit automation: {error}", file=sys.stderr)
        return 1
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
