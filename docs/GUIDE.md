# User guide

`staged-recipes-submit` takes one or more conda recipes and turns them into a reviewed pull request
against `conda-forge/staged-recipes`. It validates first, refuses duplicates, writes only inside
`recipes/<package-name>/` on a branch in **your fork**, and stops there: merging, building and
publishing stay inside conda-forge's normal process.

- [Before you start](#before-you-start)
- [Quick start](#quick-start)
- [Inputs](#inputs)
- [Outputs](#outputs)
- [Submission modes and branch names](#submission-modes-and-branch-names)
- [Dry runs](#dry-runs)
- [Reruns are idempotent](#reruns-are-idempotent)
- [How the action gets its code](#how-the-action-gets-its-code)
- [Security model](#security-model)
- [Examples](#examples)
- [Exit codes and the JSON report](#exit-codes-and-the-json-report)
- [Error reference](#error-reference)
- [Limits](#limits)
- [FAQ](#faq)

## Before you start

1. **Fork `conda-forge/staged-recipes`** and keep your fork's `main` branch untouched (the action
   branches from `upstream/main`, never from your fork's tip).
2. **Create a token** the action can use:
   - *Classic PAT*: `public_repo`. That is enough to push to your fork and open a pull request
     against a public upstream.
   - *Fine-grained PAT*: on your fork, **Contents: Read and write** + **Pull requests: Read and
     write**; add `conda-forge/staged-recipes` with **Pull requests: Read and write** so the pull
     request can be created there.
   - `${{ secrets.GITHUB_TOKEN }}` only works when the fork **is** the repository running the
     workflow: a workflow token cannot reach into another repository.
3. **Give the job a runner with git and Python.** The action installs its own Python with
   `actions/setup-python`. Tested on `ubuntu-24.04`; macOS should work; Windows is untested because
   the composite steps use `bash`.

Your recipes must not already exist in staged-recipes: if `recipes/<name>/` is present in the
upstream tree, the action refuses the submission instead of overwriting it.

## Quick start

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
        with:
          persist-credentials: false
      - uses: Archont561/staged-recipes-submit@v1
        with:
          recipes: |
            recipes/my-package/recipe.yaml
          fork: my-user/staged-recipes
          github-token: ${{ secrets.STAGED_RECIPES_TOKEN }}
```

The run prints a report, writes step outputs and appends a summary table to the job summary.

## Inputs

Full signatures, exit codes, the report schema, the CLI and the Python API live in
[`API.md`](../API.md).

| Input | Required | Default | Notes |
| --- | --- | --- | --- |
| `recipes` | yes | — | Newline- or comma-separated paths. Each is a directory holding `recipe.yaml`/`meta.yaml`, or the recipe file itself. Nested directories are searched up to four levels deep. |
| `fork` | yes | — | `owner/repo` of your staged-recipes fork. Must already exist. |
| `github-token` | yes | — | See [Before you start](#before-you-start). Never echoed; passed through the environment, not a command line. |
| `dry-run` | no | `false` | Validate and print the plan; no clone, branch, push or API call. |
| `title` | no | derived | Pull-request title. |
| `description` | no | derived | Pull-request body. |
| `mode` | no | `single` | `single` = one pull request for every recipe; `per-recipe` = one pull request each. |
| `branch-prefix` | no | `submit` | Prefix of the submission branch. |
| `upstream` | no | `conda-forge/staged-recipes` | Owner/repo that receives the pull request. |
| `base-branch` | no | `main` | Base branch of the pull request. |
| `python-version` | no | `3.13` | Interpreter used to run the action. 3.11–3.13 are supported. |

## Outputs

| Output | Example | Meaning |
| --- | --- | --- |
| `pull-request-urls` | `https://github.com/conda-forge/staged-recipes/pull/12345` | One URL per line, for every pull request created or reused. |
| `branches` | `submit/hello-world` | One branch per line. |
| `report` | `{"dry_run":false,…}` | The whole JSON report (below). |

## Submission modes and branch names

| Mode | Recipes | Pull requests | Branch |
| --- | --- | --- | --- |
| `single` | `alpha` | 1 | `submit/alpha` |
| `single` | `alpha`, `beta` | 1 | `submit/alpha-beta` |
| `single` | 4 or more | 1 | `submit/batch-4-<8 hex>` |
| `per-recipe` | `alpha`, `beta` | 2 | `submit/alpha`, `submit/beta` |

Branch names are derived from package names only, sorted and hash-suffixed once a group gets large.
That is what makes reruns safe and keeps branches short enough for Git.

## Dry runs

```yaml
- uses: Archont561/staged-recipes-submit@v1
  with:
    recipes: recipes/my-package/recipe.yaml
    fork: my-user/staged-recipes
    github-token: ${{ secrets.STAGED_RECIPES_TOKEN }}
    dry-run: true
```

A dry run reports issues and the planned branches, and returns `planned` for every unit. It is
enforced structurally: the dry-run backends raise if anything attempts a write, so a regression
fails the job instead of quietly pushing. Use it in pull requests that add recipes.

## Reruns are idempotent

| Situation | Outcome |
| --- | --- |
| First submission | `created` — branch pushed, pull request opened |
| Same recipes again, nothing changed | `reused` — the open pull request is reported, nothing is pushed |
| Same recipes, but files changed | `updated` — the branch is force-pushed with a lease, the pull request stays open |
| A recipe now fails validation | The run stops before any write and reports the issues |

Branches are force-pushed **with lease**, so a concurrent change in the fork is never overwritten
silently.

## How the action gets its code

There is nothing to download. `action.yml` is a composite wrapper around this repository:

1. `actions/setup-python` installs the interpreter named by `python-version`.
2. `pip install pyyaml==6.0.2` installs the single third-party import (pinned exactly in
   `action.yml`, required as `pyyaml>=6.0.2` in `pyproject.toml`; `pixi run validate` keeps the two
   in agreement).
3. `PYTHONPATH=${{ github.action_path }}` puts the action checkout on the import path.
4. `python "$ACTION_PATH/scripts/run.py" action` reads the `INPUT_*` variables and runs the
   submission; `… run.py summary` renders the job summary.

`scripts/run.py` is the same dispatcher contributors use locally, so the action cannot drift from
the documented workflow — `pixi run submit --recipe … --fork …` runs the identical code path.

**Pinning:** `@v1.2.3`, `@v1` and a full commit SHA all work, because the code lives at that ref.
Pin a commit SHA if you want immutability; there is no separate artifact whose digest could be
verified, and none is needed.

**Air-gapped runners:** the only network access is `pip install pyyaml==6.0.2`. Mirror that wheel in
your internal index, or pre-install it in your runner image and set `python-version` to that
interpreter — the action never fetches anything else.

## Security model

| Concern | Behaviour |
| --- | --- |
| Token exposure | Inputs arrive as environment variables, never interpolated into a command line. Tokens are wrapped in a `Secret` whose `__repr__` is `Secret(***)`, used only in an in-process git auth header and the API `Authorization` header. |
| Least privilege | The action needs `contents: write` and `pull_requests: write` on the fork, and pull-request creation on the upstream. It never merges, never tags, never publishes. |
| Path safety | User paths must resolve inside the workspace; symlinks out of a recipe are refused; package names must match conda's safe alphabet; nothing outside `recipes/<package-name>/` is written. |
| Unrelated recipes | An existing `recipes/<name>/` that does not declare the same package is never replaced. |
| Unsafe names | `..`, absolute paths, NUL bytes and names over 64 characters are rejected before any git command. |
| Code origin | The action runs this repository's `scripts/` at the ref you pinned. No artifact is downloaded, so there is no digest to trust on top of the checkout. |
| Pinned actions | Every third-party action in this repository is pinned to a 40-hex SHA in `config/actions.lock.json`, enforced by `pixi run validate`. |

## Examples

Several recipes in one pull request:

```yaml
    - uses: Archont561/staged-recipes-submit@v1
      with:
        recipes: |
          recipes/alpha/recipe.yaml
          recipes/beta/meta.yaml
        fork: my-user/staged-recipes
        github-token: ${{ secrets.STAGED_RECIPES_TOKEN }}
        title: Add alpha and beta
        description: Both were validated against conda-forge's recipe guidelines.
```

One pull request per recipe, driven from a matrix:

```yaml
jobs:
  submit:
    runs-on: ubuntu-24.04
    strategy:
      matrix:
        recipe: [recipes/alpha/recipe.yaml, recipes/beta/recipe.yaml]
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: Archont561/staged-recipes-submit@v1
        with:
          recipes: ${{ matrix.recipe }}
          fork: my-user/staged-recipes
          github-token: ${{ secrets.STAGED_RECIPES_TOKEN }}
          mode: per-recipe
```

Preview in a pull request, submit on a tag:

```yaml
on:
  pull_request:
    paths: ['recipes/**']
  workflow_dispatch:

jobs:
  submit:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: Archont561/staged-recipes-submit@v1
        with:
          recipes: ${{ github.event_name == 'workflow_dispatch' && 'recipes/my-package/recipe.yaml' || 'recipes/' }}
          fork: my-user/staged-recipes
          github-token: ${{ secrets.STAGED_RECIPES_TOKEN }}
          dry-run: ${{ github.event_name == 'pull_request' }}
```

## Exit codes and the JSON report

| Code | Meaning |
| --- | --- |
| `0` | Every planned unit succeeded (or the dry run is clean). |
| `2` | Input or recipe problem: bad path, unsafe name, invalid recipe, duplicate package. Nothing was written. |
| `1` | Unexpected failure: git or the GitHub API refused an operation. |

```json
{
  "dry_run": false,
  "ok": true,
  "issues": [
    {"code": "VAL006", "severity": "warning", "path": "recipe.yaml",
     "message": "The recipe does not declare a version.", "hint": "a missing version usually breaks the feedstock bot later"}
  ],
  "results": [
    {"branch": "submit/alpha", "packages": ["alpha"], "outcome": "created",
     "pull_request": "https://github.com/conda-forge/staged-recipes/pull/12345"}
  ]
}
```

`ok` is false only when an issue has `severity: "error"`. Warnings are reported and never block a
submission.

## Error reference

| Code | Meaning | What to do |
| --- | --- | --- |
| `VAL001` | File is not named `recipe.yaml` or `meta.yaml` | Rename it; staged-recipes accepts one recipe per directory. |
| `VAL002` | The recipe is not valid YAML, is empty, or is not a mapping | Fix the YAML. The message names the first parser error. |
| `VAL003` | No `package.name` | Add a `package:` section. |
| `VAL004` | Unsafe package name (uppercase, spaces, `/`, `..`, too long) | Use lowercase letters, digits, `.`, `_`, `-`. |
| `VAL005` | *warning*: directory name ≠ package name | Expected when your source directory is not named after the package; the pull request uses the package name. |
| `VAL006` | *warning*: no version | Add one; the feedstock bot expects it later. |
| `VAL007` | *warning*: no `about` section | Add summary, license and home. |
| `VAL008` | *warning*: v0 recipe without `source` | Add a source url/path. |
| `VAL010` | A file exceeds 5 MiB | Reference it by URL in the recipe instead of vendoring it. |
| `VAL011` | The recipe totals more than 10 MiB | Keep only the files the build needs. |
| `DUP001` | The same package appears twice in one invocation | Drop one path. |
| `DUP002` | `recipes/<name>/` already exists upstream | Update the existing recipe/feedstock instead of resubmitting. |
| — | `both recipe.yaml and meta.yaml` | Keep exactly one recipe file per directory. |
| — | `No GitHub token was provided for pushing to <fork>` | The `github-token` input is empty — see [Credential failures](#credential-failures). |
| — | `HTTP 401` | GitHub rejected the token outright: invalid, expired or revoked. Create a new one and update the secret. |
| — | `HTTP 403` | The token was accepted but lacks permission: needs `contents: write` on the fork and `pull_requests: write` on the upstream, from the fork's owner. If the message mentions a rate limit, wait instead. |
| — | `HTTP 404` | Wrong `fork`/`upstream` slug, or the token cannot see the repository. |
| — | `HTTP 422` | A pull request for that branch usually already exists, or the branch was never pushed. |
| — | `could not read Username … terminal prompts disabled` | Git could not authenticate at all — usually the same empty-secret cause; check the token. |
| — | `Refusing to overwrite …` | The fork already has `recipes/<name>/` for another package. Remove it in the fork. |

### Credential failures

An unset or misspelled secret expands to an **empty string**, and GitHub does not warn about it, so
the first symptom is an empty `github-token` input. The action reports that case explicitly:

```
::error::No GitHub token was provided for pushing to octocat/staged-recipes.  hint: set the
`github-token` input, e.g. `github-token: ${{ secrets.CONDA_FORGE_TOKEN }}`, and define that secret
under Settings > Secrets and variables > Actions. … `secrets.GITHUB_TOKEN` is scoped to the
repository running the workflow and cannot push to a fork …
```

`::error::` and `::warning::` are GitHub annotations, so they appear on the run page and in the
`Annotations` panel even after a later step fails, in addition to the plain-text line.

Before pushing, the token's *shape* is checked and mismatches are reported as warnings:

| What you passed | What you see |
| --- | --- |
| Nothing / empty secret | `error` naming the input, the secret store, and the fork |
| `secrets.GITHUB_TOKEN` (`ghs_…`) | `warning`: a GitHub App installation token is scoped to one repository and cannot push to a fork |
| A string with no `ghp_` / `github_pat_` / `gho_` prefix | `warning`: probably the wrong value or stray whitespace |
| `ghp_…` or `github_pat_…` | no warning |

Token contents are never echoed, at any verbosity: messages name the token *family*, and any token
that appears in git's own output is scrubbed to `***` before it reaches the log.

`--dry-run` (and `dry-run: true`) needs **no credentials at all** — validation, duplicate checks and
the plan work without a token, which is why you can rehearse a submission before creating a secret.

## Limits

| Limit | Value | Where |
| --- | --- | --- |
| Per-file size | 5 MiB | `validation.MAX_FILE_BYTES` |
| Per-recipe size | 10 MiB | `validation.MAX_RECIPE_BYTES` |
| Directory search depth | 4 levels | `discovery.MAX_SEARCH_DEPTH` |
| Package name length | 64 characters | `paths.MAX_PACKAGE_NAME_LENGTH` |
| Branch name group size | 3 names inline, then a hash | `plan.MAX_INLINE_NAMES` |

## FAQ

**Does it merge or publish anything?** No. It opens a pull request. Review, CI, merging, feedstock
creation and any package publication stay with conda-forge.

**Do I need conda or conda-build installed?** No. The action only reads recipes; an actual build is
conda-forge CI's job.

**Can I submit a `meta.yaml` (v0) and a `recipe.yaml` (v1) in the same run?** Yes; mixed batches are
supported and each recipe is copied into its own directory.

**What if two of my recipes depend on each other?** Submit them together in one pull request
(`mode: single`) so reviewers see the relationship.

**Can I use it outside conda-forge?** Point `upstream` at another repository with the same
`recipes/<name>/` layout. Nothing else is hard-coded.

**Is there a package to install?** No. Nothing is published — not to PyPI, not as release assets. The
action runs the repository's scripts, and `pip install -e .` is only a developer convenience. See
[How the action gets its code](#how-the-action-gets-its-code).
