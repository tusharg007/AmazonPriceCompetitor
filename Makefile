.PHONY: dev stop migrate test lint
dev:
	docker compose up --build
stop:
	docker compose down
migrate:
	uv run alembic -c backend/alembic.ini upgrade head
test:
	uv run pytest -q --cov=backend/app
	cd frontend && npm test
lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src main.py backend/app backend/alembic
	cd frontend && npm run lint && npm run typecheck && npm run format:check
