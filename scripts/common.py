"""Shared standard-library automation primitives; no shell command assembly."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class AutomationError(RuntimeError):
    """An actionable automation failure."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message}\n  hint: {self.hint}" if self.hint else self.message


def run(args, *, cwd=ROOT, capture=False, input_text=None, check=True, env=None):
    """Execute an argument vector, never ``sh -c``; never log credentials."""
    command = [str(arg) for arg in args]
    executable = shutil.which(command[0])
    if executable:
        command[0] = executable
    settings = os.environ.copy()
    settings.update(PIXI_NO_TELEMETRY="1", DO_NOT_TRACK="1", PYTHONUTF8="1")
    if env:
        settings.update(env)
    print("+ " + shlex.join(command), file=sys.stderr, flush=True)
    return subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        text=True,
        encoding="utf-8",
        capture_output=capture,
        check=check,
        env=settings,
    )


def read_toml(path):
    with Path(path).open("rb") as file:
        return tomllib.load(file)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha256_file(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def load_yaml(path):
    """Load YAML without letting its scalar typing rewrite our strings."""
    import yaml

    return yaml.load(Path(path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def git(args, *, root=ROOT, capture=True, check=True):
    return run(["git", *args], cwd=root, capture=capture, check=check)


def require_tool(name, hint):
    if shutil.which(name) is None:
        raise AutomationError(f"{name} is missing. {hint}")


def tool_version(name, *args):
    if shutil.which(name) is None:
        return None
    result = run([name, *(args or ("--version",))], capture=True, check=False)
    return (
        (result.stdout or result.stderr).strip().splitlines()[0]
        if (result.stdout or result.stderr)
        else ""
    )
