# Prebaked NCS toolchain image for the firmware CI matrix.
#
# Mirrors a local install: nrfutil sdk-manager owns the toolchain and
# SDK. Baking it here replaces multi-GB per-run installs with an image
# pull, is branch-agnostic, and freezes the env immutably. Rebuild +
# push when NCS_VERSION bumps (docker/justfile or the docker-image
# workflow).
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

# Toolchain via sdk-manager (mirrors local); SDK workspace via
# shallow west clones — full git history is dead weight, but the
# .git dirs themselves are load-bearing: NCS's manifest imports
# zephyr's west.yml at a git revision, so depth-1 is the floor.
# Cleanup in the same layer (layers are additive).
RUN nrfutil sdk-manager toolchain install --ncs-version ${NCS_VERSION} \
    && rm -rf /root/ncs/downloads /root/ncs/tmp
RUN nrfutil sdk-manager toolchain launch --ncs-version ${NCS_VERSION} -- \
      west init -m https://github.com/nrfconnect/sdk-nrf --mr ${NCS_VERSION} /root/ncs/${NCS_VERSION} \
    && cd /root/ncs/${NCS_VERSION} \
    && nrfutil sdk-manager toolchain launch --ncs-version ${NCS_VERSION} -- \
      west update --narrow -o=--depth=1

ENV NCS_VERSION=${NCS_VERSION}
ENV NCS_ROOT=/root/ncs/${NCS_VERSION}
ENV ZEPHYR_BASE=${NCS_ROOT}/zephyr

# Entrypoint launches through the toolchain env (ZEPHYR_BASE, PATH).
# No args: interactive shell; with args: run the command.
# Note: GitHub Actions `container:` jobs bypass the entrypoint (steps
# use docker exec) — CI scripts keep the explicit launch prefix.
RUN cat <<'EOF' > /usr/local/bin/ncs-entrypoint && chmod +x /usr/local/bin/ncs-entrypoint
#!/bin/bash
if [ $# -eq 0 ]; then
    exec nrfutil sdk-manager toolchain launch --ncs-version ${NCS_VERSION} --shell
else
    exec nrfutil sdk-manager toolchain launch --ncs-version ${NCS_VERSION} -- "$@"
fi
EOF

# The image proves itself at build time.
RUN nrfutil sdk-manager toolchain launch --ncs-version ${NCS_VERSION} -- west --version

WORKDIR ${NCS_ROOT}
ENTRYPOINT ["/usr/local/bin/ncs-entrypoint"]
