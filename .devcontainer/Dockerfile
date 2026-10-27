# Development container for staged-recipes-submit.
#
# Base image pinned by digest: the tag is for humans, the digest is what actually runs.
# Refresh the digest deliberately (docker buildx imagetools inspect <tag>) and record the
# new one here, the same way config/actions.lock.json pins workflow actions.
ARG BASE=mcr.microsoft.com/devcontainers/base:bookworm@sha256:9a5942e64b35c5497c591b9bf177f4a3002d43440bf0a5e1a14fc34667b1a5c1
FROM ${BASE}

# The Pixi release line is pinned in one place: pixi.toml's `requires-pixi`, the workflows'
# setup-pixi inputs and pixi-sandbox.toml's [workflow].pixi_version. Keep this ARG equal to
# them; `pixi run validate` refuses a devcontainer that drifts.
ARG PIXI_VERSION=v0.83.0

USER root
# Download the release tarball, verify it against the published .sha256 sidecar, then install
# only the binary. Nothing is piped from the network into a shell.
RUN set -eu; \
    arch="$(uname -m)"; \
    asset="pixi-${arch}-unknown-linux-musl.tar.gz"; \
    base="https://github.com/prefix-dev/pixi/releases/download/${PIXI_VERSION}"; \
    curl -fsSL --retry 3 --retry-delay 2 -o "/tmp/${asset}" "${base}/${asset}"; \
    curl -fsSL --retry 3 --retry-delay 2 -o "/tmp/${asset}.sha256" "${base}/${asset}.sha256"; \
    cd /tmp; \
    sha256sum -c "${asset}.sha256"; \
    mkdir -p /tmp/pixi-extract; \
    tar -xzf "/tmp/${asset}" -C /tmp/pixi-extract; \
    install -m 0755 "$(find /tmp/pixi-extract -maxdepth 2 -name pixi -type f | head -n 1)" /usr/local/bin/pixi; \
    rm -rf "/tmp/${asset}" "/tmp/${asset}.sha256" /tmp/pixi-extract; \
    pixi --version

USER vscode
WORKDIR /home/vscode
# Shell completion for the Pixi commands the task dispatcher exposes.
RUN echo 'eval "$(pixi completion -s bash)"' >> /home/vscode/.bashrc

WORKDIR /workspaces/staged-recipes-submit
