# API reference

Everything this repository exposes to the outside world: the composite action's inputs and outputs,
the CLI that mirrors it, the dispatcher commands, and the importable Python surface.

- Task-oriented walkthrough: [`docs/GUIDE.md`](docs/GUIDE.md)
- Internal design and invariants: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Contributor workflow: [`CONTRIBUTING.md`](CONTRIBUTING.md)

## Contents

- [Contract at a glance](#contract-at-a-glance)
- [Calling the action](#calling-the-action)
- [Inputs](#inputs)
- [Outputs](#outputs)
- [Exit codes and failure semantics](#exit-codes-and-failure-semantics)
- [Behaviour contract](#behaviour-contract)
- [Environment variables](#environment-variables)
- [CLI reference](#cli-reference)
- [Dispatcher commands](#dispatcher-commands)
- [Python API](#python-api)
- [Compatibility and versioning](#compatibility-and-versioning)

## Contract at a glance

| Surface | Reference | Stability |
| --- | --- | --- |
| Composite action (`action.yml`) | this document, [Inputs](#inputs) / [Outputs](#outputs) | inputs and outputs are stable; new optional inputs may be added in a minor release |
| CLI (`staged-recipes-submit`) | [CLI reference](#cli-reference) | flags are additive-only |
| Dispatcher (`scripts/run.py`) | [Dispatcher commands](#dispatcher-commands) | internal; used by this repository and by `action.yml` |
| Python package (`staged_recipes_submit`) | [Python API](#python-api) | `run_submission`, `inspect`, `SubmissionRequest`, `SubmissionReport`, the `*Error` classes |
| Process exit code | [Exit codes](#exit-codes-and-failure-semantics) | `0` success, `1` runtime failure, `2` input or validation failure |

The action never publishes, never merges and never builds a package. It validates recipes, pushes a
branch to **your** fork, and opens a pull request against `conda-forge/staged-recipes`.

## Calling the action

### Minimal

```yaml
- uses: Archont561/staged-recipes-submit@v1
  with:
    recipes: recipes/cool-lib/recipe.yaml
    fork: octocat/staged-recipes
    github-token: ${{ secrets.CONDA_FORGE_TOKEN }}
```

Three inputs are required (`recipes`, `fork`, `github-token`); the other seven have defaults. In a
`workflow_dispatch` job the action also needs a checkout if your recipes live in the repository:

```yaml
name: submit recipes
on: workflow_dispatch
permissions:
  contents: read

jobs:
  submit:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: { persist-credentials: false }
      - uses: Archont561/staged-recipes-submit@v1
        with:
          recipes: recipes/cool-lib/recipe.yaml
          fork: octocat/staged-recipes
          github-token: ${{ secrets.CONDA_FORGE_TOKEN }}
```

### Every option at once

```yaml
- name: Submit recipes
  id: submit
  uses: Archont561/staged-recipes-submit@v1
  with:
    # required
    recipes: |
      recipes/cool-lib
      recipes/cool-cli/recipe.yaml
    fork: octocat/staged-recipes
    github-token: ${{ secrets.CONDA_FORGE_TOKEN }}
    # optional — the values below are the defaults
    dry-run: false
    title: ""
    description: ""
    mode: single
    branch-prefix: submit
    upstream: conda-forge/staged-recipes
    base-branch: main
    python-version: "3.13"

- run: echo '${{ steps.submit.outputs.pull-request-urls }}'
```

### Rehearse, then submit

```yaml
- id: plan
  uses: Archont561/staged-recipes-submit@v1
  with:
    recipes: recipes/cool-lib
    fork: octocat/staged-recipes
    dry-run: true              # no token needed, nothing is written
- id: submit
  uses: Archont561/staged-recipes-submit@v1
  with:
    recipes: recipes/cool-lib
    fork: octocat/staged-recipes
    github-token: ${{ secrets.CONDA_FORGE_TOKEN }}
```

### One pull request per recipe

```yaml
- uses: Archont561/staged-recipes-submit@v1
  with:
    recipes: recipes/*/recipe.yaml
    fork: octocat/staged-recipes
    github-token: ${{ secrets.CONDA_FORGE_TOKEN }}
    mode: per-recipe          # submit/cool-lib and submit/cool-cli, two PRs
    branch-prefix: ci         # ci/cool-lib, ci/cool-cli
```

### From a GitHub App instead of a PAT

```yaml
- id: app
  uses: actions/create-github-app-token@<40-hex-sha> # v2
  with:
    app-id: ${{ vars.APP_ID }}
    private-key: ${{ secrets.APP_PRIVATE_KEY }}
    owner: octocat
- uses: Archont561/staged-recipes-submit@v1
  with:
    recipes: recipes/cool-lib
    fork: octocat/staged-recipes
    github-token: ${{ steps.app.outputs.token }}
```

## Inputs

| Name | Required | Default | Type | Purpose |
| --- | --- | --- | --- | --- |
| `recipes` | **yes** | — | newline/comma list | Recipes to submit: directories or `recipe.yaml`/`meta.yaml` files |
| `fork` | **yes** | — | `owner/repo` | Your `staged-recipes` fork; receives the branch |
| `github-token` | **yes** | — | secret | Token with write access to the fork and pull-request access to the upstream |
| `dry-run` | no | `false` | boolean | Validate and print the plan; no clone, branch, push or API call |
| `title` | no | derived | string | Pull-request title |
| `description` | no | derived | string | Pull-request body |
| `mode` | no | `single` | `single` \| `per-recipe` | One pull request for everything, or one per recipe |
| `branch-prefix` | no | `submit` | slug | Prefix of the submission branch names |
| `upstream` | no | `conda-forge/staged-recipes` | `owner/repo` | Repository that receives the pull request |
| `base-branch` | no | `main` | branch name | Base branch of the pull request |
| `python-version` | no | `3.13` | `3.11`–`3.13` | Interpreter used to run the action itself |

### `recipes`

Each entry is resolved as: an absolute path, a path relative to the working directory (the checked
out workspace on a runner), a directory containing `recipe.yaml` or `meta.yaml`, or the recipe file
itself. Directories are searched up to
**4 levels** deep; `.git`, `__pycache__`, `.pixi` and similar junk directories are skipped. The same
directory may be named twice — results are de-duplicated by resolved path, so reruns stay idempotent.

| Accepted | Rejected |
| --- | --- |
| `recipes/cool-lib` | `../outside-the-workspace` (path escapes) |
| `recipes/cool-lib/recipe.yaml` | a directory holding both `recipe.yaml` and `meta.yaml` |
| `recipes/` (searched 4 deep) | a file not named `recipe.yaml` or `meta.yaml` (`VAL001`) |
| `a/recipe.yaml,b/meta.yaml` (comma) | a missing path |

### `fork`

`owner/repo` matching `[A-Za-z0-9._-]+/[A-Za-z0-9._-]+`; anything else fails with exit code 2 before
any network call. It must already exist and must be a fork of `upstream`. Its `main` branch is never
used as a base — branches start from `upstream/<base-branch>`.

### `github-token`

Passed to the action through `INPUT_TOKEN`, never as a command-line argument, and never echoed: it is
wrapped in a `Secret` whose `__repr__` is `***`, and any token appearing in git's own output is
scrubbed before it reaches the log.

| Scope | classic PAT | fine-grained PAT |
| --- | --- | --- |
| push to `fork` | `public_repo` | **Contents:** read and write |
| open the PR on `upstream` | `public_repo` | **Pull requests:** read and write |

`secrets.GITHUB_TOKEN` does not work: it is scoped to the repository running the workflow and cannot
reach another repository. The action detects that case (`ghs_…`) and warns before pushing. An empty
value is reported as an empty secret with instructions naming this input — see
[Credential failures](docs/GUIDE.md#credential-failures).

### `dry-run`

`true`, `1` or `yes` (case-insensitive) enable it. A dry run needs **no token**, writes nothing to
git or the API, and still prints the report, the outputs and the summary — which makes it the right
first step in any workflow.

### `title` / `description`

When empty they are derived:

- title — `Add recipe for <name>` or `Add recipes for <a>, <b>`
- body — a bullet list of packages with versions, a checklist, and an explicit statement that
  review, merging and publication remain with conda-forge maintainers

### `mode`

| Value | Branches for three recipes | Pull requests |
| --- | --- | --- |
| `single` | `submit/a-b-c` | 1 |
| `per-recipe` | `submit/a`, `submit/b`, `submit/c` | 3 |

### `branch-prefix`

Sanitised to a branch-safe slug and capped at 24 characters: `ci` → `ci/cool-lib`. Non-ASCII is
folded, `_`/`.`/runs of `-` collapse to `-`, and an empty result falls back to `recipes`.

### `upstream` / `base-branch`

Defaults target the real staged-recipes repository. Both exist so the action can be tested against a
throwaway repository: `upstream: me/staged-recipes-playground`.

### `python-version`

Any version `actions/setup-python` can install; 3.11–3.13 are tested. The action then runs
`pip install pyyaml==6.0.2` and nothing else.

## Outputs

| Name | Type | Content |
| --- | --- | --- |
| `pull-request-urls` | newline-separated | Every pull request created or reused by this run; empty on a dry run |
| `branches` | newline-separated | Every submission branch, in the order they were processed |
| `report` | JSON string | The full report — see below |

```yaml
- run: |
    echo "branches: ${{ steps.submit.outputs.branches }}"
    echo '${{ steps.submit.outputs.report }}' | jq -r '.results[].outcome'
```

Dry runs publish no `pull-request-url`, but `branches` still lists what *would* be pushed, so a plan
job can be diffed against the apply job.

### `report`

```json
{
  "dry_run": true,
  "ok": true,
  "issues": [
    {
      "code": "VAL005",
      "severity": "warning",
      "path": "recipe.yaml",
      "message": "Recipe directory is 'demo' but the package is 'demo-pkg'.",
      "hint": "the pull request will create recipes/demo-pkg/"
    }
  ],
  "results": [
    {
      "branch": "submit/demo-pkg",
      "packages": ["demo-pkg"],
      "outcome": "planned",
      "pull_request": null
    }
  ]
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `dry_run` | boolean | Mirrors the input |
| `ok` | boolean | False when any issue has `severity: "error"` |
| `issues[]` | array | `code`, `severity` (`error` \| `warning`), `path`, `message`, `hint` |
| `results[]` | array | `branch`, `packages`, `outcome`, `pull_request` (URL or `null`) |
| `results[].outcome` | enum | `planned` (dry run), `created`, `updated`, `reused` |

Outcomes: `created` — a new branch and pull request; `updated` — an existing branch moved forward
with the new recipes; `reused` — nothing changed, the existing pull request is reported again;
`planned` — dry run only.

Issue codes (`VAL001`–`VAL011`, `DUP001`, `DUP002`) are listed in the
[error reference](docs/GUIDE.md#error-reference).

## Exit codes and failure semantics

| Code | Meaning | Typical cause |
| --- | --- | --- |
| `0` | Success | Recipes submitted, reused, or planned |
| `1` | Runtime failure | Git or GitHub API failure, rejected push, refusing to overwrite |
| `2` | Input or validation failure | Bad `fork`, missing token, unreadable recipe, error-severity findings, `ok: false` |

A run is **all-or-nothing per unit**: recipes that fail validation stop the run before any branch is
pushed, and nothing is written for the units that did not get that far. Warnings never change the
exit code.

Failures print `staged-recipes-submit: <message>` plus an indented `hint:` line, and are repeated as
`::error::` annotations so they survive a failing step. Non-fatal credential problems are emitted as
`::warning::` annotations.

## Behaviour contract

Guaranteed by the implementation and by tests:

| Guarantee | Detail |
| --- | --- |
| No merge, ever | The action calls `POST /repos/{upstream}/pulls` and `GET …/pulls`; it never calls a merge, review, or release endpoint |
| No publication | No build, no upload, no registry: acceptance and builds stay with conda-forge |
| Nothing outside `recipes/<name>` | Every write is bounded by `safe_relative`; path traversal is refused |
| No overwrite of other packages | An existing `recipes/<name>/` that declares a different package is refused (`Refusing to overwrite …`) |
| Duplicate detection | `DUP001` (same package twice in one run) always runs; `DUP002` (package already in the target checkout) runs when a checkout is supplied, i.e. with `--staged-recipes-root` |
| Idempotent reruns | Same recipes → `reused`; changed recipes → `updated` via `--force-with-lease` |
| Deterministic order | Recipes are sorted by package name before grouping, so branches and titles are stable |
| Token never logged | `Secret.__repr__` is `***`; git stderr is scrubbed |
| Dry run is inert | No clone, no branch, no push, no API call, no token required |

Side effects of a real run: one clone of the fork under `$RUNNER_TEMP/staged-recipes` (or
`--workdir`), one branch per unit, one commit per changed unit, one pull request per unit.

## Environment variables

Read by the composite path (`scripts/run.py action`):

| Variable | Set by | Purpose |
| --- | --- | --- |
| `INPUT_RECIPES` | `action.yml` | `inputs.recipes` |
| `INPUT_FORK` | `action.yml` | `inputs.fork` |
| `INPUT_TOKEN` | `action.yml` | `inputs.github-token` |
| `INPUT_DRY_RUN` | `action.yml` | `inputs.dry-run` |
| `INPUT_TITLE`, `INPUT_DESCRIPTION`, `INPUT_MODE` | `action.yml` | optional overrides |
| `INPUT_BRANCH_PREFIX`, `INPUT_UPSTREAM`, `INPUT_BASE_BRANCH` | `action.yml` | optional overrides |
| `ACTION_PATH` | `action.yml` | Location of the action checkout |
| `PYTHONPATH` | `action.yml` | Puts the checkout on the import path |
| `GITHUB_OUTPUT` | runner | Receives `pull-request-urls`, `branches`, `report` |
| `GITHUB_STEP_SUMMARY` | runner | Receives the Markdown summary |
| `RUNNER_TEMP` | runner | Parent of the work directory |
| `GITHUB_TOKEN` / `GH_TOKEN` | you | CLI fallback when `--token` is absent |

The summary step reads `REPORT_JSON` (fed from `steps.submit.outputs.report`).

## CLI reference

Installed as `staged-recipes-submit`, or `python -m staged_recipes_submit`. Every action input has a
flag; the CLI adds three flags the action cannot express.

| Flag | Default | Notes |
| --- | --- | --- |
| `--recipe`, `-r PATH` | — | **required**, repeatable; mirrors `recipes` |
| `--fork OWNER/REPO` | — | **required** |
| `--token TOKEN` | `$GITHUB_TOKEN`, `$GH_TOKEN` | never logged |
| `--dry-run` | off | no writes, no token needed |
| `--title TITLE` | derived | |
| `--description`, `--body BODY` | derived | |
| `--mode {single,per-recipe}` | `single` | |
| `--branch-prefix PREFIX` | `submit` | |
| `--upstream OWNER/REPO` | `conda-forge/staged-recipes` | |
| `--base-branch BRANCH` | `main` | |
| `--workdir PATH` | `./.staged-recipes` | where the fork is cloned |
| `--staged-recipes-root PATH` | — | a staged-recipes **`recipes/`** directory; enables `DUP002` by checking `recipes/<name>` there |
| `--json` | off | print the report as JSON instead of text |
| `--version` | — | prints the version and exits |

```bash
staged-recipes-submit -r recipes/cool-lib -r recipes/cool-cli \
  --fork octocat/staged-recipes --mode per-recipe --dry-run --json
```

## Dispatcher commands

`python scripts/run.py <command> [args…]` is the single entry point used by `action.yml`, by
`pixi run <task>`, and by contributors.

| Command | Runs | Used by |
| --- | --- | --- |
| `action` | `action_entry.main()` — reads `INPUT_*` | the composite action |
| `submit` | `cli.main(argv)` — explicit arguments | `pixi run submit`, humans |
| `summary` | `action_summary.main()` — reads `REPORT_JSON` | the composite action |
| `validate` | layout, versions, workflow and action-contract policy | `pixi run validate`, CI |
| `fmt`, `fmt-check`, `lint`, `type-check`, `test`, `coverage`, `ci` | quality gates | `pixi run ci`, lefthook |
| `setup`, `check-tools`, `hooks-install` | workspace bootstrap | `pixi run setup` |
| `hook-commit-msg`, `hook-pre-commit`, `hook-pre-push`, `commit-check` | git hooks | lefthook |
| `sandbox` | pixi-sandbox plan/publish | the offline workflow |

`python scripts/run.py --help` lists them; an unknown command exits 2.

## Python API

```python
from pathlib import Path

from staged_recipes_submit import SubmissionMode, SubmissionRequest, inspect, run_submission

request = SubmissionRequest(
    recipes=(Path("recipes/cool-lib"),),
    fork="octocat/staged-recipes",
    mode=SubmissionMode.SINGLE,  # or SubmissionMode.PER_RECIPE
    dry_run=True,
)
recipes, issues, units = inspect(request)  # nothing is written
report = run_submission(request, git=..., pull_requests=...)  # backends are injectable
print(report.to_dict())
```

| Object | Signature | Notes |
| --- | --- | --- |
| `SubmissionRequest` | `recipes, fork, upstream=…, base_branch=…, mode=…, title=…, body=…, branch_prefix="submit", dry_run=False, base_dir=…, staged_recipes_root=…` | validates `fork`/`upstream` on construction |
| `inspect(request)` | → `(recipes, issues, units)` | discovery + validation + planning, no side effects |
| `run_submission(request, *, git, pull_requests)` | → `SubmissionReport` | pure orchestration over two backend protocols |
| `SubmissionReport.to_dict()` | → `dict` | the exact JSON published in the `report` output |
| `SubmissionReport.render()` | → `str` | the text report printed to the log |
| `discover_recipes(sources, base=None)` | → `list[Recipe]` | |
| `validate_recipes(recipes)` | → `list[Issue]` | |
| `detect_duplicates(recipes, …)` | → `list[Issue]` | |
| `build_plan(recipes, mode=…, title=…, body=…, branch_prefix=…)` | → `list[SubmissionUnit]` | |
| `Secret(value)` | `.reveal()` | `str`/`repr` are `***` |
| `SubmissionError` and subclasses | `.message`, `.hint` | `ConfigurationError`, `PathSafetyError`, `RecipeDiscoveryError`, `RecipeValidationError`, `DuplicateRecipeError`, `GitError`, `PullRequestError` |

Entry points for embedding the action itself:

| Callable | Contract |
| --- | --- |
| `staged_recipes_submit.cli.main(argv)` | returns the exit code; never raises `SubmissionError` |
| `staged_recipes_submit.action_entry.main(environment=None)` | reads a mapping (defaults to `os.environ`), writes `$GITHUB_OUTPUT`, returns the exit code |
| `staged_recipes_submit.action_summary.main(environment=None)` | renders `REPORT_JSON` into `$GITHUB_STEP_SUMMARY` |

Both backends are protocols: `prepare`, `checkout_or_create`, `materialize`, `commit`, `push` for git,
and `find_open`, `create` for GitHub. `DryRunGuard` implements dry runs by raising on any of them,
which is why a dry run cannot write even by accident.

## Compatibility and versioning

| Policy | Detail |
| --- | --- |
| Pin by tag or SHA | `@v1`, `@v1.2.3` or a 40-hex commit SHA; the ref *is* the code that runs — nothing is published or downloaded |
| Inputs | never removed or renamed within a major version; new inputs are optional with defaults |
| Outputs | existing names and meanings are stable; new outputs may be added |
| Report JSON | additive fields only; existing keys keep their meaning |
| Exit codes | `0`/`2` are stable; a new failure class would use `1` |
| Python | 3.11–3.13, single runtime dependency `pyyaml==6.0.2` |
| Platform | Linux runners tested; macOS expected to work; Windows is unsupported (composite steps use `bash`) |

Version parity across `pyproject.toml`, `pixi.toml`, `config/project.toml` and
`staged_recipes_submit/_version.py` is enforced by `pixi run validate`.
