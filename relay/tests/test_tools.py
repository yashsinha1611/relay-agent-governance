import tempfile
import unittest
from pathlib import Path

from relay.tools import (
    DirectoryNotFound,
    InvalidName,
    NotFound,
    apply_action,
    hash_world,
    init_world,
    list_objects,
    lookup_user,
    parse_bucket,
    plan_add_member,
    plan_delete,
    plan_download,
    plan_upload,
    read_object,
    seed_user,
)


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.world = init_world(Path(self.tmp.name) / "world.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_bucket_matrix(self):
        for env in ("dev", "test", "staging", "prod"):
            for zone in ("raw", "curated", "archive"):
                parsed = parse_bucket(f"acme-{env}-{zone}")
                self.assertEqual((parsed["env"], parsed["zone"]), (env, zone))
        for bad in ("ACME-dev-raw", "acme-dev", "acme-qa-raw", "acme-dev-tmp", "", "acme--raw"):
            with self.assertRaises(InvalidName):
                parse_bucket(bad)

    def test_real_reads_and_missing(self):
        self.assertIn("report.csv", list_objects(self.world, "acme-dev-raw"))
        self.assertTrue(read_object(self.world, "acme-dev-raw", "report.csv").startswith("id,value"))
        with self.assertRaises(NotFound):
            read_object(self.world, "acme-dev-raw", "absent.csv")

    def test_planned_actions_apply_transactionally(self):
        before = hash_world(self.world)
        self.assertNotEqual(before, "")
        apply_action(self.world, plan_upload("acme-dev-raw", "new.txt", "hello"))
        self.assertIn("new.txt", list_objects(self.world, "acme-dev-raw"))
        # Download validates existence without mutating content rows.
        apply_action(self.world, plan_download("acme-dev-raw", "new.txt"))
        apply_action(self.world, plan_delete("acme-dev-raw", "new.txt"))
        with self.assertRaises(LookupError):
            apply_action(self.world, plan_delete("acme-dev-raw", "new.txt"))

    def test_directory_lookup_seed_persistence(self):
        self.assertEqual(lookup_user(self.world, "alice")["groups"], ["analysts"])
        with self.assertRaises(DirectoryNotFound):
            lookup_user(self.world, "nobody")
        seed_user(self.world, "carol", ["editors"])
        apply_action(self.world, plan_add_member("carol", "reviewers"))
        persisted = lookup_user(str(self.world), "carol")
        self.assertEqual(persisted["groups"], ["editors", "reviewers"])


if __name__ == "__main__":
    unittest.main()