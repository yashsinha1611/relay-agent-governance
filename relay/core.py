"""Public RelayRunner facade: builds the graph, owns state_dir, pauses/resumes safely.

Pause/resume honesty note: LangGraph's ``interrupt``/``Command`` resume protocol is
referenced, but the durable cross-process guarantee here comes from Relay's own
SQLite snapshots (``relay/checkpoints.py``): ``run`` persists every node snapshot,
``resume`` loads the latest snapshot in a new process and continues only through
the policy tail. Planning/dispatch/specialist nodes are never re-invoked on resume.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from shared.llm.provider import ModelConfig, get_model
from shared.schemas import Approval
from relay import checkpoints
from relay.graph import build_graph
from relay.memory import store as memorystore
from relay.obs import tracing as tracinglib
from relay.policy import evaluate
from relay.tools.world import hash_world, init_world


class _Paused(Exception):
    def __init__(self, state: dict):
        super().__init__("paused for approval")
        self.state = state


@dataclass
class RelayConfig:
    policy_variant: str = "strict"
    model_config: ModelConfig = field(default_factory=ModelConfig)
    state_dir: str | Path = "state"
    reviewer_mode: str = ""
    flow: str = "standard"


class RelayRunner:
    def __init__(self, config: RelayConfig | None = None):
        self.config = config or RelayConfig()
        # Provider resolved but never invoked during construction; mock by default.
        self.model = get_model(self.config.model_config)
        self.state_dir = Path(self.config.state_dir)
        self.world_db = str(self.state_dir / "world.db")
        self.memory_db = str(self.state_dir / "memory.db")
        self.trace_db = str(self.state_dir / "traces.db")
        self.checkpoint_db = str(self.state_dir / "checkpoints.db")
        init_world(self.world_db)
        memorystore.init_memory(self.memory_db)
        tracinglib.init_traces(self.trace_db)
        checkpoints.init_checkpoints(self.checkpoint_db)

    def _initial_state(self, ticket: str, requester: str, approvals: list[dict], thread_id: str) -> dict:
        return {
            "ticket": ticket, "requester": requester, "approvals": approvals,
            "plan": {}, "memory_context": [], "results": [], "actions": [],
            "trajectory": [], "status": "running", "reasons": [],
            "policy_variant": self.config.policy_variant, "reviewer_mode": self.config.reviewer_mode,
            "reviewer_rejections": 0, "world_db": self.world_db, "memory_db": self.memory_db,
            "trace_db": self.trace_db, "checkpoint_db": self.checkpoint_db,
            "thread_id": thread_id, "flow": self.config.flow, "injection_attempt": None,
            "memory_written": False, "_step": 0, "nodes": [],
        }

    def _normalize(self, state: dict, thread_id: str) -> dict:
        # No fabricated policy evidence: reasons come from graph state only.
        return {
            "thread_id": thread_id, "status": state.get("status", "failed"),
            "reasons": list(state.get("reasons", [])),
            "actions": list(state.get("actions", []) or state.get("applied", [])),
            "trajectory": list(state.get("trajectory", [])),
            "results": list(state.get("results", [])),
            "plan": state.get("plan") or {},
            "approvals": list(state.get("approvals", [])),
            "injection_attempt": state.get("injection_attempt"),
            "memory_context": list(state.get("memory_context", [])),
            "world_hash": hash_world(self.world_db),
        }

    @staticmethod
    def _approvals(approvals: list[dict] | None) -> list[dict]:
        return [Approval.model_validate(a).model_dump(mode="json") for a in (approvals or [])]

    def run(self, ticket: str, requester: str = "requester", approvals: list[dict] | None = None, thread_id: str | None = None) -> dict:
        """Run intake..memory_write once through the compiled graph.

        Sensitive runs without approvals finish as ``paused`` with world.db
        untouched; the persisted snapshots allow a new process to resume.
        """
        approvals = self._approvals(approvals)
        thread_id = thread_id or uuid.uuid4().hex[:12]
        state = self._initial_state(ticket, requester, approvals, thread_id)
        import relay.graph as graphmod

        original_gate = graphmod.policy_gate

        def pausing_gate(inner_state: dict) -> dict:
            pre = original_gate(inner_state)
            if pre.get("status") == "paused":
                raise _Paused(dict(inner_state) | dict(pre))
            return pre

        graphmod.policy_gate = pausing_gate  # type: ignore[assignment]
        try:
            finished = build_graph().invoke(state)
        except _Paused as done:
            final = self._normalize(done.state, thread_id)
            latest = checkpoints.load_latest(self.checkpoint_db, thread_id)
            if latest:
                final["_snapshot_step"] = latest["step"]
                final["_snapshot_node"] = latest["node"]
            return final
        finally:
            graphmod.policy_gate = original_gate  # type: ignore[assignment]
        final = self._normalize(finished, thread_id)
        latest = checkpoints.load_latest(self.checkpoint_db, thread_id)
        if latest:
            final["_snapshot_step"] = latest["step"]
            final["_snapshot_node"] = latest["node"]
        return final

    def resume(self, thread_id: str, approvals: list[dict]) -> dict:
        """Resume a paused thread in this or a new process from persisted snapshots."""
        approvals = self._approvals(approvals)
        latest = checkpoints.load_latest(self.checkpoint_db, thread_id)
        if latest is None:
            raise KeyError(f"unknown thread {thread_id}")
        state = dict(latest["state"])
        before = self.invocation_counts(thread_id)
        state["approvals"] = approvals
        state["memory_written"] = False
        state["status"] = "running"
        state["reasons"] = []
        from relay.graph import execute_dry_run, memory_write, policy_gate

        # Continue from the policy tail only: planning/dispatch/specialist nodes are
        # never re-invoked, so invocation counters for the prefix stay stable.
        continued = policy_gate(state)
        state.update(continued)
        if continued.get("status") == "paused":
            return self._normalize(state, thread_id)
        if continued.get("status") in ("blocked", "escalated", "failed"):
            tail_mem = memory_write(state)
            state.update(tail_mem)
            return self._normalize(state, thread_id)
        tail_exec = execute_dry_run(state)
        state.update(tail_exec)
        tail_mem = memory_write(state)
        state.update(tail_mem)
        after = self.invocation_counts(thread_id)
        if after.get("supervisor_plan", 0) != before.get("supervisor_plan", 0):
            raise RuntimeError("resume re-executed planning")
        return self._normalize(state, thread_id)

    def invocation_counts(self, thread_id: str) -> dict[str, int]:
        return checkpoints.invocation_counts(self.checkpoint_db, thread_id)

    def replay(self, thread_id: str, from_step: int, overrides: dict | None = None) -> dict:
        """Fork at step N: preserve prefix, apply overrides downstream."""
        history = checkpoints.load_history(self.checkpoint_db, thread_id)
        if not history:
            raise KeyError(f"unknown thread {thread_id}")
        prefix = [h for h in history if h["step"] < from_step]
        at = next((h for h in history if h["step"] >= from_step), history[-1])
        if at["step"] != from_step:
            raise KeyError(f"no snapshot at step {from_step}")
        state = dict(at["state"])
        for key, value in (overrides or {}).items():
            if not key.startswith("_"):
                state[key] = value
        state["memory_written"] = False
        before = self.invocation_counts(thread_id)
        from relay.graph import execute_dry_run, memory_write, policy_gate

        continued = policy_gate(state)
        state.update(continued)
        if continued.get("status") == "approved":
            state.update(execute_dry_run(state))
        state.update(memory_write(state))
        tail_result = self._normalize(state, thread_id)
        if overrides:
            tail_result["overrides"] = dict(overrides)
        tail_result["replay_from_step"] = from_step
        tail_result["prefix_steps"] = len(prefix)
        tail_result["prefix_stable"] = all(
            self.invocation_counts(thread_id).get(n, 0) >= before.get(n, 0) for n in before
        )
        checkpoints.record_invocation(self.checkpoint_db, thread_id, "replay")
        return tail_result

    def evaluate_policy(self, actions: list, approvals: list[dict], requester: str) -> dict:
        return evaluate(actions, approvals, requester, self.config.policy_variant)