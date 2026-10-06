"""Export actual FastAPI contracts for the generated TypeScript client models."""

import json
from pathlib import Path

from app.main import create_app


def main() -> None:
    destination = Path(__file__).resolve().parents[1] / "frontend/openapi.json"
    destination.write_text(json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
