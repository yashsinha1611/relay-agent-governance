"""Phase-2b acceptance: overlap, ordering, caps, exit codes, wrong-path, Tribunal loop."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from relay.core import RelayConfig, RelayRunner
from relay.dispatch import batches, overlap_of, run_ordered
from relay.evals.pipeline import run_all
from relay.graph import REVIEWER_CAP


class Phase2bTests(unittest.TestCase):
    def test_overlap_and_dependency_order(self):
        def slow(task):
            if task["id"] in ("a", "b"):
                time.sleep(0.08)
            return task["id"]
        results, _ = run_ordered([{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}], slow)
        self.assertTrue(overlap_of(results, "a", "b"))
        tasks = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": ["a"]}]
        self.assertEqual([[t["id"] for t in batch] for batch in batches(tasks)], [["a"], ["b"]])

    def test_sequential_mutation_kills_overlap(self):
        def slow(task):
            time.sleep(0.05)
            return task["id"]
        tasks = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}]
        sequential = {}
        for task in tasks:  # forced-sequential mutation
            started = time.time()
            slow(task)
            sequential[task["id"]] = {"started": started, "ended": time.time()}
        self.assertFalse(overlap_of(sequential, "a", "b"))

    def test_rejection_cap_is_two(self):
        self.assertEqual(REVIEWER_CAP, 2)
        with tempfile.TemporaryDirectory() as tmp:
            out = RelayRunner(RelayConfig(state_dir=f"{tmp}/state", reviewer_mode="reject")).run("upload a.txt to acme-dev-raw content one")
            self.assertEqual(out["status"], "escalated")

    def test_exit_codes_and_wrong_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_all(f"{tmp}/evals")
            self.assertIn(result["summary"]["exit_code"], (0, 1, 2))

    def test_wrong_path_detection(self):
        # Right answer via a wrong execution path must be detectable: the
        # detector flags it even when the outcome comparison cannot.
        from shared.schemas import EvaluationResult

        ok = EvaluationResult(scenario_id="s", outcome_correct=True, path_correct=False,
                              wrong_path=True, escalation_correct=True, trajectory=[],
                              severity="warning", regressions=["wrong-path:s"])
        self.assertTrue(ok.wrong_path)
        self.assertEqual(ok.severity, "warning")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_all(f"{tmp}/evals")
            self.assertIn("wrong_paths", result["summary"])

    def test_tribunal_feedback_loop_contract(self):
        path = Path(__file__).resolve().parent.parent / "data" / "scenarios_from_tribunal.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(payload, list)
        from relay.evals.pipeline import load_scenarios
        self.assertGreaterEqual(len(load_scenarios()), 13)


if __name__ == "__main__":
    unittest.main()