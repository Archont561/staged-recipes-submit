# Contributing to staged-recipes-submit

This repository follows the same working agreement as Airpack: one locked Pixi environment, one
Python task dispatcher, Git hooks that run in seconds, and CI that runs exactly what you run
locally.

## Prerequisites

- Git
- [Pixi](https://pixi.sh) 0.83 or newer (`curl -fsSL https://pixi.sh/install.sh | bash`)

## First checkout

Prefer a container? Open the folder in VS Code and choose **Reopen in Container**;
[`.devcontainer/`](.devcontainer/devcontainer.json) provides Pixi, git and the extensions, and runs
the same `pixi run setup` and `pixi run ci` you would run on a host.

```bash
git clone https://github.com/Archont561/staged-recipes-submit.git
cd staged-recipes-submit
pixi run setup          # pixi install --locked + tool check + Git hooks
pixi run ci             # everything CI runs
```

`pixi run setup` is idempotent: it installs the locked environment, verifies the tool versions and
installs the lefthook Git hooks.

## Daily loop

```bash
pixi run fmt            # ruff format
pixi run lint           # ruff check
pixi run type-check     # mypy --strict
pixi run test           # pytest, live GitHub tests excluded
pixi run coverage       # branch coverage with the 90 % gate
pixi run validate       # layout, version, workflow and action-pin policy
pixi run ci             # validate + lint + format + types + coverage
```

Pass arguments through the dispatcher, for example `pixi run test -k duplicates` or
`pixi run test tests/bdd -q`.

## Git hooks

`pixi run hooks-install` registers three lefthook hooks. Each one calls a named Pixi task, so the
hook and CI share the same implementation.

| Hook | Task | What it refuses |
| --- | --- | --- |
| `commit-msg` | `hook-commit-msg` | messages that are not Conventional Commits |
| `pre-commit` | `hook-pre-commit` | ruff or formatting problems in staged Python, whitespace errors |
| `pre-push` | `hook-pre-push` | outgoing non-conventional commits and failing tests when source changed |

Bypass only when you must: `git commit --no-verify`.

## Commit messages

```
<type>(optional-scope): <summary>
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`,
`revert`. Merge commits, `fixup!` and `squash!` are exempt.

## Project layout

```
action.yml                     thin composite wrapper: inputs -> scripts/run.py action
staged_recipes_submit/         the package, imported straight from the checkout (no src/, not published)
  discovery.py                 find recipes and their supporting files
  validation.py                static structural checks
  duplicates.py                packages that already exist or appear twice
  plan.py                      group recipes into branches and pull requests
  submit.py                    orchestration against the Git/PR protocols
  gitops.py                    real Git operations
  github.py                    real GitHub pull-request operations
  cli.py                       argument parsing and exit codes
scripts/                       Python automation: the dispatcher the action also calls
tests/                         unit, property (Hypothesis), BDD (pytest-bdd), integration, live
config/                        project identity and the pinned-action lock file
```

## Adding automation

1. Write `scripts/my_task.py` exposing `def my_task(args)`.
2. Register it in `scripts/run.py` (`COMMANDS`).
3. Add a task in `pixi.toml` that calls `python scripts/run.py my-task`.
4. Add tests under `tests/unit/` (or `tests/integration/`).
5. `pixi run ci`.

`pixi run validate` refuses non-Python files under `scripts/`, so keep the dispatcher pure Python.

## Releases

A git tag is the whole release: nothing is built and nothing is published.

```bash
pixi run ci
git tag v0.2.0 && git push origin v0.2.0
```

Consumers pin `@v0.2.0` (or a commit SHA for immutability). If you keep a moving `v1` tag, move it
with `git tag -f v1 v0.2.0 && git push -f origin v1`. `pixi run validate` requires the version to
agree across `pyproject.toml`, `pixi.toml`, `config/project.toml` and `__init__.py`.

## Reports and issues

`pixi run check-tools` writes `reports/tool-versions.json`. Actionable bugs are worth more than
polished ones: include the exact command, the exit code and the rendered report.
