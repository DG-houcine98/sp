# jenkins/jenkins:lts only has Java + Jenkins itself - none of the CLI tools
# the pipeline's `sh` steps shell out to (docker, aws, python3, git, zip, jq,
# shellcheck, curl). This layer installs them so the pipeline can actually
# run against this image, rather than failing on the first shell step.
FROM jenkins/jenkins:lts

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        git zip unzip jq curl shellcheck \
        docker.io \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# AWS CLI v2 (the Debian package only ships v1, which lacks some commands
# this project's scripts rely on). AWS ships separate x86_64/aarch64 builds -
# hardcoding x86_64 silently "works" via QEMU emulation on an arm64 host (like
# Apple Silicon via Colima) right up until some transitive piece of it needs a
# library QEMU's user-mode emulation doesn't have, e.g. the x86_64 dynamic
# linker itself. Detecting the real arch avoids emulation entirely.
RUN ARCH="$(uname -m)" \
    && curl -s "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/awscliv2.zip /tmp/aws

# checkov depends on rustworkx (PyO3/Rust bindings), which has no prebuilt wheel
# for this image's Python version on arm64 - pip falls back to building from
# source, which needs an actual Rust toolchain. Installed system-wide (not under
# a user home) so it's usable by both root (this build) and the jenkins user.
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal \
    && chmod -R a+rwX /usr/local/rustup /usr/local/cargo

USER jenkins
