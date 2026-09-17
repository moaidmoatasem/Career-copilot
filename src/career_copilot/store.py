"""Local SQLite storage. Everything stays on this machine."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .util import utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    score INTEGER,
    tier TEXT,
    confidence TEXT,
    analysis_json TEXT NOT NULL DEFAULT '{}',
    notes TEXT NOT NULL DEFAULT '',
    flags_json TEXT NOT NULL DEFAULT '[]',
    first_seen TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_tier ON jobs(tier, score DESC);

CREATE TABLE IF NOT EXISTS inbox_items (
    id INTEGER PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    sender TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    preview TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    priority TEXT NOT NULL DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'new',
    flags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    feed TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    published TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0,
    matched_json TEXT NOT NULL DEFAULT '[]',
    flags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY,
    skill TEXT NOT NULL,
    title TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned',
    progress_pct INTEGER NOT NULL DEFAULT 0,
    target_date TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS connections (
    id INTEGER PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    company_key TEXT NOT NULL DEFAULT '',
    position TEXT NOT NULL DEFAULT '',
    profile_url TEXT NOT NULL DEFAULT '',
    connected_on TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS profile_snapshot (
    section TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    target_ref TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    original_content TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    char_limit INTEGER,
    checks_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewer_note TEXT NOT NULL DEFAULT '',
    approved_hash TEXT,
    executed_at TEXT,
    execution_note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    object_ref TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _restrict(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:  # e.g. Windows or unusual filesystems
        pass


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        _restrict(path.parent, 0o700)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        _restrict(path, 0o600)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self.transaction() as conn:
            return conn.execute(sql, params)

    def query(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: tuple | list = ()) -> Any:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return row[0] if row else None

    def audit(
        self,
        actor: str,
        action: str,
        object_ref: str = "",
        details: dict[str, Any] | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        params = (utcnow(), actor, action, object_ref, json.dumps(details or {}, ensure_ascii=False))
        sql = "INSERT INTO audit_log(ts, actor, action, object_ref, details_json) VALUES (?,?,?,?,?)"
        if conn is not None:
            conn.execute(sql, params)
        else:
            self.execute(sql, params)

    def get_meta(self, key: str) -> str | None:
        return self.scalar("SELECT value FROM meta WHERE key = ?", (key,))

    def set_meta(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
