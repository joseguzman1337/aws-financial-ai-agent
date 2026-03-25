"""Live regression checks for notebook-required runtime responses."""

import os
import unittest

from notebook_flow import bootstrap_guest_credentials, invoke_query


class NotebookLiveE2ETests(unittest.TestCase):
    """Live tests that mirror notebook invocation behavior."""

    REGION = "us-east-1"
    IDENTITY_POOL_ID = "us-east-1:c7680c24-fe96-4358-b305-6f43de1ca6c8"
    UNAUTH_ROLE_ARN = "arn:aws:iam::162187491349:role/cognito_unauthenticated_role"
    AGENT_ARN = (
        "arn:aws:bedrock-agentcore:us-east-1:162187491349:"
        "runtime/Financial_Analyst_Agent-hvRgckAqaW"
    )

    @classmethod
    def setUpClass(cls):
        if os.environ.get("RUN_NOTEBOOK_LIVE_E2E") != "1":
            raise unittest.SkipTest("Set RUN_NOTEBOOK_LIVE_E2E=1 for live tests")
        bootstrap_guest_credentials(
            cls.REGION, cls.IDENTITY_POOL_ID, cls.UNAUTH_ROLE_ARN
        )

    def test_required_prompt_returns_non_empty_response(self):
        ok, text = invoke_query(
            self.REGION,
            self.AGENT_ARN,
            "What is the stock price for Amazon right now?",
        )
        self.assertTrue(ok, text)
        self.assertGreater(len(text), 10)


if __name__ == "__main__":
    unittest.main()
