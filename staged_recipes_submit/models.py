"""Value objects shared by discovery, validation, planning and submission."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .parsing import RecipeMetadata


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Issue:
    """A single finding about a recipe or a submission."""

    code: str
    message: str
    severity: Severity = Severity.ERROR
    path: str | None = None
    hint: str | None = None

    def render(self) -> str:
        location = f" [{self.path}]" if self.path else ""
        text = f"[{self.severity.value}] {self.code}{location}: {self.message}"
        return f"{text}\n      hint: {self.hint}" if self.hint else text


@dataclass(frozen=True, slots=True)
class Recipe:
    """One recipe directory and the files that belong to it."""

    name: str
    version: str | None
    root: Path
    recipe_file: Path
    files: tuple[Path, ...]
    metadata: RecipeMetadata

    def path_to(self, relative: Path) -> Path:
        return self.root / relative

    def relative_files(self) -> tuple[str, ...]:
        return tuple(path.as_posix() for path in self.files)

    @property
    def total_bytes(self) -> int:
        return sum(self.path_to(path).stat().st_size for path in self.files)

    @property
    def label(self) -> str:
        return f"{self.name}-{self.version}" if self.version else self.name


class SubmissionMode(StrEnum):
    SINGLE = "single"
    PER_RECIPE = "per-recipe"


class Outcome(StrEnum):
    PLANNED = "planned"
    CREATED = "created"
    UPDATED = "updated"
    REUSED = "reused"


@dataclass(frozen=True, slots=True)
class SubmissionUnit:
    """One branch, one commit set, one pull request."""

    branch: str
    title: str
    body: str
    recipes: tuple[Recipe, ...]

    @property
    def package_names(self) -> tuple[str, ...]:
        return tuple(recipe.name for recipe in self.recipes)

    @property
    def destination_directories(self) -> dict[str, Path]:
        """``recipes/<name>`` -> source directory inside the fork checkout."""
        return {f"recipes/{recipe.name}": recipe.root for recipe in self.recipes}


@dataclass(frozen=True, slots=True)
class PullRequest:
    number: int
    url: str
    head: str
    state: str = "open"


@dataclass(frozen=True, slots=True)
class UnitResult:
    unit: SubmissionUnit
    outcome: Outcome
    pull_request: PullRequest | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class SubmissionReport:
    results: tuple[UnitResult, ...]
    issues: tuple[Issue, ...] = ()
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return not any(issue.severity is Severity.ERROR for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "ok": self.ok,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity.value,
                    "path": issue.path,
                    "message": issue.message,
                    "hint": issue.hint,
                }
                for issue in self.issues
            ],
            "results": [
                {
                    "branch": result.unit.branch,
                    "packages": list(result.unit.package_names),
                    "outcome": result.outcome.value,
                    "pull_request": result.pull_request.url if result.pull_request else None,
                }
                for result in self.results
            ],
        }

    def render(self) -> str:
        lines = [f"{'DRY RUN ' if self.dry_run else ''}submission report"]
        for issue in self.issues:
            lines.append(f"  {issue.render()}")
        for result in self.results:
            packages = ", ".join(result.unit.package_names)
            target = result.pull_request.url if result.pull_request else result.unit.branch
            lines.append(f"  {result.outcome.value:<8} {packages} -> {target}")
        if not self.results and self.ok:
            lines.append("  nothing to do")
        return "\n".join(lines)
