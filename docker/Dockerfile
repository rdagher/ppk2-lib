# Prebaked NCS toolchain + SDK image for the firmware CI matrix.
#
# Mirrors a local install: nrfutil sdk-manager owns both. Baking them
# into an image turns multi-GB per-run installs into one pull and
# freezes the build env. Rebuild + push on an NCS_VERSION bump
# (docker/justfile locally, or the docker-image workflow).
#
# Build args:
#   UBUNTU_VERSION: base image (default 24.04)
#   NCS_VERSION:    nRF Connect SDK version (default v3.3.1)

ARG UBUNTU_VERSION=24.04

FROM ubuntu:${UBUNTU_VERSION}

ARG NCS_VERSION=v3.3.1

# Minimal host deps (the toolchain bundle carries its own git, cmake,
# python, compilers).
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends curl ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /usr/local/bin/nrfutil \
      https://developer.nordicsemi.com/.pc-tools/nrfutil/x64-linux/nrfutil \
    && chmod +x /usr/local/bin/nrfutil \
    && nrfutil self-upgrade \
    && nrfutil install sdk-manager

# `sdk install` ships a ready west workspace (.west/ + zephyr/nrf/
# modules) — no west init/update needed, at build time or in CI.
# Cleanup must stay in the same layer (layers are additive).
RUN nrfutil sdk-manager toolchain install --ncs-version ${NCS_VERSION} \
    && rm -rf /root/ncs/downloads /root/ncs/tmp
RUN nrfutil sdk-manager sdk install ${NCS_VERSION} \
    && nrfutil sdk-manager sdk register ${NCS_VERSION} \
    && rm -rf /root/ncs/downloads /root/ncs/tmp

ENV NCS_VERSION=${NCS_VERSION}
ENV NCS_ROOT=/root/ncs/${NCS_VERSION}
ENV ZEPHYR_BASE=${NCS_ROOT}/zephyr

# CI runners override HOME, but nrfutil resolves its subcommands from
# $HOME/.nrfutil and sdk-manager defaults its install dir to
# $HOME/ncs. Pin both so the image works under any HOME.
ENV NRFUTIL_HOME=/root/.nrfutil
RUN nrfutil sdk-manager config install-dir set /root/ncs

# Entrypoint runs everything through the toolchain env (ZEPHYR_BASE,
# PATH). No args: interactive shell; with args: run the command.
# CI `container:` jobs bypass entrypoints (docker exec), so CI
# scripts keep the explicit launch prefix.
RUN cat <<'EOF' > /usr/local/bin/ncs-entrypoint && chmod +x /usr/local/bin/ncs-entrypoint
#!/bin/bash
if [ $# -eq 0 ]; then
    exec nrfutil sdk-manager toolchain launch --ncs-version ${NCS_VERSION} --shell
else
    exec nrfutil sdk-manager toolchain launch --ncs-version ${NCS_VERSION} -- "$@"
fi
EOF

# Build-time self-check, under a foreign HOME as CI runners set.
RUN HOME=/tmp/ci-home nrfutil sdk-manager toolchain launch --ncs-version ${NCS_VERSION} -- west --version

# Shown on the ghcr package page ("About") and in the packages list.
LABEL org.opencontainers.image.source="https://github.com/rdagher/ppk2-lib" \
      org.opencontainers.image.description="Prebaked nRF Connect SDK ${NCS_VERSION} toolchain + workspace for the ppk2-lib firmware CI matrix"

WORKDIR ${NCS_ROOT}
ENTRYPOINT ["/usr/local/bin/ncs-entrypoint"]
