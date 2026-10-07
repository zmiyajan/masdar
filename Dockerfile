# syntax=docker/dockerfile:1
# Masdar web app and API for Hugging Face Spaces (Docker SDK).
# Build: docker build -t masdar .   Run: docker run --rm -p 7860:7860 masdar

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# ---------------------------------------------------------------- builder
FROM ${PYTHON_IMAGE} AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first, in their own layer: code changes do not reinstall torch.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ml --no-install-project

COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ml

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime

# Hugging Face Spaces runs containers as UID 1000; owning the files as that
# user also keeps the image working on any host that enforces non-root.
RUN useradd --create-home --uid 1000 user

ENV HOME=/home/user \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/home/user/.cache/huggingface

WORKDIR /app

# Same path as in the builder: the editable install points at /app/src.
COPY --from=builder --chown=user:user /app/.venv /app/.venv
COPY --chown=user:user src/ ./src/
COPY --chown=user:user data/sources/ ./data/sources/
COPY --chown=user:user data/gold/ ./data/gold/
COPY --chown=user:user data/dataset/stats.json data/dataset/DATASET_CARD.md ./data/dataset/
RUN mkdir -p /app/data/index "$HF_HOME" && chown -R user:user /app/data/index /home/user/.cache

USER user

# Warm-up: download model weights and build any on-disk index now, as the
# runtime user, so they ship inside the image and the first visitor does not
# wait. "|| true" keeps an offline or model-less build usable: the app then
# warms up on first start instead.
RUN python -m masdar.entrypoints.warmup || true

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/health', timeout=4)"]

# --proxy-headers: Spaces sits behind a proxy, and the rate limit keys on the
# client address from X-Forwarded-For. One worker: the limiter is in-memory.
CMD ["uvicorn", "masdar.entrypoints.api:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "7860", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--workers", "1"]
