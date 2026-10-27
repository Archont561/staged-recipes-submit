#!/usr/bin/env bash
# Provision the container after it is created.
#
# Runs once per new container (`postCreateCommand`), never on every start, and only through
# the same task dispatcher a human uses: no bespoke install logic lives here.
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

# `.pixi` is a named volume (see devcontainer.json). A fresh volume is owned by root, and the
# Pixi environment must not live on a case-insensitive bind mount, so claim it here.
mkdir -p .pixi
sudo chown "$(id -u):$(id -g)" .pixi

pixi --version
# Locked install of every environment, tool check, and the lefthook Git hooks.
pixi run --locked setup
pixi run --locked ci
