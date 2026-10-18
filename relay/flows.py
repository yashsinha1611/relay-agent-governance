"""Sequential / map-reduce / plan-execute-replan / saga workflow subgraphs."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from relay.dispatch import batches, overlap_of, run_ordered

REPLAN_CAP = 2


def sequential(tasks: list[dict], fn) -> list:
    """Run dependency batches in order; returns per-batch ID lists plus values."""
    values: list = []
    for batch in batches(tasks):
        for task in batch:
            values.append(fn(task))
    return values


def map_reduce(tasks: list[dict], fn) -> dict:
    """Run independent tasks concurrently; record peak overlap."""
    started_all = time.time()
    results, order = run_ordered(tasks, fn)
    peak = 0
    events: list[tuple[float, int]] = []
    for record in results.values():
        events.append((record["started"], 1))
        events.append((record["ended"], -1))
    running = 0
    for _, delta in sorted(events):
        running += delta
        peak = max(peak, running)
    overlapped = False
    ids = list(results)
    if len(ids) >= 2:
        overlapped = overlap_of(results, ids[0], ids[1]) or overlap_of(results, ids[1], ids[0])
    return {"results": results, "order": order, "peak_concurrency": peak, "overlapped": overlapped, "elapsed": time.time() - started_all}


def plan_execute_replan(plan_fn, execute_fn, max_replans: int = REPLAN_CAP) -> dict:
    """Replan loop capped at two replans; returns attempts and final value."""
    replans = 0
    plan = plan_fn(0)
    while True:
        outcome = execute_fn(plan)
        if outcome.get("ok") or replans >= max_replans:
            return {"plan": plan, "outcome": outcome, "replans": replans, "capped": replans >= max_replans and not outcome.get("ok")}
        replans += 1
        plan = plan_fn(replans)


def saga(operations: list[dict], apply_fn, compensate_fn) -> dict:
    """Apply operations; on failure compensate applied ones in reverse."""
    applied: list[dict] = []
    compensated: list[dict] = []
    for operation in operations:
        try:
            apply_fn(operation)
            applied.append(operation)
        except Exception as exc:  # noqa: BLE001 - record then compensate
            for done in reversed(applied):
                compensate_fn(done)
                compensated.append(done)
            return {"applied": applied, "failed": operation, "compensated": compensated, "error": str(exc), "ok": False}
    return {"applied": applied, "failed": None, "compensated": compensated, "error": "", "ok": True}


def run_threadpool(tasks: list[dict], fn, max_workers: int = 8) -> dict:
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return dict(zip([t["id"] for t in tasks], pool.map(fn, tasks)))