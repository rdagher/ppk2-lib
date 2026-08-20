# Prebaked NCS toolchain image for the firmware CI matrix.
#
# Same flow as a local install: nrfutil sdk-manager owns the toolchain
# and SDK. Baking it here replaces a multi-GB CI cache restore with an
# image pull, is branch-agnostic, and freezes the env immutably.
# Rebuild + push when NCS_VERSION bumps (docker/justfile or the
# docker-image workflow).

FROM ubuntu:24.04

ARG NCS_VERSION=v3.3.1

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /usr/local/bin/nrfutil \
      https://files.nordicsemi.com/artifactory/swtools/external/nrfutil/executables/x86_64-unknown-linux-gnu/nrfutil \
    && chmod +x /usr/local/bin/nrfutil \
    && nrfutil install sdk-manager

RUN nrfutil sdk-manager install ${NCS_VERSION} \
    && rm -rf /root/ncs/downloads /root/ncs/tmp

ENV NCS_VERSION=${NCS_VERSION}
WORKDIR /root/ncs
