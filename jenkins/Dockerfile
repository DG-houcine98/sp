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
    && rm -rf /var/lib/apt/lists/*

# AWS CLI v2 (the Debian package only ships v1, which lacks some commands
# this project's scripts rely on).
RUN curl -s "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/awscliv2.zip /tmp/aws

USER jenkins
