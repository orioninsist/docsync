FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/tmp/uv-cache

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

COPY pyproject.toml uv.lock README.md .python-version ./
COPY src ./src
COPY typescript/package.json typescript/package-lock.json ./typescript/

RUN uv sync --locked --all-groups
RUN cd typescript && npm ci && npx playwright install chromium

COPY typescript ./typescript
COPY tests ./tests

WORKDIR /workspace

ENTRYPOINT ["/app/.venv/bin/docsync"]
CMD ["--help"]
