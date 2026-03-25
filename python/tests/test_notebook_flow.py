"""Regression tests for notebook flow helpers (fast, no live AWS calls)."""

import unittest

from notebook_flow import build_agentcore_url, event_text


class NotebookFlowUnitTests(unittest.TestCase):
    """Unit-level regression checks for notebook helper behavior."""

    def test_build_agentcore_url_encodes_runtime_arn(self):
        arn = (
            "arn:aws:bedrock-agentcore:us-east-1:123456789012:"
            "runtime/Financial_Analyst_Agent-abc123"
        )
        url = build_agentcore_url("us-east-1", arn)
        self.assertIn("bedrock-agentcore.us-east-1.amazonaws.com", url)
        self.assertIn("arn%3Aaws%3Abedrock-agentcore", url)
        self.assertTrue(url.endswith("/invocations"))

    def test_event_text_str(self):
        self.assertEqual(event_text("hello"), "hello")

    def test_event_text_list_blocks(self):
        event = [
            {"type": "text", "text": "hello"},
            {"type": "text", "text": " world"},
        ]
        self.assertEqual(event_text(event), "hello world")

    def test_event_text_nested_dict(self):
        event = {"content": [{"type": "text", "text": "nested"}]}
        self.assertEqual(event_text(event), "nested")


if __name__ == "__main__":
    unittest.main()
