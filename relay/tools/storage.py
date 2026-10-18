"""Typed storage tools. Reads come from world.db; writes are planned, then applied post-approval."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path

from shared.schemas import Action

BUCKET_RE = re.compile(r"^(?P<project>[a-z0-9-]+)-(?P<env>dev|test|staging|prod)-(?P<zone>raw|curated|archive)$")
ENVIRONMENTS = ("dev", "test", "staging", "prod")
ZONES = ("raw", "curated", "archive")


class StorageError(ValueError):
    code = "StorageError"


class InvalidName(StorageError):
    code = "InvalidName"


class NotFound(StorageError):
    code = "NotFound"


def parse_bucket(name: str) -> dict[str, str]:
    """Validate grammar <project>-<env>-<zone> and return its components."""
    match = BUCKET_RE.match(name or "")
    if not match:
        raise InvalidName(f"invalid bucket name: {name!r}")
    return match.groupdict()


def environment_of(bucket: str) -> str:
    return parse_bucket(bucket)["env"]


def zone_of(bucket: str) -> str:
    return parse_bucket(bucket)["zone"]


def list_objects(world_db: str | Path, bucket: str) -> list[str]:
    parse_bucket(bucket)
    with closing(sqlite3.connect(world_db)) as conn:
        rows = conn.execute("SELECT key FROM objects WHERE bucket=? ORDER BY key", (bucket,)).fetchall()
    return [row[0] for row in rows]


def read_object(world_db: str | Path, bucket: str, key: str) -> str:
    parse_bucket(bucket)
    if not key:
        raise StorageError("object key must not be empty")
    with closing(sqlite3.connect(world_db)) as conn:
        row = conn.execute(
            "SELECT content FROM objects WHERE bucket=? AND key=?", (bucket, key)
        ).fetchone()
    if row is None:
        raise NotFound(f"missing object {bucket}/{key}")
    return row[0]


def _target_env(bucket: str) -> str:
    return environment_of(bucket)


def plan_upload(bucket: str, key: str, content: str) -> Action:
    parse_bucket(bucket)
    if not key:
        raise StorageError("upload key must not be empty")
    return Action(operation="upload", target=bucket, path=key, content=content, environment=_target_env(bucket))


def plan_download(bucket: str, key: str) -> Action:
    parse_bucket(bucket)
    if not key:
        raise StorageError("download key must not be empty")
    return Action(operation="download", target=bucket, path=key, environment=_target_env(bucket))


def plan_delete(bucket: str, key: str) -> Action:
    parse_bucket(bucket)
    if not key:
        raise StorageError("delete key must not be empty")
    return Action(operation="delete", target=bucket, path=key, environment=_target_env(bucket))