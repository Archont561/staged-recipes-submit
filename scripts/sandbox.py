"""Thin wrapper around the optional pixi-sandbox offline transport."""

from __future__ import annotations

import shutil

from common import AutomationError, run


def sandbox(args):
    if not args:
        raise AutomationError(
            "sandbox expects a pixi-sandbox subcommand.",
            hint="try: pixi run --locked -e offline sandbox plan",
        )
    executable = shutil.which("pixi-sandbox")
    if executable is None:
        raise AutomationError(
            "pixi-sandbox is not installed.",
            hint="run 'pixi run --locked -e offline ...', or install it from the prefix.dev channel",
        )
    run([executable, *args])
