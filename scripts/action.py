"""The three commands the composite action and contributors share.

`action.yml` runs `python "$ACTION_PATH/scripts/run.py" action` — the same dispatcher a developer
uses locally, so there is no second entry point to keep in sync. Each wrapper returns an integer
exit code, which :mod:`scripts.run` passes through to the shell.
"""

from __future__ import annotations

from common import AutomationError


def submit(args):
    """Run a submission from explicit CLI arguments: `pixi run submit --recipe … --fork …`."""
    from staged_recipes_submit.cli import main

    code = main([str(argument) for argument in args])
    if code:
        raise AutomationError(f"the submission exited with code {code}")
    return 0


def action(_args):
    """Translate `INPUT_*` environment variables into a submission (the composite path)."""
    from staged_recipes_submit.action_entry import main

    return main()


def summary(_args):
    """Render the step summary from `REPORT_JSON`."""
    from staged_recipes_submit.action_summary import main

    return main()
