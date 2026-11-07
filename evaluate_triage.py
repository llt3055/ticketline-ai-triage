"""Evaluate structured triage on fixed synthetic data; demo mode is free."""

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path
from time import perf_counter

from openai import AuthenticationError, OpenAI

from classifier import MODEL_NAME
from ticket_classifier import classify
from triage import TRIAGE_INSTRUCTIONS, TicketTriage, triage_ticket

ROOT = Path(__file__).resolve().parent
CATEGORIES = ("billing", "technical", "other")
URGENCIES = ("low", "normal", "high")


def load_cases(path):
    """Load and validate data before any optional paid request is made."""
    cases = []
    seen = set()
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        if not isinstance(case, dict):
            raise ValueError(f"Line {line_number}: expected an object.")
        if not isinstance(case.get("id"), str) or not case["id"] or case["id"] in seen:
            raise ValueError(f"Line {line_number}: expected a unique, nonempty id.")
        if not isinstance(case.get("message"), str) or not case["message"].strip():
            raise ValueError(f"Line {line_number}: expected a nonempty message.")
        if case.get("category") not in CATEGORIES or case.get("urgency") not in URGENCIES:
            raise ValueError(f"Line {line_number}: invalid expected label.")
        seen.add(case["id"])
        cases.append(case)
    if not cases:
        raise ValueError("An evaluation dataset must contain at least one example.")
    return cases


def percentile(values, fraction):
    """Linear interpolation between sorted observations; None for no attempts."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def label_metrics(results, field, labels):
    """Failures have no predicted class and remain false negatives."""
    columns = (*labels, "__failed__", "__unattempted__")
    confusion = {label: {column: 0 for column in columns} for label in labels}
    for result in results:
        actual = result["expected"][field]
        predicted = (
            result["prediction"][field]
            if result["status"] == "success"
            else "__failed__" if result["status"] == "failed" else "__unattempted__"
        )
        confusion[actual][predicted] += 1

    per_class = {}
    correct = 0
    for label in labels:
        true_positive = confusion[label][label]
        support = sum(confusion[label].values())
        predicted_count = sum(confusion[actual][label] for actual in labels)
        precision = true_positive / predicted_count if predicted_count else 0.0
        recall = true_positive / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {
            "precision": precision, "recall": recall, "f1": f1, "support": support,
        }
        correct += true_positive

    return {
        "correct": correct,
        "total": len(results),
        "accuracy": correct / len(results) if results else None,
        "per_class": per_class,
        "macro_precision": sum(item["precision"] for item in per_class.values()) / len(labels),
        "macro_recall": sum(item["recall"] for item in per_class.values()) / len(labels),
        "macro_f1": sum(item["f1"] for item in per_class.values()) / len(labels),
        "confusion_matrix": confusion,
        "confusion_matrix_orientation": "rows=expected; columns=predicted or failure status",
        "zero_denominator_policy": "Per-class precision/recall/F1 are 0 when undefined; macro uses all labels.",
    }


def usage_values(usage):
    if usage is None:
        return None
    values = {name: getattr(usage, name, None) for name in ("input_tokens", "output_tokens", "total_tokens")}
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values.values()):
        return None
    return values


def evaluate_cases(cases, predict, *, timer=None, initial_stop=None):
    """Run one prediction per message, retaining all failed/unattempted rows."""
    if not cases:
        raise ValueError("An evaluation requires at least one case.")
    timer = timer or perf_counter
    results = []
    stop_reason = initial_stop

    for case in cases:
        row = {
            "id": case["id"],
            "message": case["message"],
            "expected": {"category": case["category"], "urgency": case["urgency"]},
            "prediction": None,
            "latency_seconds": None,
            "token_usage": None,
            "error": None,
        }
        if stop_reason:
            row.update(status="unattempted", error={"reason": stop_reason})
            results.append(row)
            continue

        started = timer()
        try:
            prediction, usage = predict(case["message"])
            if not isinstance(prediction, TicketTriage):
                raise TypeError("Predictor must return a validated TicketTriage object.")
            row.update(status="success", prediction=prediction.model_dump(), token_usage=usage_values(usage))
        except KeyboardInterrupt:
            row.update(status="failed", error={"type": "KeyboardInterrupt", "reason": "interrupted"})
            stop_reason = "interrupted"
        except Exception as error:
            # Save type/status, not arbitrary server text that might contain secrets.
            status = getattr(error, "status_code", None)
            authentication_failed = isinstance(error, AuthenticationError) or status == 401
            row.update(status="failed", error={
                "type": type(error).__name__,
                "http_status": status if isinstance(status, int) else None,
                "reason": "authentication_failed" if authentication_failed else "prediction_failed",
            })
            if authentication_failed:
                stop_reason = "authentication_failed"
        finally:
            row["latency_seconds"] = max(0.0, timer() - started)
        results.append(row)

    attempted = [row for row in results if row["status"] != "unattempted"]
    succeeded = [row for row in results if row["status"] == "success"]
    failures = sum(row["status"] == "failed" for row in results)
    latencies = [row["latency_seconds"] for row in attempted]
    known_usage = [row["token_usage"] for row in results if row["token_usage"] is not None]
    joint_correct = sum(
        row["prediction"]["category"] == row["expected"]["category"]
        and row["prediction"]["urgency"] == row["expected"]["urgency"]
        for row in succeeded
    )
    return {
        "metrics": {
            "total": len(results), "attempted": len(attempted), "successful": len(succeeded),
            "failures": failures, "unattempted": len(results) - len(attempted),
            "category": label_metrics(results, "category", CATEGORIES),
            "urgency": label_metrics(results, "urgency", URGENCIES),
            "joint": {"correct": joint_correct, "total": len(results), "accuracy": joint_correct / len(results)},
        },
        "latency_seconds": {
            "scope": "Attempted prediction calls, including failures; excludes unattempted cases and setup.",
            "sample_count": len(latencies),
            "p50": percentile(latencies, 0.50), "p95": percentile(latencies, 0.95),
            "percentile_method": "linear interpolation at (n-1)*p",
        },
        "token_usage": {
            "responses_with_usage": len(known_usage),
            "successful_responses_without_usage": len(succeeded) - len(known_usage),
            "totals_for_responses_with_usage": {
                name: sum(item[name] for item in known_usage)
                for name in ("input_tokens", "output_tokens", "total_tokens")
            } if known_usage else None,
            "note": "Only returned usage is counted. Missing usage or failed requests does not imply zero billing.",
        },
        "cost_usd": None,
        "cost_note": "Not calculated: no explicit verified price schedule is supplied.",
        "stop_reason": stop_reason,
        "results": results,
    }


def sha256_bytes(content):
    return hashlib.sha256(content).hexdigest()


def metadata(mode, split, path):
    source_names = {
        "demo": ("triage_demo.py", "triage.py"),
        "live": ("triage.py", "classifier.py"),
        "rules": ("ticket_classifier.py", "evaluate_triage.py"),
    }[mode]
    return {
        "report_schema_version": 1,
        "mode": mode,
        "inference_source": {
            "demo": "Deterministic simulation; no model inference or model-quality claim.",
            "rules": "Keyword category baseline; urgency is always normal, not inferred.",
            "live": "Hosted model inference through the OpenAI API.",
        }[mode],
        "model_id": MODEL_NAME if mode == "live" else None,
        "model_version_note": "Model alias, not an immutable model snapshot." if mode == "live" else "No AI model used.",
        "prompt_sha256": sha256_bytes(TRIAGE_INSTRUCTIONS.encode("utf-8")) if mode == "live" else None,
        "teaching_policy_sha256": sha256_bytes(TRIAGE_INSTRUCTIONS.encode("utf-8")),
        "implementation_sha256": {
            name: sha256_bytes((ROOT / name).read_bytes())
            for name in source_names if (ROOT / name).is_file()
        },
        "dataset": {
            "file": path.name, "split": split,
            "sha256": sha256_bytes(path.read_bytes()),
            "source": "Manually reviewed synthetic teaching examples; not customer data.",
            "note": "Fixed separate holdout; do not tune on its cases." if split == "holdout" else "Development examples may be inspected during improvement.",
        },
        "limitations": [
            "Small synthetic dataset; does not establish real-world or production performance.",
            "Urgency follows this project's teaching policy, not a validated support organization policy.",
            "Summary correctness is not evaluated by category/urgency metrics.",
            "A single run does not establish repeated-run reliability or operational latency guarantees.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("demo", "live", "rules"), default="demo")
    parser.add_argument("--split", choices=("development", "holdout"), default="development")
    parser.add_argument("--output", type=Path, help="JSON report destination; default reports/triage-MODE-SPLIT.json")
    args = parser.parse_args(argv)
    dataset_path = ROOT / "data" / f"triage_{args.split}.jsonl"
    cases = load_cases(dataset_path)
    output_path = args.output or ROOT / "reports" / f"triage-{args.mode}-{args.split}.json"
    report = metadata(args.mode, args.split, dataset_path)
    report["started_at_utc"] = datetime.now(timezone.utc).isoformat()
    client = None
    initial_stop = None
    predict = None

    print(f"Mode: {args.mode}. Split: {args.split}. Examples: {len(cases)}.")
    if args.mode == "live":
        print(f"Up to {len(cases)} paid API requests. No automatic retries. Authentication failure stops the run.")
        try:
            api_key = os.environ.get("OPENAI_API_KEY", "").strip() or getpass("OpenAI API key (hidden): ").strip()
            if not api_key:
                initial_stop = "missing_api_key"
            else:
                client = OpenAI(api_key=api_key, timeout=30.0, max_retries=0)
                predict = lambda message: triage_ticket(message, client)
        except (Exception, KeyboardInterrupt) as error:
            initial_stop = "interrupted" if isinstance(error, KeyboardInterrupt) else "client_setup_failed"
    elif args.mode == "demo":
        from triage_demo import demo_triage
        predict = lambda message: (demo_triage(message), None)
        print("SIMULATION: deterministic demo output, not a model evaluation.")
    else:
        predict = lambda message: (
            TicketTriage(category=classify(message), urgency="normal", summary=message), None,
        )
        print("BASELINE: keyword category; urgency always normal. No AI requests.")

    try:
        report.update(evaluate_cases(cases, predict, initial_stop=initial_stop))
    finally:
        if client is not None:
            client.close()
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["run_status"] = (
        "completed" if report["metrics"]["failures"] == 0 and report["metrics"]["unattempted"] == 0
        else "completed_with_failures" if report["metrics"]["unattempted"] == 0 else "stopped_early"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for field in ("category", "urgency", "joint"):
        item = report["metrics"][field]
        print(f"{field.capitalize()} accuracy: {item['correct']}/{item['total']} ({item['accuracy']:.1%})")
    print(f"Failed: {report['metrics']['failures']}; unattempted: {report['metrics']['unattempted']}.")
    print(f"Report: {output_path}")
    return 0 if report["run_status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
