FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    APP_DATABASE_PATH=/app/data/amazon_competitor.sqlite3 \
    APP_BROWSER_BINARY=/usr/bin/chromium

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
RUN apt-get update && apt-get install -y --no-install-recommends chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.21

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY scripts ./scripts
COPY migrations ./migrations
COPY main.py ./
RUN uv sync --locked --no-dev
RUN mkdir -p /app/data /app/artifacts && chown -R app:app /app

USER app
EXPOSE 8501
CMD ["uv", "run", "--no-sync", "streamlit", "run", "main.py", "--server.address=0.0.0.0", "--server.port=8501"]
