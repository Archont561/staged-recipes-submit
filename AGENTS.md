# Agent and automation guide

This repository is developed with human review plus automated agents. The rules that matter:

1. **One dispatcher.** Every development action is a task in `pixi.toml` that calls
   `python scripts/run.py <command>`. CI refuses workflow steps that chain shell commands.
2. **Tests before claims.** `pixi run ci` must pass before you describe work as done. Quote the real
   numbers.
3. **No live GitHub in the default suite.** Live tests are marked `live`, read-only, and require
   `--run-live` plus `GITHUB_TOKEN`.
4. **Conventional commits**, enforced by the `commit-msg` hook and by the `policy` CI job.
5. **Never weaken a gate silently.** The coverage floor, the pinned-action policy and the
   single-task CI rule are all checked by `validate`; changing them is a deliberate commit.
6. **Secrets stay in the environment.** Inputs arrive as environment variables, tokens are wrapped
   in `Secret`, and `Secret.__repr__` is always redacted.
7. **`API.md` is the contract.** Every input and output in `action.yml` must appear in `API.md`;
   `pixi run validate` fails otherwise. Change the two together, never one alone.
8. **Nothing is published.** There is no wheel, no release asset and no PyPI project. The action runs
   `scripts/` from the checkout; do not add a build or publish step without changing
   `config/project.toml` and the action contract in `scripts/quality.py` in the same commit.
