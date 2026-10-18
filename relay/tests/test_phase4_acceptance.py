"""Phase-4 acceptance: real tools, budgets, transactions, memory, checkpoints, hashes."""

import tempfile
import unittest

from relay.core import RelayConfig, RelayRunner
from relay.memory import store as memory
from relay.specialists import MAX_TOOL_STEPS
from relay.tools.world import hash_world


class Phase4Tests(unittest.TestCase):
    def test_real_execution_budgets_and_hashes(self):
        self.assertEqual(MAX_TOOL_STEPS, 5)
        with tempfile.TemporaryDirectory() as tmp:
            runner = RelayRunner(RelayConfig(state_dir=f"{tmp}/state"))
            missing = runner.run("download absent.csv from acme-dev-raw")
            self.assertEqual(missing["status"], "failed")
            self.assertEqual(missing["actions"], [])
            for result in missing["results"]:
                self.assertLessEqual(len(result["trajectory"]), 5)
            before = hash_world(f"{tmp}/state/world.db")
            blocked = runner.run("delete notes.txt from acme-dev-raw", approvals=[{"approver": "amy", "approved": True}], thread_id="p4-block")
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(hash_world(f"{tmp}/state/world.db"), before)
            counts = runner.invocation_counts("p4-block")
            self.assertEqual(counts.get("supervisor_plan"), 1)

    def test_memory_persists_and_indexes(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = RelayRunner(RelayConfig(state_dir=f"{tmp}/state"))
            runner.run("upload episode.txt to acme-dev-raw content memorable")
            hits = memory.retrieve(f"{tmp}/state/memory.db", "episode memorable upload")
            self.assertTrue(hits)


if __name__ == "__main__":
    unittest.main()