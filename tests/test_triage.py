"""Offline checks for structured triage, including the real SDK parser."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import httpx2
from openai import OpenAI

from triage import TicketTriage, triage_ticket


class TriageTests(unittest.TestCase):
    def test_real_sdk_sends_schema_and_parses_structured_response(self):
        message = "Our entire team cannot sign in to answer customer tickets."
        expected = {
            "category": "technical",
            "urgency": "high",
            "summary": "The entire team cannot sign in to answer customer tickets.",
        }
        sent_requests = []

        def respond(request):
            payload = json.loads(request.content)
            sent_requests.append(payload)
            return httpx2.Response(
                200,
                json={
                    "id": "resp_offline_test",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "error": None,
                    "incomplete_details": None,
                    "model": payload["model"],
                    "output": [
                        {
                            "id": "msg_offline_test",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(expected),
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                    "parallel_tool_calls": False,
                    "tool_choice": "auto",
                    "tools": [],
                    "usage": {
                        "input_tokens": 30,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens": 15,
                        "output_tokens_details": {"reasoning_tokens": 0},
                        "total_tokens": 45,
                    },
                },
            )

        transport = httpx2.MockTransport(respond)
        with OpenAI(
            api_key="offline-test-key-not-a-secret",
            base_url="https://example.invalid/v1",
            http_client=httpx2.Client(transport=transport),
            max_retries=0,
        ) as client:
            result, usage = triage_ticket(message, client)

        self.assertEqual(len(sent_requests), 1)
        self.assertEqual(sent_requests[0]["input"], message)
        self.assertEqual(sent_requests[0]["text"]["format"]["type"], "json_schema")
        self.assertIsInstance(result, TicketTriage)
        self.assertEqual(result.category, expected["category"])
        self.assertEqual(result.urgency, expected["urgency"])
        self.assertEqual(result.summary, expected["summary"])
        self.assertEqual(usage.total_tokens, 45)

    def test_incomplete_or_missing_parsed_response_is_rejected(self):
        for status in ("incomplete", "completed"):
            with self.subTest(status=status):
                client = Mock()
                client.responses.parse.return_value = SimpleNamespace(
                    status=status,
                    output_parsed=None,
                    output=[],
                    error=None,
                    incomplete_details=None,
                )

                with self.assertRaises(RuntimeError):
                    triage_ticket("I was charged twice.", client)

    def test_empty_ticket_is_rejected_before_request(self):
        for message in ("", "   ", "\n\t"):
            with self.subTest(message=repr(message)):
                client = Mock()

                with self.assertRaises(ValueError):
                    triage_ticket(message, client)

                client.responses.parse.assert_not_called()


if __name__ == "__main__":
    unittest.main()
