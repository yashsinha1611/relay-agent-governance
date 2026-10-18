"""Compiled LangGraph workflow: intake -> plan -> dispatch -> specialists -> review -> policy -> execute."""

from __future__ import annotations

import time
from typing import Any

from typing_extensions import TypedDict

from langgraph.graph import StateGraph
from langgraph.types import Send

from shared.schemas import Plan
from relay import checkpoints, dispatch as dispatchlib
from relay.memory import store as memorystore
from relay.obs import tracing as tracinglib
from relay.policy import detect_injection, evaluate
from relay.planner import plan_ticket
from relay.specialists import MAX_TOOL_STEPS, run_task
from relay.tools.world import apply_action, init_world

REVIEWER_CAP = 2


class RelayState(TypedDict, total=False):
    ticket: str
    requester: str
    approvals: list[dict]
    plan: dict
    memory_context: list[dict]
    results: list[dict]
    actions: list[dict]
    trajectory: list[dict]
    status: str
    reasons: list[str]
    policy_variant: str
    reviewer_mode: str
    reviewer_rejections: int
    world_db: str
    memory_db: str
    trace_db: str
    checkpoint_db: str
    thread_id: str
    flow: str
    injection_attempt: str | None
    memory_written: bool


def _step(state: RelayState, node: str) -> int:
    return int(state.get("_step", 0)) + 1  # type: ignore[typeddict-item]


def _track(state: RelayState, node: str) -> dict:
    step = _step(state, node)
    checkpoints.save_snapshot(state["checkpoint_db"], state["thread_id"], step, node, dict(state))
    checkpoints.record_invocation(state["checkpoint_db"], state["thread_id"], node)
    nodes = list(state.get("nodes", []))  # type: ignore[typeddict-item]
    nodes.append({"node": node, "step": step, "at": time.time()})
    return {"_step": step, "nodes": nodes}


def intake(state: RelayState) -> dict:
    ticket = (state.get("ticket") or "").strip()
    update = _track(state, "intake")
    update.update({"ticket": ticket, "injection_attempt": detect_injection(ticket)})
    return update


def memory_lookup(state: RelayState) -> dict:
    update = _track(state, "memory_lookup")
    update.update({"memory_context": memorystore.retrieve(state["memory_db"], state.get("ticket", ""), limit=3)})
    return update


def supervisor_plan(state: RelayState) -> dict:
    update = _track(state, "supervisor_plan")
    update.update({"plan": plan_ticket(state.get("ticket", "")).model_dump(mode="json")})
    return update


def dispatch(state: RelayState):
    tasks = [t for t in Plan.model_validate(state.get("plan") or {}).subtasks]
    if not tasks:
        return "reviewer"
    # Dependency wave 0 fans out via Send; later waves are handled after the join.
    done = {r.get("task_id") for r in state.get("results", [])}
    ready = [t for t in tasks if set(t.depends_on) <= done and t.id not in done]
    if not ready:
        return "reviewer"
    # Send payloads carry the full parent state plus the routed task, because
    # LangGraph invokes Send targets with the payload alone.
    base = {k: v for k, v in dict(state).items() if k != "dispatch_task"}
    return [Send("specialist", dict(base) | {"dispatch_task": t.model_dump(mode="json")}) for t in ready]


def specialist(state: RelayState) -> dict:
    task_data = state.get("dispatch_task", {})  # type: ignore[typeddict-item]
    from shared.schemas import Subtask as SubtaskModel

    task = SubtaskModel.model_validate(task_data)
    result = run_task(state["world_db"], task)
    update = _track(state, "specialist")
    results = list(state.get("results", [])) + [result.model_dump(mode="json")]
    trajectory = list(state.get("trajectory", [])) + [r.model_dump(mode="json") for r in result.trajectory]
    update.update({"results": results, "trajectory": trajectory})
    return update


def join(state: RelayState) -> dict:
    update = _track(state, "join")
    planned = {t.id for t in Plan.model_validate(state.get("plan") or {}).subtasks}
    done = {r.get("task_id") for r in state.get("results", [])}
    update.update({"dispatch_complete": planned <= done})
    return update


def reviewer(state: RelayState) -> dict:
    update = _track(state, "reviewer")
    rejections = int(state.get("reviewer_rejections", 0))
    failed = [r for r in state.get("results", []) if not r.get("success")]
    actions = [r.get("action") for r in state.get("results", []) if r.get("success") and r.get("action")]
    # Rejection cap is exactly two: reviewer_mode="reject" forces the reviewer to
    # reject twice in this pass, reaching the cap and escalating to human review.
    if state.get("reviewer_mode") == "reject":
        total = rejections + REVIEWER_CAP
        update.update({"reviewer_rejections": total, "actions": [], "status": "escalated",
                       "reasons": ["reviewer rejection cap reached"]})
        return update
    if failed and rejections >= REVIEWER_CAP:
        update.update({"status": "escalated", "reasons": ["reviewer rejection cap reached"], "actions": []})
        return update
    if failed:
        update.update({"reviewer_rejections": rejections + 1, "actions": [], "status": "failed",
                       "reasons": [f"tool failure: {(r.get('trajectory') or [{}])[-1].get('error')}" for r in failed]})
        return update
    update.update({"actions": actions})
    return update


def injection_scan(state: RelayState) -> dict:
    update = _track(state, "injection_scan")
    # Recorded at intake; this node guarantees it cannot alter approvals or policy.
    update.update({"injection_attempt": state.get("injection_attempt")})
    return update


def policy_gate(state: RelayState) -> dict:
    update = _track(state, "policy_gate")
    if state.get("status") in ("failed", "escalated"):
        return update
    from shared.schemas import Action as ActionModel

    actions = [ActionModel.model_validate(a) for a in state.get("actions", [])]
    verdict = evaluate(actions, state.get("approvals", []), state.get("requester", ""), state.get("policy_variant", "strict"))
    update.update({"status": verdict["decision"], "reasons": verdict["reasons"]})
    return update


def execute_dry_run(state: RelayState) -> dict:
    update = _track(state, "execute_dry_run")
    if state.get("status") != "approved":
        return update
    from shared.schemas import Action as ActionModel

    init_world(state["world_db"])
    applied = []
    try:
        for item in state.get("actions", []):
            applied.append(apply_action(state["world_db"], ActionModel.model_validate(item)))
    except Exception as exc:  # noqa: BLE001 - failed writes leave status failed
        update.update({"status": "failed", "reasons": [f"apply failed: {exc}"]})
        return update
    update.update({"status": "completed", "applied": applied})
    return update


def memory_write(state: RelayState) -> dict:
    update = _track(state, "memory_write")
    if state.get("memory_written"):
        return update
    memorystore.persist_episode(
        state["memory_db"], state.get("ticket", ""), state.get("plan") or {},
        state.get("status", ""), f"{state.get('ticket','')} -> {state.get('status','')}",
        state.get("requester", ""), {"thread_id": state.get("thread_id", ""), "flow": state.get("flow", "standard")},
    )
    tracinglib.record_trace(state["trace_db"], state["thread_id"], state.get("status", ""),
                            state.get("nodes", []) + [{"node": "memory_write", "step": update["_step"], "at": time.time()}],
                            state.get("trajectory", []), state.get("approvals", []),
                            [{"message": r} for r in state.get("reasons", [])])
    update.update({"memory_written": True})
    return update


def route_after_join(state: RelayState) -> str:
    planned = {t.id for t in Plan.model_validate(state.get("plan") or {}).subtasks}
    done = {r.get("task_id") for r in state.get("results", [])}
    if planned and not planned <= done:
        # More dependency waves remain: route back through dispatch Send fan-out.
        return "dispatch"
    return "reviewer"


def route_after_policy(state: RelayState) -> str:
    if state.get("status") == "paused":
        return "memory_write"
    return "execute_dry_run"


def build_graph(checkpointer=None, interrupt_before_policy: bool = False):
    builder = StateGraph(RelayState)
    builder.add_node("intake", intake)
    builder.add_node("memory_lookup", memory_lookup)
    builder.add_node("supervisor_plan", supervisor_plan)
    builder.add_node("dispatch", lambda state: _track(state, "dispatch"))
    builder.add_node("specialist", specialist)
    builder.add_node("join", join)
    builder.add_node("reviewer", reviewer)
    builder.add_node("injection_scan", injection_scan)
    builder.add_node("policy_gate", policy_gate)
    builder.add_node("execute_dry_run", execute_dry_run)
    builder.add_node("memory_write", memory_write)
    builder.set_entry_point("intake")
    builder.add_edge("intake", "memory_lookup")
    builder.add_edge("memory_lookup", "supervisor_plan")
    builder.add_edge("supervisor_plan", "dispatch")
    builder.add_conditional_edges("dispatch", dispatch, ["specialist", "reviewer"])
    builder.add_edge("specialist", "join")
    builder.add_conditional_edges("join", route_after_join, ["dispatch", "reviewer"])
    builder.add_edge("reviewer", "injection_scan")
    builder.add_edge("injection_scan", "policy_gate")
    builder.add_conditional_edges("policy_gate", route_after_policy, ["execute_dry_run", "memory_write"])
    builder.add_edge("execute_dry_run", "memory_write")
    builder.set_finish_point("memory_write")
    kwargs: dict[str, Any] = {}
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer
    if interrupt_before_policy:
        kwargs["interrupt_before"] = ["policy_gate"]
    return builder.compile(**kwargs)


def build_resume_graph(checkpointer=None):
    """Resume uses the same compiled topology; LangGraph continues past the interrupt."""
    return build_graph(checkpointer=checkpointer, interrupt_before_policy=True)