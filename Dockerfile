# ---------- Base Stage ----------
FROM python:3.12.7 AS base

# Environment variables
ENV POETRY_VERSION=2.1.1
ENV POETRY_HOME=/opt/poetry
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
ENV PATH=/usr/local/go/bin:${POETRY_HOME}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ENV JUPYTER_SESSIONS_DIR=/mnt/jupyter_sessions

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        python3-pip \
        git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Symlink python for Poetry - not needed for python:3.12.7 image
# RUN ln -s /usr/bin/python3.12 /usr/local/bin/python

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3.12 -

# Set up common directories
RUN mkdir -p /mnt/data /mnt/jupyter_sessions /workspace

# Set common working directory
WORKDIR /workspaces

# Copy only Poetry config files (to cache dependency installation)
COPY pyproject.toml poetry.lock ./

# ---------- Production Stage ----------
FROM base AS prod

# Install dependencies
RUN poetry install --no-root --only main

# Copy the rest of the code
COPY . .

# Set production startup command
CMD ["poetry", "run", "python", "-m", "math_rag_jupyter.main"]

# ---------- Development Stage ----------
FROM base AS dev

COPY . .
