"""Shared fixtures and the opt-in switch for live GitHub tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

from support import FakeGit, FakePullRequests, write_recipe

settings.register_profile(
    "default",
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
settings.load_profile("default")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests that talk to the real GitHub API (read-only)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="live GitHub tests require --run-live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture
def recipes_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "sources"
    directory.mkdir()
    return directory


@pytest.fixture
def recipe_factory(recipes_dir: Path):
    def factory(name: str, *, version: str = "1.0.0", filename: str = "recipe.yaml", document=None):
        return write_recipe(
            recipes_dir, name, version=version, filename=filename, document=document
        )

    return factory


@pytest.fixture
def staged_recipes_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "staged-recipes"
    (checkout / "recipes").mkdir(parents=True)
    return checkout


@pytest.fixture
def fake_git(tmp_path: Path) -> FakeGit:
    workdir = tmp_path / "fork"
    workdir.mkdir()
    (workdir / "recipes").mkdir()
    return FakeGit(workdir=workdir)


@pytest.fixture
def fake_pull_requests() -> FakePullRequests:
    return FakePullRequests()
