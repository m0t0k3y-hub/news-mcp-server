# --- Build stage: resolve and install production dependencies with uv ---
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv

# Compile bytecode for faster startup, copy (not link) files out of the uv cache,
# and use the image's Python rather than downloading one.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first so this layer is cached until pyproject.toml / uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable


# --- Runtime stage: only the virtual environment, run as non-root ---
FROM python:3.12-slim

RUN groupadd --system appuser \
    && useradd --system --gid appuser --no-create-home --shell /usr/sbin/nologin appuser

# Owned by root so the app user cannot modify installed code.
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

USER appuser
WORKDIR /app

# Documentation only: Render and Cloud Run inject PORT, which the server reads at startup.
EXPOSE 8000

CMD ["python", "-m", "news_mcp_server"]
