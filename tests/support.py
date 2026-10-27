"""Test doubles and small builders shared by the whole suite."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from staged_recipes_submit.models import PullRequest, SubmissionUnit

V1_TEMPLATE = """\
context:
  version: "{version}"

package:
  name: "{name}"
  version: ${{{{ version }}}}

source:
  url: https://example.invalid/{name}-${{{{ version }}}}.tar.gz
  sha256: 0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0

build:
  number: 0
  script: python -m pip install . -vv --no-deps

requirements:
  host:
    - python
  run:
    - python

tests:
  - python:
      imports:
        - {module}

about:
  summary: A test package
  license: MIT
  home: https://example.invalid/{name}

extra:
  recipe-maintainers:
    - archont561
"""

V0_TEMPLATE = """\
package:
  name: "{name}"
  version: "{version}"

source:
  path: ..

build:
  number: 0

requirements:
  host:
    - python

about:
  summary: A test package
  license: MIT
"""


def fresh_dir(tmp_path: Path) -> Path:
    """A unique directory, so Hypothesis examples never share state."""
    directory = tmp_path / f"case-{uuid.uuid4().hex[:12]}"
    directory.mkdir()
    return directory


def write_recipe(
    root: Path,
    name: str,
    *,
    version: str = "1.0.0",
    filename: str = "recipe.yaml",
    document: str | None = None,
) -> Path:
    """Create a recipe directory and return it."""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    template = V1_TEMPLATE if filename == "recipe.yaml" else V0_TEMPLATE
    body = (
        document
        if document is not None
        else template.format(name=name, version=version, module=name.replace("-", "_"))
    )
    (directory / filename).write_text(body, encoding="utf-8")
    return directory


def _digest(directory: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            hasher.update(path.relative_to(directory).as_posix().encode())
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


@dataclass
class FakeGit:
    """An in-memory fork checkout that records every call."""

    workdir: Path
    calls: list[str] = field(default_factory=list)
    pushed: list[str] = field(default_factory=list)
    branch: str | None = None
    prepared: tuple[str, str, str] | None = None
    committed: list[str] = field(default_factory=list)
    _digests: dict[str, str] = field(default_factory=dict)
    _dirty: bool = False

    def prepare(self, *, upstream: str, fork: str, base_branch: str) -> Path:
        self.calls.append("prepare")
        self.prepared = (upstream, fork, base_branch)
        return self.workdir

    def checkout_or_create(self, branch: str) -> None:
        self.calls.append(f"checkout:{branch}")
        self.branch = branch

    def materialize(self, unit: SubmissionUnit) -> bool:
        self.calls.append(f"materialize:{unit.branch}")
        changed = False
        for recipe in unit.recipes:
            target = self.workdir / "recipes" / recipe.name
            shutil.copytree(recipe.root, target, dirs_exist_ok=True)
            digest = _digest(target)
            if self._digests.get(recipe.name) != digest:
                self._digests[recipe.name] = digest
                changed = True
        self._dirty = changed
        return changed

    def commit(self, message: str) -> bool:
        self.calls.append(f"commit:{message.splitlines()[0]}")
        if not self._dirty:
            return False
        self.committed.append(message)
        self._dirty = False
        return True

    def push(self, branch: str) -> None:
        self.calls.append(f"push:{branch}")
        self.pushed.append(branch)

    @property
    def writes(self) -> list[str]:
        return [call for call in self.calls if call.startswith(("push", "commit", "materialize"))]


@dataclass
class FakePullRequests:
    """An in-memory GitHub that hands out deterministic pull requests."""

    created: list[PullRequest] = field(default_factory=list)
    open_by_head: dict[str, PullRequest] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def find_open(self, *, head: str, base: str) -> PullRequest | None:
        self.calls.append(f"find:{head}")
        return self.open_by_head.get(head)

    def create(self, *, unit: SubmissionUnit, head: str, base: str) -> PullRequest:
        self.calls.append(f"create:{head}")
        number = len(self.created) + 1
        pull_request = PullRequest(
            number=number,
            url=f"https://github.com/conda-forge/staged-recipes/pull/{number}",
            head=unit.branch,
        )
        self.created.append(pull_request)
        self.open_by_head[head] = pull_request
        return pull_request
