"""Persistent per-server UTC budget and nonblocking cross-process execution lock.

All workers must share this directory. Deploy one replica with a persistent volume;
independent replicas or ephemeral disks cannot provide a global daily budget.
"""
from __future__ import annotations

import fcntl
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class RunStore:
    def __init__(self, directory: Path, daily_limit: int = 20, *, clock=None):
        if daily_limit < 0:
            raise ValueError("daily_limit must be nonnegative")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "runs.sqlite3"
        self.daily_limit = daily_limit
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS budget (day TEXT PRIMARY KEY, used INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS results (
                    dataset TEXT NOT NULL, profile TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (dataset, profile)
                );
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @contextmanager
    def reserve(self):
        """Count attempts before providers run, including failed calls; never queue runs."""
        with (self.directory / "run.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield "busy"
                return
            try:
                day = self.clock().astimezone(timezone.utc).date().isoformat()
                with self.connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute("SELECT used FROM budget WHERE day=?", (day,)).fetchone()
                    used = row[0] if row else 0
                    if used >= self.daily_limit:
                        status = "limit"
                    else:
                        conn.execute("INSERT INTO budget VALUES (?, 1) ON CONFLICT(day) "
                                     "DO UPDATE SET used=used+1", (day,))
                        status = "allowed"
                yield status
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def get(self, dataset: str, profile: str):
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM results WHERE dataset=? AND profile=?",
                               (dataset, profile)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, dataset: str, profile: str, snapshot: dict):
        with self.connect() as conn:
            conn.execute("INSERT INTO results VALUES (?, ?, ?) ON CONFLICT(dataset, profile) "
                         "DO UPDATE SET payload=excluded.payload",
                         (dataset, profile, json.dumps(snapshot)))

    def latest(self, dataset: str):
        with self.connect() as conn:
            rows = conn.execute("SELECT payload FROM results WHERE dataset=?", (dataset,)).fetchall()
        snapshots = [json.loads(row[0]) for row in rows]
        return max(snapshots, key=lambda s: s["created_at"]) if snapshots else None
