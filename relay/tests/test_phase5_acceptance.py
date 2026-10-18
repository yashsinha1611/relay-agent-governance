"""Phase-5 acceptance: plugins, skills, flows, MCP, replay, DB-only reports."""

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from relay import checkpoints
from relay.core import RelayConfig, RelayRunner
from relay.evals.pipeline import run_all
from relay.evals.report import render
from relay.flows import REPLAN_CAP, map_reduce, plan_execute_replan, saga, sequential
from relay.mcp import MCPValidationError, invoke
from relay.plugins.registry import PluginScopeViolation, build_default_registry, metrics, record_violation
from relay.replay import diff_prefix
from relay.skills.registry import disclosure_savings, list_skills, load_skill
from shared.schemas import ToolCall


def approvals(*names, role="approver"):
    return [{"approver": n, "role": role, "approved": True} for n in names]


class Phase5Tests(unittest.TestCase):
    def test_plugin_scopes(self):
        registry = build_default_registry()
        self.assertIn("storage", registry.list())
        self.assertIsNotNone(registry.tool("notebook", "notebook.summarize"))
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "plugins.db")
            registry.call(db, "notebook", "notebook.summarize", "hello world")
            with self.assertRaises(PluginScopeViolation):
                registry.call(db, "notebook", "storage.plan_delete", "x")
            record_violation(db, "notebook", "storage.plan_delete")
            self.assertGreaterEqual(metrics(db)["notebook"]["violations"], 1)

    def test_plugin_removal_mutation(self):
        registry = build_default_registry()
        registry.remove("notebook")
        self.assertNotIn("notebook", registry.list())

    def test_progressive_skills(self):
        listed = list_skills()
        self.assertGreaterEqual(len(listed), 2)
        bodies = {item["name"]: load_skill(item["name"]) for item in listed}
        savings = disclosure_savings(listed[0]["name"], bodies)
        self.assertGreater(savings["saved_chars"], 0)
        eager_chars = sum(len(body) for body in bodies.values())
        self.assertGreater(eager_chars, savings["selected_chars"])

    def test_flows(self):
        order: list[str] = []
        sequential([{"id": "a", "depends_on": []}, {"id": "b", "depends_on": ["a"]}], lambda t: order.append(t["id"]))
        self.assertEqual(order, ["a", "b"])

        def slow(task):
            time.sleep(0.06)
            return task["id"]
        mr = map_reduce([{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}], slow)
        self.assertTrue(mr["overlapped"])
        self.assertGreaterEqual(mr["peak_concurrency"], 2)

        attempts = {"n": 0}
        def execute(plan):
            attempts["n"] += 1
            return {"ok": attempts["n"] > 5}
        capped = plan_execute_replan(lambda n: {"attempt": n}, execute)
        self.assertEqual(capped["replans"], REPLAN_CAP)

        applied: list[str] = []
        def apply(op):
            if op["id"] == "bad":
                raise RuntimeError("boom")
            applied.append(op["id"])
        undone: list[str] = []
        result = saga([{"id": "good"}, {"id": "bad"}], apply, lambda op: undone.append(op["id"]))
        self.assertFalse(result["ok"])
        self.assertEqual(undone, ["good"])

    def test_mcp_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = RelayRunner(RelayConfig(state_dir=f"{tmp}/state"))
            ok = invoke(f"{tmp}/state/world.db", ToolCall(name="storage.list_objects", arguments={"bucket": "acme-dev-raw"}))
            self.assertIsNone(ok.error)
            bad = invoke(f"{tmp}/state/world.db", ToolCall(name="storage.list_objects", arguments={"bucket": "BAD"}))
            self.assertIsNotNone(bad.error)
            with self.assertRaises(MCPValidationError):
                invoke(f"{tmp}/state/world.db", ToolCall(name="storage.list_objects", arguments={"wrong": 1}))
            with self.assertRaises(MCPValidationError):
                invoke(f"{tmp}/state/world.db", ToolCall(name="remote.evil", arguments={}))

    def test_replay_and_db_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = RelayRunner(RelayConfig(state_dir=f"{tmp}/state"))
            paused = runner.run("upload r.txt to acme-prod-curated content hi", thread_id="p5")
            history = checkpoints.load_history(f"{tmp}/state/checkpoints.db", "p5")
            first_step = history[0]["step"]
            diff = diff_prefix(history, paused["_snapshot_step"])
            self.assertGreaterEqual(diff["prefix_steps"], 0)
            self.assertEqual(diff["forked_node"], paused["_snapshot_node"])
            before = runner.invocation_counts("p5")
            forked = runner.replay("p5", paused["_snapshot_step"], {"approvals": approvals("amy", role="data_owner")})
            self.assertEqual(forked["status"], "completed")
            self.assertEqual(runner.invocation_counts("p5").get("supervisor_plan"), before.get("supervisor_plan"))
            # Mutation guard: forking at a step that was never snapshotted must fail
            # instead of silently replaying from step zero.
            with self.assertRaises(KeyError):
                diff_prefix(history, first_step - 1)
        with tempfile.TemporaryDirectory() as tmp:
            result = run_all(f"{tmp}/evals", baseline=True)
            rendered = render(f"{tmp}/evals/evals.db", result["run_id"])
            import os
            self.assertTrue(os.path.exists(rendered["md"]))
            from contextlib import closing
            with closing(sqlite3.connect(f"{tmp}/evals/evals.db")) as conn:
                self.assertTrue(conn.execute("SELECT run_id FROM runs").fetchall())


if __name__ == "__main__":
    unittest.main()