# syntax=docker/dockerfile:1

# --- Build stage ---
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN uv sync --no-dev

# --- Runtime stage ---
FROM python:3.13-slim

WORKDIR /app

# Copy everything from builder (venv, source, and package metadata)
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "-m", "sdlc_assist_mcp.server", "--transport", "streamable-http"]