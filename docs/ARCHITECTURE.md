# Architecture

## Runtime stages

```
0  wrapper        action.yml (composite): setup-python, pip install pyyaml==6.0.2
1  dispatcher     python "$ACTION_PATH/scripts/run.py" action      (PYTHONPATH = action checkout)
2  entry          staged_recipes_submit.action_entry: INPUT_* -> argv
3  workflow       discover -> validate -> duplicates -> plan -> execute
```

There is no build step and no artifact. The package lives at the repository root (no `src/`) and is
imported straight from the checkout, so the ref pinned in `uses:` is exactly what runs. `scripts/` is
the only automation surface, and `action.yml` is held to it: `quality._check_action_contract`
refuses a step that does not call the dispatcher, any install of the checkout, and the retired
distribution inputs.

## One flow, five seams

```
action.yml (composite)
  -> python -m staged_recipes_submit.action_entry       inputs -> CLI arguments
     -> cli.build_request                              inputs -> SubmissionRequest
        -> submit.inspect                              discover -> validate -> duplicates -> plan
        -> submit.run_submission                       execute against two protocols
           -> GitBackend          (gitops.SubprocessGit | tests' FakeGit | DryRunGuard)
           -> PullRequestBackend  (github.GitHubPullRequests | tests' FakePullRequests | DryRunGuard)
```

Everything above the two protocols is pure Python over local files, which is why the whole workflow
is testable without a GitHub token.

## Modules

| Module | Responsibility | Refuses |
| --- | --- | --- |
| `paths` | package-name and path hygiene, branch slugs | escapes, symlinks out of the recipe, unsafe names |
| `parsing` | tolerant YAML reading, `${{ version }}` context | never raises; returns errors |
| `discovery` | recipe roots, supporting files, de-duplication | ambiguous `recipe.yaml` + `meta.yaml` |
| `validation` | static, structural checks | nothing is fatal until the caller decides |
| `duplicates` | intra-batch and upstream collisions | submitting a package that already exists |
| `plan` | branch names, titles, bodies, grouping | non-deterministic branch names |
| `submit` | orchestration, idempotency, reporting | any write when validation failed |
| `gitops` | clone, fetch, branch, copy, commit, push | overwriting a directory that declares another package |
| `github` | `GET /pulls`, `POST /pulls` | any token in a URL or log line |

## Guarantees and where they live

| Guarantee | Enforced by |
| --- | --- |
| Invalid recipes cause no remote change | `submit.inspect` runs before `git.prepare`; tests assert zero backend calls |
| Duplicates are reported with a hint | `duplicates.detect_duplicates` + `Issue.hint` |
| Dry runs perform no remote writes | `backends.DryRunGuard` raises on every attribute call |
| Reruns do not duplicate branches or PRs | deterministic `plan.branch_name` + `PullRequestBackend.find_open` |
| Unrelated recipes are never overwritten | `gitops._assert_same_package` |
| Tokens never reach logs | `errors.Secret`, `GitBackend` environment header, environment-passed inputs |
| Only pinned actions run | `scripts/quality.py::_check_uses` against `config/actions.lock.json` |
| Final acceptance stays with conda-forge | no merge or publish code path exists; PR body states the handover |
| The container matches the repository pins | `quality._check_devcontainer` (digest-pinned base image, verified Pixi download, same Pixi version, `.pixi` volume, dispatcher-only provisioning) |
| The README stays an index, not a manual | `quality._check_docs` (length budget, every `docs/*.md` linked, every guide anchor resolvable) |
| The offline plan matches the workspace | `quality.check_sandbox_config`, `quality._check_sandbox_pin`, `tests/unit/test_sandbox_config.py` |
| A missing secret is a loud, specific failure | `credentials.missing_token_error` (action wording vs CLI wording), `credentials.warnings` (token family checks), `::error::`/`::warning::` annotations |
| The action runs this repository's code, nothing else | `quality._check_action_contract`: dispatcher-only steps, `PYTHONPATH` = action checkout, no checkout install, no distribution inputs, pinned `pyyaml` |
| Nothing is published | `config/project.toml` (`publish.pypi = false`, `publish.release = false`, `publish.action = true`); `release.yml` cuts tags and an assetless GitHub Release only (`quality._check_release_workflow`) |

## Idempotency

Branch names are derived from package names only (`submit/<name>`, `submit/<a>-<b>`, or
`submit/batch-<n>-<hash>` for larger groups). A rerun therefore targets the same branch, computes the
same commit content, finds the open pull request for that head and reports `reused` (or `updated`
when the recipe changed). Nothing is ever force-created twice.

## Distribution: none

```
git tag v0.2.0 ──► consumers pin it:  uses: Archont561/staged-recipes-submit@v0.2.0
                                      └─ setup-python → pip install pyyaml → run scripts/

No registry  ├─ no publish token to leak
No assets    ├─ no wheel, no checksum file, no version resolution
No build     └─ the tag is the artifact
```

This is the deliberate trade against a released package: you lose `pip install staged-recipes-submit`
and a separately verifiable artifact, and you gain a repository with one runtime path, no release
workflow to maintain, and an action that cannot drift from the code its own tests exercise.
`pyproject.toml` still describes an installable project so `pip install -e .` works for contributors;
it is simply never published.

## Offline transport

```
pixi-sandbox.toml  (reviewed: bundles, platforms, runners, budgets, workflow policy)
        │
        ├─ pixi run sandbox plan       → matrix: bundle × platform → branch, runner
        ├─ pixi run sandbox publish    → orphan branch sandbox/dev-<platform>
        │                                (packages, tools, manifest, SHA-256 per file)
        └─ restore.sh on the airlocked host → verified environment, no registry access
```

`scripts/quality.py::check_sandbox_config` is the contract: the plan may only name environments and
platforms `pixi.toml` defines, every platform needs an explicit runner label, `cargo_vendor` stays
false because this repository has no `Cargo.lock`, budgets are positive with `max_blob_mib ≤ 95`,
and `[workflow]` keeps the generated publisher least-privilege and on the same Pixi release as CI.
`config/sandbox-bootstrap.json` records the CLI version and must agree with `pixi.toml`'s `offline`
feature.

Generated files (`restore.sh`, `publish-sandbox.yml`, `relock.yml`) are allowed to exist and are
held to a policy rather than to the `pixi run` one-task rule: top-level `contents: read`, and any
job holding `contents: write` must carry an explicit `if` guard.

## Extension points

- **Different upstream**: pass `upstream`; nothing is hard-coded outside `submit.DEFAULT_UPSTREAM`.
- **Different remote host**: `gitops.SubprocessGit(url_for=...)` and `github.GitHubPullRequests(api_url=...)`.
- **New checks**: add a function returning `Issue` objects and call it from `submit.inspect`.
- **Another distribution channel**: consumers can pin a tag or a commit SHA; if you later want a
  published artifact, add it beside the scripts and teach `quality._check_action_contract` about it.
