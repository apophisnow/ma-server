FROM mcr.microsoft.com/vscode/devcontainers/python:3.13

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    git curl build-essential ca-certificates gnupg lsb-release \
    pkg-config libssl-dev libffi-dev libsndfile1 ffmpeg \
 && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

RUN python -m pip install --upgrade pip setuptools wheel

WORKDIR /workspace/ma-server

CMD ["/bin/bash"]
