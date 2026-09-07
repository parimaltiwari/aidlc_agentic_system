FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY aidlc ./aidlc

RUN uv sync --frozen --no-dev

ENTRYPOINT ["uv", "run", "--no-sync", "aidlc"]
