"""Phase-2 acceptance: entrypoints, typed errors, persistence, reports, resume."""

import tempfile
import unittest

from relay import checkpoints
from relay.core import RelayConfig, RelayRunner
from relay.evals.pipeline import load_scenarios, run_all
from relay.evals.report import render
from relay.graph import build_graph
from relay.tools import storage as storetools


class Phase2Tests(unittest.TestCase):
    def test_entrypoints_and_invalid_bucket(self):
        self.assertIsNotNone(build_graph())
        self.assertGreaterEqual(len(load_scenarios()), 10)
        with self.assertRaises(storetools.InvalidName):
            storetools.parse_bucket("BAD-NAME")

    def test_world_reopen_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = RelayRunner(RelayConfig(state_dir=f"{tmp}/state"))
            first.run("upload keep.txt to acme-dev-raw content hi")
            second = RelayRunner(RelayConfig(state_dir=f"{tmp}/state"))
            out = second.run("download keep.txt from acme-dev-raw")
            self.assertEqual(out["status"], "completed")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_all(f"{tmp}/evals", baseline=True)
            rendered = render(f"{tmp}/evals/evals.db", result["run_id"])
            import os
            self.assertTrue(os.path.exists(rendered["html"]))

    def test_cross_process_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            paused = RelayRunner(RelayConfig(state_dir=f"{tmp}/state")).run("upload x.txt to acme-prod-curated content hi", thread_id="p2")
            self.assertEqual(paused["status"], "paused")
            resumed = RelayRunner(RelayConfig(state_dir=f"{tmp}/state")).resume("p2", [{"approver": "amy", "role": "data_owner", "approved": True}])
            self.assertEqual(resumed["status"], "completed")
            self.assertTrue(checkpoints.load_history(f"{tmp}/state/checkpoints.db", "p2"))


if __name__ == "__main__":
    unittest.main()