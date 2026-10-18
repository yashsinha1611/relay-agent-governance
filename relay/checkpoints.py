"""SQLite checkpoint history and invocation counters (LangGraph-independent persistence)."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots(thread_id TEXT NOT NULL, step INTEGER NOT NULL, node TEXT NOT NULL, state_json TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(thread_id, step));
CREATE TABLE IF NOT EXISTS invocations(thread_id TEXT NOT NULL, node TEXT NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(thread_id, node));
"""


def init_checkpoints(path: str | Path) -> Path:
    db = Path(path)
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    return db


def _jsonable(state: dict) -> dict:
    from pydantic import BaseModel

    out: dict = {}
    for key, value in state.items():
        if key.startswith("_"):
            continue
        if isinstance(value, BaseModel):
            out[key] = value.model_dump(mode="json")
        else:
            out[key] = json.loads(json.dumps(value, default=str))
    return out


def save_snapshot(db: str | Path, thread_id: str, step: int, node: str, state: dict) -> None:
    db = init_checkpoints(db)
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO snapshots(thread_id,step,node,state_json,created) VALUES(?,?,?,?,?)",
            (thread_id, step, node, json.dumps(_jsonable(state), sort_keys=True, default=str), time.time()),
        )
        conn.commit()


def load_history(db: str | Path, thread_id: str) -> list[dict]:
    with closing(sqlite3.connect(db)) as conn:
        try:
            rows = conn.execute("SELECT step,node,state_json,created FROM snapshots WHERE thread_id=? ORDER BY step", (thread_id,)).fetchall()
        except sqlite3.OperationalError:
            return []
    return [{"step": r[0], "node": r[1], "state": json.loads(r[2]), "created": r[3]} for r in rows]


def load_latest(db: str | Path, thread_id: str) -> dict | None:
    history = load_history(db, thread_id)
    return history[-1] if history else None


def record_invocation(db: str | Path, thread_id: str, node: str) -> int:
    db = init_checkpoints(db)
    with closing(sqlite3.connect(db)) as conn:
        row = conn.execute("SELECT count FROM invocations WHERE thread_id=? AND node=?", (thread_id, node)).fetchone()
        count = (row[0] if row else 0) + 1
        conn.execute("INSERT OR REPLACE INTO invocations(thread_id,node,count) VALUES(?,?,?)", (thread_id, node, count))
        conn.commit()
    return count


def invocation_counts(db: str | Path, thread_id: str) -> dict[str, int]:
    with closing(sqlite3.connect(db)) as conn:
        try:
            rows = conn.execute("SELECT node,count FROM invocations WHERE thread_id=?", (thread_id,)).fetchall()
        except sqlite3.OperationalError:
            return {}
    return {node: count for node, count in rows}