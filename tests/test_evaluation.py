"""Offline checks for the classifier and development evaluation workflow."""

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import evaluate as evaluation
from classifier import classify_ticket


class EvaluationTests(unittest.TestCase):
    def test_default_mode_is_free_and_reports_baseline_result(self):
        output = io.StringIO()

        with (
            patch("evaluate.OpenAI") as create_client,
            patch("evaluate.getpass") as prompt_for_key,
            redirect_stdout(output),
        ):
            evaluation.main([])

        create_client.assert_not_called()
        prompt_for_key.assert_not_called()
        self.assertIn("Accuracy on development examples: 6/9", output.getvalue())

    def test_model_category_is_normalized_and_unknown_category_is_rejected(self):
        client = Mock()
        response = SimpleNamespace(
            status="completed",
            output_text=" Technical\n",
            usage=SimpleNamespace(input_tokens=12, output_tokens=2, total_tokens=14),
        )
        client.responses.create.return_value = response

        category, _usage = classify_ticket("I cannot access my account.", client)
        self.assertEqual(category, "technical")

        response.output_text = "urgent"
        with self.assertRaises(ValueError):
            classify_ticket("I cannot access my account.", client)

    def test_evaluation_counts_matches_and_passes_only_messages(self):
        tickets = [
            ("Please resend my invoice.", "billing"),
            ("The app will not open.", "technical"),
            ("When is your office open?", "other"),
        ]
        predict = Mock(side_effect=["billing", "other", "other"])
        output = io.StringIO()

        with redirect_stdout(output):
            correct = evaluation.evaluate(predict, tickets)

        self.assertEqual(correct, 2)
        self.assertEqual(
            predict.call_args_list,
            [call("Please resend my invoice."),
             call("The app will not open."),
             call("When is your office open?")],
        )
        self.assertIn("Accuracy on development examples: 2/3", output.getvalue())

    def test_prediction_failure_does_not_print_completed_accuracy(self):
        tickets = [
            ("Please resend my invoice.", "billing"),
            ("The app will not open.", "technical"),
        ]
        predict = Mock(side_effect=["billing", RuntimeError("Request failed")])
        output = io.StringIO()

        with redirect_stdout(output):
            with self.assertRaisesRegex(RuntimeError, "Request failed"):
                evaluation.evaluate(predict, tickets)

        self.assertNotIn("Accuracy on development examples:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
