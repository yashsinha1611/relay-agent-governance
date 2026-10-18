"""SQLite fake-world persistence. All mutations are explicit and transactional."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from shared.schemas import Action

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects(bucket TEXT NOT NULL, key TEXT NOT NULL, content TEXT NOT NULL, PRIMARY KEY(bucket, key));
CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, groups_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memberships(username TEXT NOT NULL, grp TEXT NOT NULL, PRIMARY KEY(username, grp));
"""

SEED_OBJECTS = [
    ("acme-dev-raw", "report.csv", "id,value\n1,alpha\n"),
    ("acme-dev-raw", "notes.txt", "seed notes"),
    ("acme-prod-curated", "report.csv", "id,value\n1,prod\n"),
]

SEED_USERS = {
    "alice": ["analysts"],
    "bob": ["admins", "analysts"],
}


def init_world(path: str | Path) -> Path:
    """Create tables and deterministic seed rows if they are absent. Returns path."""
    db = Path(path)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.executescript(SCHEMA)
        for bucket, key, content in SEED_OBJECTS:
            conn.execute(
                "INSERT OR IGNORE INTO objects(bucket,key,content) VALUES(?,?,?)",
                (bucket, key, content),
            )
        for username, groups in SEED_USERS.items():
            conn.execute(
                "INSERT OR IGNORE INTO users(username,groups_json) VALUES(?,?)",
                (username, json.dumps(sorted(groups))),
            )
            for grp in groups:
                conn.execute(
                    "INSERT OR IGNORE INTO memberships(username,grp) VALUES(?,?)",
                    (username, grp),
                )
        conn.commit()
    finally:
        conn.close()
    return db


def apply_action(world_db: str | Path, action: Action) -> dict:
    """Apply one approved action transactionally. Called only after policy approval."""
    db = Path(world_db)
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        if action.operation == "upload":
            conn.execute(
                "INSERT OR REPLACE INTO objects(bucket,key,content) VALUES(?,?,?)",
                (action.target, action.path, action.content),
            )
        elif action.operation == "delete":
            cursor = conn.execute(
                "DELETE FROM objects WHERE bucket=? AND key=?", (action.target, action.path)
            )
            if cursor.rowcount == 0:
                raise LookupError(f"missing object {action.target}/{action.path}")
        elif action.operation == "add_member":
            conn.execute(
                "INSERT OR IGNORE INTO users(username,groups_json) VALUES(?,?)",
                (action.user, "[]"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO memberships(username,grp) VALUES(?,?)",
                (action.user, action.target),
            )
            rows = conn.execute(
                "SELECT grp FROM memberships WHERE username=? ORDER BY grp", (action.user,)
            ).fetchall()
            conn.execute(
                "UPDATE users SET groups_json=? WHERE username=?",
                (json.dumps([row[0] for row in rows]), action.user),
            )
        elif action.operation == "download":
            row = conn.execute(
                "SELECT content FROM objects WHERE bucket=? AND key=?",
                (action.target, action.path),
            ).fetchone()
            if row is None:
                raise LookupError(f"missing object {action.target}/{action.path}")
        else:  # pragma: no cover - schema validation forbids this
            raise ValueError(f"unsupported operation {action.operation}")
        conn.commit()
    except BaseException:
        try:
            conn.rollback()
        finally:
            conn.close()
        raise
    else:
        conn.close()
    return {"operation": action.operation, "target": action.target, "path": action.path}


def hash_world(world_db: str | Path) -> str:
    """Stable hash of persisted world rows, used to prove blocked runs changed nothing."""
    conn = sqlite3.connect(world_db)
    try:
        objects = conn.execute("SELECT bucket,key,content FROM objects ORDER BY bucket,key").fetchall()
        memberships = conn.execute("SELECT username,grp FROM memberships ORDER BY username,grp").fetchall()
    finally:
        conn.close()
    digest = hashlib.sha256(repr((objects, memberships)).encode())
    return digest.hexdigest()