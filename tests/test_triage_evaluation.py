"""Offline evaluation-accounting checks; no model requests or holdout tuning."""

import io
import json
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call, patch

import httpx2
from openai import AuthenticationError

import evaluate_triage as evaluator
from triage import TicketTriage


def case(identifier, message, category, urgency):
    return {"id": identifier, "message": message, "category": category, "urgency": urgency}


def prediction(category, urgency, tokens=None):
    usage = None if tokens is None else SimpleNamespace(
        input_tokens=tokens[0], output_tokens=tokens[1], total_tokens=sum(tokens),
    )
    return TicketTriage(category=category, urgency=urgency, summary="Synthetic test response."), usage


class TriageEvaluationTests(unittest.TestCase):
    def test_metrics_include_failures_and_only_messages_reach_predictor(self):
        cases = [
            case("a", "Invoice issue", "billing", "normal"),
            case("b", "Company payments blocked", "billing", "high"),
            case("c", "Application crashes", "technical", "normal"),
            case("d", "Office hours", "other", "low"),
        ]
        predict = Mock(side_effect=[
            prediction("billing", "normal", (12, 3)),
            prediction("technical", "normal", (8, 2)),
            TimeoutError("Simulated timeout"),
            prediction("other", "normal", (4, 1)),
        ])
        ticks = iter([0, 1, 1, 3, 3, 6, 6, 10])
        report = evaluator.evaluate_cases(cases, predict, timer=lambda: next(ticks))
        metrics = report["metrics"]

        self.assertEqual(predict.call_args_list, [call(item["message"]) for item in cases])
        self.assertEqual(metrics["total"], 4)
        self.assertEqual(metrics["successful"], 3)
        self.assertEqual(metrics["failures"], 1)
        self.assertEqual(metrics["unattempted"], 0)
        self.assertEqual(metrics["category"]["accuracy"], 0.5)
        self.assertEqual(metrics["urgency"]["accuracy"], 0.25)
        self.assertEqual(metrics["joint"]["accuracy"], 0.25)
        self.assertEqual(metrics["category"]["confusion_matrix"]["technical"]["__failed__"], 1)
        self.assertEqual(metrics["category"]["per_class"]["billing"]["precision"], 1)
        self.assertEqual(metrics["category"]["per_class"]["billing"]["recall"], 0.5)
        self.assertAlmostEqual(metrics["category"]["macro_f1"], 5 / 9)
        self.assertEqual(report["latency_seconds"]["p50"], 2.5)
        self.assertAlmostEqual(report["latency_seconds"]["p95"], 3.85)
        self.assertEqual(report["token_usage"]["totals_for_responses_with_usage"]["total_tokens"], 30)
        self.assertIsNone(report["cost_usd"])

    def test_authentication_failure_stops_requests_and_keeps_full_denominator(self):
        cases = [
            case("a", "Invoice issue", "billing", "normal"),
            case("b", "Application crashes", "technical", "normal"),
            case("c", "Office hours", "other", "low"),
        ]
        error = AuthenticationError(
            "private error detail must not be saved",
            response=httpx2.Response(401, request=httpx2.Request("POST", "https://example.invalid")),
            body=None,
        )
        predict = Mock(side_effect=error)
        report = evaluator.evaluate_cases(cases, predict)

        predict.assert_called_once_with("Invoice issue")
        self.assertEqual(report["stop_reason"], "authentication_failed")
        self.assertEqual(report["metrics"]["failures"], 1)
        self.assertEqual(report["metrics"]["unattempted"], 2)
        self.assertEqual(report["metrics"]["category"]["total"], 3)
        self.assertEqual(report["metrics"]["category"]["accuracy"], 0)
        self.assertEqual(report["metrics"]["category"]["confusion_matrix"]["other"]["__unattempted__"], 1)
        self.assertEqual(report["latency_seconds"]["sample_count"], 1)
        self.assertNotIn("private error detail", json.dumps(report))

    def test_default_cli_is_simulated_and_never_reads_credentials(self):
        demo_module = ModuleType("triage_demo")
        demo_module.demo_triage = lambda message: prediction("other", "normal")[0]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "demo.json"
            with (
                patch.dict("sys.modules", {"triage_demo": demo_module}),
                patch.object(evaluator, "OpenAI") as create_client,
                patch.object(evaluator, "getpass") as prompt_for_key,
                redirect_stdout(io.StringIO()),
            ):
                result = evaluator.main(["--output", str(destination)])
            report = json.loads(destination.read_text(encoding="utf-8"))

        create_client.assert_not_called()
        prompt_for_key.assert_not_called()
        self.assertEqual(result, 0)
        self.assertEqual(report["mode"], "demo")
        self.assertIn("simulation", report["inference_source"])
        self.assertIsNone(report["model_id"])
        self.assertIsNone(report["prompt_sha256"])
        self.assertIsNone(report["token_usage"]["totals_for_responses_with_usage"])
        self.assertEqual(report["metrics"]["total"], 30)

    def test_live_cli_saves_authentication_failure_report_without_reprompting(self):
        error = AuthenticationError(
            "offline rejection",
            response=httpx2.Response(401, request=httpx2.Request("POST", "https://example.invalid")),
            body=None,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "failure.json"
            with (
                patch.dict("os.environ", {"OPENAI_API_KEY": "offline-dummy-key"}),
                patch.object(evaluator, "OpenAI") as create_client,
                patch.object(evaluator, "getpass") as prompt_for_key,
                patch.object(evaluator, "triage_ticket", side_effect=error) as predict,
                redirect_stdout(io.StringIO()),
            ):
                result = evaluator.main(["--mode", "live", "--output", str(destination)])
            report = json.loads(destination.read_text(encoding="utf-8"))

        prompt_for_key.assert_not_called()
        create_client.return_value.close.assert_called_once()
        self.assertEqual(predict.call_count, 1)
        self.assertEqual(result, 1)
        self.assertEqual(report["run_status"], "stopped_early")
        self.assertEqual(report["metrics"]["failures"], 1)
        self.assertEqual(report["metrics"]["unattempted"], 29)
        self.assertEqual(len(report["dataset"]["sha256"]), 64)
        self.assertEqual(len(report["prompt_sha256"]), 64)
        self.assertNotIn("offline-dummy-key", json.dumps(report))

    def test_datasets_are_separate_balanced_and_valid_without_predicting_holdout(self):
        development = evaluator.load_cases(evaluator.ROOT / "data" / "triage_development.jsonl")
        holdout = evaluator.load_cases(evaluator.ROOT / "data" / "triage_holdout.jsonl")
        for cases in (development, holdout):
            self.assertEqual(len(cases), 30)
            self.assertEqual(Counter(item["category"] for item in cases), {label: 10 for label in evaluator.CATEGORIES})
            self.assertEqual({item["urgency"] for item in cases}, set(evaluator.URGENCIES))
        self.assertFalse({item["message"] for item in development} & {item["message"] for item in holdout})
        self.assertFalse({item["id"] for item in development} & {item["id"] for item in holdout})

    def test_missing_key_records_all_cases_as_unattempted(self):
        cases = [case("a", "Invoice issue", "billing", "normal")]
        predict = Mock()
        report = evaluator.evaluate_cases(cases, predict, initial_stop="missing_api_key")
        predict.assert_not_called()
        self.assertEqual(report["metrics"]["failures"], 0)
        self.assertEqual(report["metrics"]["unattempted"], 1)
        self.assertEqual(report["metrics"]["joint"]["accuracy"], 0)
        self.assertIsNone(report["latency_seconds"]["p50"])


if __name__ == "__main__":
    unittest.main()
