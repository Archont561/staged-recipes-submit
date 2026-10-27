"""Submit conda recipes to ``conda-forge/staged-recipes`` through a pull request.

The package is deliberately split so that everything except the two remote
backends can be tested without a GitHub token:

``discovery``   find recipes and their supporting files
``validation``  static, structural checks
``duplicates``  packages that already exist or appear twice
``plan``        group recipes into branches and pull requests
``submit``      the orchestration flow
``gitops``      real Git operations
``github``      real GitHub pull-request operations
"""

from __future__ import annotations

from ._version import __version__
from .discovery import discover_recipes
from .duplicates import detect_duplicates
from .errors import (
    ConfigurationError,
    DuplicateRecipeError,
    GitError,
    PathSafetyError,
    PullRequestError,
    RecipeDiscoveryError,
    RecipeValidationError,
    Secret,
    SubmissionError,
)
from .models import (
    Issue,
    Outcome,
    Recipe,
    Severity,
    SubmissionMode,
    SubmissionReport,
    SubmissionUnit,
    UnitResult,
)
from .plan import build_plan
from .submit import SubmissionRequest, inspect, run_submission
from .validation import validate_recipe, validate_recipes

__all__ = [
    "ConfigurationError",
    "DuplicateRecipeError",
    "GitError",
    "Issue",
    "Outcome",
    "PathSafetyError",
    "PullRequestError",
    "Recipe",
    "RecipeDiscoveryError",
    "RecipeValidationError",
    "Secret",
    "Severity",
    "SubmissionError",
    "SubmissionMode",
    "SubmissionReport",
    "SubmissionRequest",
    "SubmissionUnit",
    "UnitResult",
    "__version__",
    "build_plan",
    "detect_duplicates",
    "discover_recipes",
    "inspect",
    "run_submission",
    "validate_recipe",
    "validate_recipes",
]
