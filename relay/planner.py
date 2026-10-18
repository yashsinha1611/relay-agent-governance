"""Deterministic mock planner: parses documented ticket syntax into typed Plans."""

from __future__ import annotations

import re

from shared.schemas import Action, Plan, Subtask

BUCKET = r"[a-z0-9-]+-(?:dev|test|staging|prod)-(?:raw|curated|archive)"
# Content is a single token so multi-operation tickets parse deterministically.
UPLOAD_RE = re.compile(rf"upload\s+(?P<key>\S+)\s+to\s+(?P<bucket>{BUCKET})(?:\s+content\s+(?P<content>\S+))?", re.IGNORECASE)
DOWNLOAD_RE = re.compile(rf"download\s+(?P<key>\S+)\s+from\s+(?P<bucket>{BUCKET})", re.IGNORECASE)
DELETE_RE = re.compile(rf"delete\s+(?P<key>\S+)\s+from\s+(?P<bucket>{BUCKET})", re.IGNORECASE)
MEMBER_RE = re.compile(r"add\s+(?P<user>[a-zA-Z0-9_.-]+)\s+to\s+(?P<group>[a-zA-Z0-9_.-]+)", re.IGNORECASE)


def _env(bucket: str) -> str:
    return bucket.rsplit("-", 2)[-2]


def plan_ticket(ticket: str) -> Plan:
    """Parse supported ticket phrases. Unknown tickets yield an empty plan (failure downstream)."""
    tasks: list[Subtask] = []
    seq = 0

    def add(specialist: str, action: Action, depends: list[str] | None = None) -> str:
        nonlocal seq
        seq += 1
        tid = f"t{seq}"
        tasks.append(Subtask(id=tid, specialist=specialist, action=action, depends_on=depends or []))
        return tid

    last_storage: str | None = None
    for match in UPLOAD_RE.finditer(ticket or ""):
        bucket = match.group("bucket")
        tid = add("storage", Action(operation="upload", target=bucket, path=match.group("key"), content=(match.group("content") or "mock-content").strip(), environment=_env(bucket)), [last_storage] if last_storage else [])
        last_storage = tid
    for match in DOWNLOAD_RE.finditer(ticket or ""):
        bucket = match.group("bucket")
        tid = add("storage", Action(operation="download", target=bucket, path=match.group("key"), environment=_env(bucket)), [last_storage] if last_storage else [])
        last_storage = tid
    for match in DELETE_RE.finditer(ticket or ""):
        bucket = match.group("bucket")
        tid = add("storage", Action(operation="delete", target=bucket, path=match.group("key"), environment=_env(bucket)), [last_storage] if last_storage else [])
        last_storage = tid
    for match in MEMBER_RE.finditer(ticket or ""):
        add("directory", Action(operation="add_member", target=match.group("group"), user=match.group("user")))
    return Plan(subtasks=tasks)