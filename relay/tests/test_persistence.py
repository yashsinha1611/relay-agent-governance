import tempfile
import time
import unittest
from pathlib import Path

from relay import checkpoints
from relay.dispatch import batches, build_send_graph, overlap_of, run_ordered
from relay.memory import store as memory
from relay.obs import tracing as tracinglib


class PersistenceTests(unittest.TestCase):
    def test_memory_cross_process_and_index_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.db"
            memory.persist_episode(db, "upload report.csv to acme-dev-raw", {"subtasks": []}, "completed", "upload report completed", "amy", {})
            memory.persist_episode(db, "add bob to analysts", {"subtasks": []}, "completed", "directory change", "amy", {})
            # New handle, same file: proves cross-process retrieval.
            hits = memory.retrieve(str(db), "upload report acme-dev-raw")
            self.assertTrue(hits and "upload" in hits[0]["ticket"])
            self.assertEqual(memory.retrieve(str(db), "zzz-no-match"), [])
            self.assertEqual(memory.retrieve(Path(tmp) / "missing.db", "anything"), [])

    def test_tracing_orders_and_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "traces.db"
            now = time.time()
            nodes = [{"node": "intake", "started": now, "ended": now + 1}, {"node": "policy_gate", "started": now + 1, "ended": now + 2}]
            tid = tracinglib.record_trace(db, "t1", "completed", nodes, [{"call": {"name": "storage.read_object"}, "error": {"code": "NotFound", "message": "gone"}}], [{"approver": "amy"}], [{"message": "boom"}])
            got = tracinglib.get_trace(db, tid)
            self.assertIsNotNone(got)
            assert got is not None
            self.assertLess(got["nodes"][0]["started"], got["nodes"][1]["started"])
            self.assertEqual(got["trajectory"][0]["error"]["code"], "NotFound")
            self.assertEqual(got["approvals"], [{"approver": "amy"}])
            self.assertTrue(tracinglib.list_traces(db, "t1"))

    def test_checkpoint_history_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "c.db"
            checkpoints.save_snapshot(db, "th", 1, "intake", {"ticket": "t"})
            checkpoints.save_snapshot(db, "th", 2, "policy_gate", {"ticket": "t", "status": "paused"})
            history = checkpoints.load_history(db, "th")
            self.assertEqual([h["step"] for h in history], [1, 2])
            self.assertEqual(checkpoints.load_latest(db, "th")["node"], "policy_gate")
            checkpoints.record_invocation(db, "th", "supervisor_plan")
            checkpoints.record_invocation(db, "th", "supervisor_plan")
            self.assertEqual(checkpoints.invocation_counts(db, "th")["supervisor_plan"], 2)
            self.assertEqual(checkpoints.load_history(Path(tmp) / "missing.db", "th"), [])

    def test_dispatch_overlap_and_dependencies(self):
        tasks = [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}, {"id": "c", "depends_on": ["a", "b"]}]
        order = [[t["id"] for t in batch] for batch in batches(tasks)]
        self.assertEqual(order[0], ["a", "b"])
        self.assertEqual(order[1], ["c"])

        def slow(task):
            if task["id"] in ("a", "b"):
                time.sleep(0.08)
            return task["id"]

        results, _ = run_ordered([{"id": "a", "depends_on": []}, {"id": "b", "depends_on": []}], slow)
        self.assertTrue(overlap_of(results, "a", "b"))
        dep_results, _ = run_ordered(tasks, lambda t: (time.sleep(0.01), t["id"])[1])
        self.assertGreaterEqual(dep_results["c"]["started"], max(dep_results["a"]["ended"], dep_results["b"]["ended"]))
        with self.assertRaises(ValueError):
            batches([{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}])

    def test_send_graph_overlaps(self):
        graph = build_send_graph()
        out = graph.invoke({"tasks": [{"id": "a", "sleep": 0.08}, {"id": "b", "sleep": 0.08}]})
        marks = {m["id"]: m for m in out["marks"]}
        self.assertLess(marks["b"]["started"], marks["a"]["ended"])


if __name__ == "__main__":
    unittest.main()