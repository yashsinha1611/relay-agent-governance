"""Environment/zone/operation/approval matrix over typed tools and policy."""

import unittest

from relay.policy import evaluate
from relay.tools import storage as storetools
from shared.schemas import Action


class MatrixTests(unittest.TestCase):
    def test_environment_zone_matrix(self):
        for env in ("dev", "test", "staging", "prod"):
            for zone in ("raw", "curated", "archive"):
                action = storetools.plan_upload(f"acme-{env}-{zone}", "k.txt", "v")
                self.assertEqual(action.environment, env)
        for bad in ("acme-qa-raw", "acme-dev-tmp", "ACME-dev-raw", ""):
            with self.assertRaises(storetools.InvalidName):
                storetools.parse_bucket(bad)

    def test_approval_matrix(self):
        prod = [Action(operation="upload", target="acme-prod-curated", path="k", content="v", environment="prod")]
        delete = [Action(operation="delete", target="acme-dev-raw", path="k", environment="dev")]
        owner = [{"approver": "amy", "role": "data_owner", "approved": True}]
        two = [{"approver": "a", "approved": True}, {"approver": "b", "approved": True}]
        self.assertEqual(evaluate(prod, [], "amy")["decision"], "paused")
        self.assertEqual(evaluate(prod, owner, "zed")["decision"], "approved")
        self.assertEqual(evaluate(delete, two, "zed")["decision"], "approved")
        self.assertEqual(evaluate(delete, two[:1], "zed")["decision"], "blocked")
        self.assertEqual(evaluate(prod, owner, "amy")["decision"], "escalated")


if __name__ == "__main__":
    unittest.main()