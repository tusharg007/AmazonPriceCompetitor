"""SQLite administration: migrate, health, backup, and restore verification."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from src.db import SQLiteRepository


def backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_conn, sqlite3.connect(destination) as destination_conn:
        source_conn.backup(destination_conn)


def verify(path: Path) -> dict[str, str]:
    with sqlite3.connect(path) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        migrations = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    return {
        "path": str(path),
        "integrity_check": integrity,
        "foreign_key_violations": str(len(foreign_keys)),
        "migrations": str(migrations),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("migrate")
    subcommands.add_parser("health")
    backup_command = subcommands.add_parser("backup")
    backup_command.add_argument("--destination", type=Path, required=True)
    restore_command = subcommands.add_parser("restore-verify")
    restore_command.add_argument("--source", type=Path, required=True)
    restore_command.add_argument("--destination", type=Path, required=True)
    arguments = parser.parse_args()
    repo = SQLiteRepository()
    if arguments.command == "migrate":
        repo.migrate()
        print("Migrations applied")
    elif arguments.command == "health":
        print(repo.health())
    elif arguments.command == "backup":
        repo.migrate()
        backup(repo.path, arguments.destination)
        print(verify(arguments.destination))
    else:
        backup(arguments.source, arguments.destination)
        print(verify(arguments.destination))


if __name__ == "__main__":
    main()
