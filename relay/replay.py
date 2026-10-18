"""Persisted replay/fork helpers over SQLite checkpoint history."""

from __future__ import annotations

from relay import checkpoints
from relay.core import RelayRunner


def history(checkpoint_db: str, thread_id: str) -> list[dict]:
    return checkpoints.load_history(checkpoint_db, thread_id)


def fork(runner: RelayRunner, thread_id: str, from_step: int, overrides: dict | None = None) -> dict:
    """Fork at step N via the runner; prefix invocations stay stable."""
    return runner.replay(thread_id, from_step, overrides)


def diff_prefix(history_rows: list[dict], from_step: int) -> dict:
    prefix = [h for h in history_rows if h["step"] < from_step]
    at = next((h for h in history_rows if h["step"] >= from_step), None)
    if at is None or at["step"] != from_step:
        raise KeyError(f"no snapshot at step {from_step}")
    return {"prefix_steps": len(prefix), "forked_node": at["node"]}