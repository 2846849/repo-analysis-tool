"""SQLite persistence for repositories and manual author merges.

Uses only the Python standard library so the backend has a single runtime
dependency (FastAPI) and the database file lives inside ``backend/storage``.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BACKEND_DIR / "storage"
REPOS_DIR = STORAGE_DIR / "repos"
DB_PATH = STORAGE_DIR / "rat.db"


def _connect() -> sqlite3.Connection:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS repositories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source TEXT NOT NULL,
                path TEXT NOT NULL,
                mailmap_text TEXT,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS author_merges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id INTEGER NOT NULL
                    REFERENCES repositories(id) ON DELETE CASCADE,
                alias_name TEXT NOT NULL,
                alias_email TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                canonical_email TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def add_repository(name: str, source_type: str, source: str, path: str,
                   mailmap_text: str | None = None) -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO repositories (name, source_type, source, path, mailmap_text, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (name, source_type, source, path, mailmap_text, time.time()),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def set_repository_path(repo_id: int, path: str) -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE repositories SET path = ? WHERE id = ?", (path, repo_id))
        conn.commit()
    finally:
        conn.close()


def set_mailmap(repo_id: int, text: str | None) -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE repositories SET mailmap_text = ? WHERE id = ?",
                     (text, repo_id))
        conn.commit()
    finally:
        conn.close()


def _row_to_repo(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "source_type": row["source_type"],
        "source": row["source"],
        "path": row["path"],
        "mailmap_text": row["mailmap_text"],
        "created_at": row["created_at"],
    }


def get_repository(repo_id: int) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM repositories WHERE id = ?",
                           (repo_id,)).fetchone()
        return _row_to_repo(row) if row else None
    finally:
        conn.close()


def list_repositories() -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM repositories ORDER BY id").fetchall()
        return [_row_to_repo(row) for row in rows]
    finally:
        conn.close()


def delete_repository(repo_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
        conn.commit()
    finally:
        conn.close()


def get_merges(repo_id: int) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT alias_name, alias_email, canonical_name, canonical_email"
            " FROM author_merges WHERE repo_id = ? ORDER BY id",
            (repo_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def replace_merges(repo_id: int, merges: list[dict]) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM author_merges WHERE repo_id = ?", (repo_id,))
        conn.executemany(
            "INSERT INTO author_merges (repo_id, alias_name, alias_email,"
            " canonical_name, canonical_email) VALUES (?, ?, ?, ?, ?)",
            [
                (repo_id, m["alias_name"].strip(), m["alias_email"].strip(),
                 m["canonical_name"].strip(), m["canonical_email"].strip())
                for m in merges
            ],
        )
        conn.commit()
    finally:
        conn.close()


def clear_merges(repo_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM author_merges WHERE repo_id = ?", (repo_id,))
        conn.commit()
    finally:
        conn.close()
