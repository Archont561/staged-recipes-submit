# staged-recipes-submit

[![CI](https://github.com/Archont561/staged-recipes-submit/actions/workflows/ci.yml/badge.svg)](https://github.com/Archont561/staged-recipes-submit/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/Archont561/staged-recipes-submit/branch/main/graph/badge.svg)](https://codecov.io/gh/Archont561/staged-recipes-submit)

A reusable GitHub Action that validates conda recipes and opens a pull request against
[`conda-forge/staged-recipes`](https://github.com/conda-forge/staged-recipes).

- **Validates first.** Structure, unsafe paths and duplicate packages are checked before anything is
  written, so a rejected recipe never leaves a branch behind.
- **Submits once.** Recipes land in `recipes/<package-name>/` on a branch in your fork; reruns reuse
  that branch and its open pull request instead of creating a second one.
- **Never merges, never publishes.** Review, builds, feedstock creation and any publication stay
  inside conda-forge's normal process.

```yaml
- uses: Archont561/staged-recipes-submit@v1
  with:
    recipes: |
      recipes/my-package/recipe.yaml
    fork: my-user/staged-recipes
    github-token: ${{ secrets.STAGED_RECIPES_TOKEN }}
    dry-run: false
```

Nothing is published: no PyPI package, no release assets, no wheel. The action runs the scripts in
this repository directly (`action.yml` → `scripts/run.py`), so the tag or commit SHA you pin in
`uses:` is exactly the code that runs.

## Documentation

| Document | Contents |
| --- | --- |
| [API.md](API.md) | Reference: every input and output, exit codes, report JSON, CLI, dispatcher, Python API |
| [docs/GUIDE.md](docs/GUIDE.md) | User guide: inputs, outputs, modes, dry runs, idempotency, security model, error reference, FAQ |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Development workflow, test layers, coverage gate, releases, offline and devcontainer setup |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Modules, the two backend seams, guarantees and where each one is enforced |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, daily loop, Git hooks, commit conventions, project layout |
| [AGENTS.md](AGENTS.md) | Rules for automated contributors |

## Development

```bash
pixi run setup      # locked environment, tool check, Git hooks
pixi run ci         # validate, lint, format, types, coverage (gate 90 %)
```

Prefer a container? [`.devcontainer/`](.devcontainer/devcontainer.json) provides Pixi, Python and the
extensions, and runs the same `pixi run setup` / `pixi run ci`.

## License

MIT
