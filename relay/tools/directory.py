"""Fake directory backed by world.db. Unknown users are typed failures, never invented."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from shared.schemas import Action


class DirectoryNotFound(LookupError):
    code = "DirectoryNotFound"


def seed_user(world_db: str | Path, username: str, groups: list[str] | tuple[str, ...] = ()) -> dict:
    if not username:
        raise ValueError("username must not be empty")
    import json

    ordered = sorted(set(groups))
    with closing(sqlite3.connect(world_db)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO users(username,groups_json) VALUES(?,?)",
            (username, json.dumps(ordered)),
        )
        conn.execute("DELETE FROM memberships WHERE username=?", (username,))
        conn.executemany(
            "INSERT INTO memberships(username,grp) VALUES(?,?)", [(username, grp) for grp in ordered]
        )
        conn.commit()
    return {"username": username, "groups": ordered}


def lookup_user(world_db: str | Path, username: str) -> dict:
    with closing(sqlite3.connect(world_db)) as conn:
        row = conn.execute("SELECT groups_json FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            raise DirectoryNotFound(f"unknown user {username!r}")
        groups = conn.execute(
            "SELECT grp FROM memberships WHERE username=? ORDER BY grp", (username,)
        ).fetchall()
    import json

    stored = json.loads(row[0])
    live = [item[0] for item in groups]
    # Membership table is authoritative; stored JSON is a cached projection.
    return {"username": username, "groups": live or stored}


def plan_add_member(username: str, group: str) -> Action:
    if not username or not group:
        raise ValueError("username and group must not be empty")
    return Action(operation="add_member", target=group, user=username)