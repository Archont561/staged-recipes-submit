# Development workflow

## Quick start

### Option A — dev container (nothing installed on the host)

Open the repository in VS Code and pick **Reopen in Container** (or run
`devcontainer up --workspace-folder .` with the Dev Containers CLI). The container provides Pixi,
git, the Python toolchain through the locked environment, and the recommended extensions.

- Base image is pinned by digest, and the Pixi binary is downloaded from a pinned release and
  verified against its published `.sha256` before it is installed.
- `.pixi/` is a named volume: it must not live on a case-insensitive bind mount, because some conda
  packages ship files that differ only in case.
- `postCreateCommand` runs `.devcontainer/post-create.sh`, which does nothing but
  `pixi run --locked setup` and `pixi run --locked ci` — the same tasks you would run by hand.
- `pixi run validate` holds the container to the repository pins: the base image digest, the Pixi
  version (it must equal every workflow's `setup-pixi` input and `pixi-sandbox.toml`), the
  recommend extensions, the `.pixi` volume and the no-bespoke-installs rule.

### Option B — host machine

```bash
pixi run setup     # locked environment + tools + Git hooks
pixi run ci        # what CI runs, on your machine
```

## What each check proves

| Task | Proves |
| --- | --- |
| `validate` | layout, versions, one-workflow policy, every `uses:` pinned to a 40-hex SHA in `config/actions.lock.json`, every `run:` a single Pixi task, coverage gate ≥ 90 |
| `lint` / `fmt-check` | ruff correctness and formatting |
| `type-check` | mypy strict over the package |
| `test` | unit, property, BDD and integration tests; live GitHub tests skipped |
| `coverage` | branch coverage, fails under 90 %, writes `coverage.xml` |
| `ci` | all of the above, in that order |

## Test layers

| Layer | Directory | Talks to |
| --- | --- | --- |
| unit | `tests/unit` | nothing |
| property | `tests/property` | nothing; Hypothesis generates paths, names and documents |
| BDD | `tests/bdd` | in-memory Git and GitHub doubles |
| integration | `tests/integration` | a real `git` binary and a local bare repository |
| live | `tests/live` | the real GitHub API, read-only, opt-in |

Live tests never write. Run them explicitly:

```bash
GITHUB_TOKEN=... pixi run test --run-live tests/live
```

## Coverage

`pytest --cov` with `branch = true`. The gate lives in `pyproject.toml`
(`[tool.coverage.report] fail_under = 90`) and is re-checked by `validate`, so lowering the gate is
a visible, reviewable change rather than a quiet edit.

## Offline work

`pixi-sandbox.toml` is the reviewed plan for the offline transport. It ships with this repository,
so there is nothing to invent before you can use it:

```toml
schema = 2
branch_prefix = "sandbox"
cargo_vendor = false            # no Cargo.lock here; pixi-sandbox defaults this to true

[[bundle]]
name = "dev"
environments = ["default"]      # one bundle: the dev environment
platforms = ["linux-64", "osx-arm64", "win-64"]
cargo_vendor = false

[runners]                       # explicit labels, not ubuntu-latest-style defaults
linux-64 = "ubuntu-24.04"
osx-arm64 = "macos-15"
win-64 = "windows-2025"

[budgets]                       # the generated publisher's pre-publish doctor gate
max_blob_mib = 95               # the Git limit; split a pack instead of raising it
max_transport_mib = 1500
max_repository_push_mib = 1500
max_restore_required_mib = 6144

[workflow]                      # policy for the generated publisher
permissions = true              # contents: read top-level, contents: write only on publish
pixi_version = "v0.83.0"        # must match every other workflow's setup-pixi pin
setup_pixi_cache = false
```

`pixi run validate` re-checks all of it: schema 1–2, `cargo_vendor = false`, slug-safe bundle
names, every environment and platform actually existing in `pixi.toml`, an explicit runner per
platform, positive budgets with `max_blob_mib ≤ 95`, and a `[workflow]` table that is
least-privilege and pins the same Pixi as CI. The CLI version itself is pinned in
`config/sandbox-bootstrap.json` and must equal `pixi.toml`'s `offline` feature pin.

### Tier 1 — same machine, no network

```bash
pixi install --locked --all          # online, once; populates the cache
pixi install --frozen --offline      # later: no re-solve, no download
pixi run --frozen ci
```

A cache miss fails the install; this is convenience, not an airlock.

### Tier 2 — a verified, portable transport

On a connected machine:

```bash
pixi install --locked -e offline                       # the pinned pixi-sandbox CLI lives here
pixi run --locked -e offline sandbox plan              # matrix + branches the publisher will use
pixi run --locked -e offline sandbox publish           # writes sandbox/<bundle>-<platform> locally
```

`restore.sh`, `.github/workflows/publish-sandbox.yml` and `.github/workflows/relock.yml` are
**generated** by `pixi-sandbox init`. They are not in the tree yet: run `init` when you want the
airlock, review the generated diff, and commit it. Do not hand-edit them afterwards, and do not
re-run `plan` with `--envs` to work around a change in the plan — edit `pixi-sandbox.toml` and
regenerate. Once the publish workflow exists, `validate` allows it and holds it to the sandbox
policy (top-level `contents: read`, and any `contents: write` job must carry an explicit guard).

On the airlocked host (the repository plus its `sandbox/*` branches must be present):

```bash
bash restore.sh
export PATH="$HOME/.local/bin:$PATH"
pixi install --frozen --offline
pixi run --frozen ci
```

The generator pins the same action SHAs as `config/actions.lock.json`, so a generated workflow
passes the pin policy without an exemption.

## Debugging

```bash
pixi run test -x -vv                         # stop at first failure
pixi run test tests/bdd -k "duplicate"       # one scenario
pixi run coverage --no-cov-on-fail           # coverage despite failures
python -m staged_recipes_submit --help       # the CLI the action runs
python -m staged_recipes_submit -r path/to/recipe -r path/to/other \
  --fork you/staged-recipes --dry-run --json
```

A dry run never constructs a token, never clones and never calls GitHub: the dry-run backends raise
on any write attempt, so a dry-run regression fails loudly.

## Entry points

Nothing is published. Three surfaces run the same code:

| Surface | Command | Used by |
| --- | --- | --- |
| composite action | `python "$ACTION_PATH/scripts/run.py" action` | `action.yml`, reading `INPUT_*` variables |
| dispatcher | `pixi run submit --recipe … --fork … [--dry-run]` | humans, local reproduction of an action run |
| module | `python -m staged_recipes_submit …` | direct CLI use, `--json` reports |

`scripts/run.py` is the single dispatcher: `pixi run <task>` → `python scripts/run.py <command>` →
`<module>.<function>(argv)`. Exit codes pass through, so a failing submission fails the action.

### Releasing

A tag *is* the release — there is no build, no artifact and no registry:

```bash
pixi run ci
git tag v0.2.0 && git push origin v0.2.0      # consumers may pin v0.2.0 or the commit SHA
git tag -f v1 v0.2.0 && git push -f origin v1 # moving major tag, if you keep one
```

`pixi run validate` keeps the version identical in `pyproject.toml`, `pixi.toml`,
`config/project.toml` and `__init__.py`, and refuses an `action.yml` that stops calling the
dispatcher or that starts installing the checkout.

### Development install (optional)

```bash
pip install -e ".[dev]"     # or just: pixi run setup
```

The action never needs this: it imports the checkout from `PYTHONPATH`.

### What the action needs from a runner

- `python-version` (default 3.13; 3.11–3.13 supported).
- Network access to a package index for `pyyaml==6.0.2`, or a pre-seeded image. Nothing else.
- `git` for the push step; `bash` for the composite steps.

### Trust model

- **Code origin:** whatever ref you pin in `uses:` is the code that executes. Pin a commit SHA for
  immutability.
- **Third-party actions:** `actions/setup-python` is pinned to a 40-hex SHA in `config/actions.lock.json`.
- **Runtime dependency:** `pyyaml` is pinned exactly in `action.yml` and cross-checked by
  `pixi run validate` against `config/project.toml` and `pyproject.toml`.
- **No artifacts:** there is no wheel, checksum file or release asset that could be swapped
  independently of the repository.
