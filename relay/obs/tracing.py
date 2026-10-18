"""SQLite + JSONL trace persistence for Relay runs."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS traces(trace_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, status TEXT NOT NULL, started REAL NOT NULL, ended REAL NOT NULL, approvals_json TEXT NOT NULL, trajectory_json TEXT NOT NULL, nodes_json TEXT NOT NULL, errors_json TEXT NOT NULL);
"""


def init_traces(path: str | Path) -> Path:
    db = Path(path)
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    return db


def record_trace(db: str | Path, thread_id: str, status: str, nodes: list[dict], trajectory: list[dict], approvals: list[dict], errors: list[dict] | None = None) -> str:
    db = init_traces(db)
    trace_id = uuid.uuid4().hex[:12]
    now = time.time()
    started = min([n.get("started", now) for n in nodes], default=now)
    payload = {
        "trace_id": trace_id, "thread_id": thread_id, "status": status,
        "started": started, "ended": now,
        "approvals_json": json.dumps(approvals, sort_keys=True, default=str),
        "trajectory_json": json.dumps(trajectory, sort_keys=True, default=str),
        "nodes_json": json.dumps(nodes, sort_keys=True, default=str),
        "errors_json": json.dumps(errors or [], sort_keys=True, default=str),
    }
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(
            "INSERT INTO traces(trace_id,thread_id,status,started,ended,approvals_json,trajectory_json,nodes_json,errors_json) VALUES(:trace_id,:thread_id,:status,:started,:ended,:approvals_json,:trajectory_json,:nodes_json,:errors_json)",
            payload,
        )
        conn.commit()
    # JSONL mirror for human inspection; never includes secrets (callers pass only typed data).
    jsonl = Path(str(db) + ".jsonl")
    with open(jsonl, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"trace_id": trace_id, "thread_id": thread_id, "status": status, "nodes": nodes}, sort_keys=True, default=str) + "\n")
    return trace_id


def get_trace(db: str | Path, trace_id: str) -> dict | None:
    with closing(sqlite3.connect(db)) as conn:
        try:
            row = conn.execute("SELECT trace_id,thread_id,status,started,ended,approvals_json,trajectory_json,nodes_json,errors_json FROM traces WHERE trace_id=?", (trace_id,)).fetchone()
        except sqlite3.OperationalError:
            return None
    if row is None:
        return None
    return {"trace_id": row[0], "thread_id": row[1], "status": row[2], "started": row[3], "ended": row[4],
            "approvals": json.loads(row[5]), "trajectory": json.loads(row[6]), "nodes": json.loads(row[7]), "errors": json.loads(row[8])}


def list_traces(db: str | Path, thread_id: str | None = None) -> list[dict]:
    with closing(sqlite3.connect(db)) as conn:
        try:
            if thread_id:
                rows = conn.execute("SELECT trace_id,thread_id,status,started,ended FROM traces WHERE thread_id=? ORDER BY started", (thread_id,)).fetchall()
            else:
                rows = conn.execute("SELECT trace_id,thread_id,status,started,ended FROM traces ORDER BY started").fetchall()
        except sqlite3.OperationalError:
            return []
    return [{"trace_id": r[0], "thread_id": r[1], "status": r[2], "started": r[3], "ended": r[4]} for r in rows]