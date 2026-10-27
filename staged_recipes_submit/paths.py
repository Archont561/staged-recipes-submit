"""Path and name hygiene.

Everything that reaches the filesystem goes through this module first: recipe
inputs from the user, package names that become directories, and names that
become branch names. Nothing may resolve outside the directory it is allowed
to touch.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from .errors import PathSafetyError

MAX_PACKAGE_NAME_LENGTH = 64
_PACKAGE_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")
_UNSAFE_BRANCH = re.compile(r"[^a-z0-9._-]+")
JUNK_DIRECTORIES = frozenset(
    {".git", ".pytest_cache", ".hypothesis", ".ruff_cache", "__pycache__", ".ipynb_checkpoints"}
)
JUNK_FILES = frozenset({".DS_Store", "Thumbs.db"})


def validate_package_name(name: str) -> str:
    """Return ``name`` when it is a safe conda package name, else raise."""
    if not name:
        raise PathSafetyError(
            "A recipe declares no package name.", hint="add 'package: {name: ...}'"
        )
    if len(name) > MAX_PACKAGE_NAME_LENGTH:
        raise PathSafetyError(
            f"Package name is longer than {MAX_PACKAGE_NAME_LENGTH} characters: {name!r}"
        )
    if not _PACKAGE_NAME.fullmatch(name):
        raise PathSafetyError(
            f"{name!r} is not a safe conda package name.",
            hint="use lowercase letters, digits, '.', '_' and '-', starting and ending with a "
            "letter or digit",
        )
    return name


def guard_user_path(candidate: str | Path, *, base: Path | None = None) -> Path:
    """Resolve a user-supplied recipe path, rejecting escapes and symlink tricks."""
    raw = Path(candidate).expanduser()
    if "\x00" in str(raw):
        raise PathSafetyError("Recipe paths must not contain NUL bytes.")
    resolved = raw.resolve()
    if base is not None:
        anchor = base.resolve()
        if not resolved.is_relative_to(anchor):
            raise PathSafetyError(
                f"{raw} resolves outside the allowed directory {anchor}.",
                hint="pass recipes inside the checked-out workspace",
            )
    return resolved


def safe_relative(root: Path, candidate: Path) -> PurePosixPath:
    """Express ``candidate`` relative to ``root``; refuse anything that escapes it."""
    anchor = root.resolve()
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if not resolved.is_relative_to(anchor):
        raise PathSafetyError(
            f"{candidate} would land outside {anchor}.",
            hint="recipes may only write into their own 'recipes/<package-name>' directory",
        )
    return PurePosixPath(resolved.relative_to(anchor).as_posix())


def is_junk(path: Path) -> bool:
    return path.name in JUNK_DIRECTORIES or path.name in JUNK_FILES


def relative_files(root: Path) -> Iterator[Path]:
    """Yield every file that belongs to a recipe, relative to its directory."""
    anchor = root.resolve()
    for path in sorted(root.rglob("*")):
        if any(part in JUNK_DIRECTORIES for part in path.relative_to(root).parts):
            continue
        if not path.is_file() or path.name in JUNK_FILES:
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(anchor):
            raise PathSafetyError(
                f"{path} links outside the recipe directory.",
                hint="remove the symlink or move the target into the recipe directory",
            )
        yield path.relative_to(root)


def branch_component(text: str, *, limit: int = 48) -> str:
    """Turn arbitrary text into a branch-safe slug."""
    normalised = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = _UNSAFE_BRANCH.sub("-", normalised.lower()).strip("-._")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:limit].strip("-._") or "recipes"


def destination(root: Path, package_name: str) -> Path:
    """Return ``root/recipes/<package_name>`` after checking both components."""
    validate_package_name(package_name)
    candidate = root / "recipes" / package_name
    safe_relative(root, Path("recipes") / package_name)
    return candidate
