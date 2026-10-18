"""Dependency-aware fan-out with overlap instrumentation and a LangGraph Send demo graph."""

from __future__ import annotations

import operator
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any

from typing_extensions import TypedDict


class _FanState(TypedDict, total=False):
    tasks: list[dict]
    task: dict
    marks: Annotated[list[dict], operator.add]


def batches(tasks: list[dict]) -> list[list[dict]]:
    """Topological batches: dependents never start before prerequisites finish."""
    by_id = {t["id"]: t for t in tasks}
    pending = {t["id"]: set(t.get("depends_on", [])) for t in tasks}
    done: set[str] = set()
    out: list[list[dict]] = []
    while pending:
        ready = [by_id[tid] for tid, deps in pending.items() if deps <= done]
        if not ready:
            raise ValueError("cyclic or unknown prerequisites")
        out.append(sorted(ready, key=lambda t: t["id"]))
        for task in ready:
            done.add(task["id"])
            del pending[task["id"]]
    return out


def run_parallel(tasks: list[dict], fn, max_workers: int = 8) -> dict[str, dict]:
    """Run one dependency batch concurrently; record start/end per task."""
    results: dict[str, dict] = {}

    def _wrap(task: dict) -> tuple[str, dict]:
        started = time.time()
        try:
            value = fn(task)
            return task["id"], {"value": value, "started": started, "ended": time.time(), "error": None}
        except Exception as exc:  # noqa: BLE001 - errors are recorded per task
            return task["id"], {"value": None, "started": started, "ended": time.time(), "error": str(exc)}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for task_id, record in pool.map(_wrap, tasks):
            results[task_id] = record
    return results


def run_ordered(tasks: list[dict], fn) -> tuple[dict[str, dict], list[list[str]]]:
    """Run dependency batches in order; tasks inside a batch overlap."""
    all_results: dict[str, dict] = {}
    order: list[list[str]] = []
    for batch in batches(tasks):
        order.append([t["id"] for t in batch])
        all_results.update(run_parallel(batch, fn))
    return all_results, order


def overlap_of(results: dict[str, dict], first: str, second: str) -> bool:
    """True when `second` started before `first` finished (independent overlap)."""
    return results[second]["started"] < results[first]["ended"]


def build_send_graph():
    """Small compiled graph proving LangGraph Send fan-out overlaps independent work."""
    from langgraph.graph import StateGraph
    from langgraph.types import Send

    def fanout(state: _FanState):
        return [Send("worker", {"task": task}) for task in state.get("tasks", [])]

    def worker(state: _FanState) -> dict:
        task: dict[str, Any] = dict(state.get("task", {}))
        started = time.time()
        time.sleep(task.get("sleep", 0.05))
        return {"marks": [{"id": task.get("id"), "started": started, "ended": time.time()}]}

    builder = StateGraph(_FanState)
    builder.add_node("fanout", lambda state: {})
    builder.add_node("worker", worker)
    builder.set_entry_point("fanout")
    builder.add_conditional_edges("fanout", fanout, ["worker"])
    builder.set_finish_point("worker")
    return builder.compile()