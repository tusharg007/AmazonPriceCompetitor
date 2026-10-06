FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy \
    PYTHONPATH=/app/backend PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    APP_EVIDENCE_DIR=/app/runtime/evidence APP_ENV=production
RUN pip install --no-cache-dir uv==0.12.21
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project \
    && .venv/bin/python -m playwright install --with-deps chromium \
    && chmod -R a+rX /opt/playwright
COPY backend ./backend
COPY README.md ./
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p /app/runtime/evidence && chown -R app:app /app/runtime
USER app
EXPOSE 8000
CMD [".venv/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
