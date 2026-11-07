# Structured triage evaluation

This evaluator measures category and urgency predictions under the policy in
`triage.py`. It does not grade summary accuracy, prove customer value, or establish
production readiness. The earlier category-only `9/9` screenshot remains a
historical observation on nine development examples; it is not a result for this
new prompt or the new holdout.

## Three explicit modes

Run commands from the repository folder. The examples below use the Windows
virtual environment; on other systems use the equivalent Python interpreter.

```powershell
.\.venv\Scripts\python.exe .\evaluate_triage.py
.\.venv\Scripts\python.exe .\evaluate_triage.py --mode rules
.\.venv\Scripts\python.exe .\evaluate_triage.py --mode live
```

- `demo` is the default. It calls a deterministic simulation and sends no model
  requests. A good demo score would be evidence only about that simulation.
- `rules` uses the original keyword category baseline. It always assigns urgency
  `normal`; that is an intentionally weak constant baseline, not inferred urgency.
  Its summary merely repeats the input and is not evaluated.
- `live` calls the hosted model named in `classifier.py`. It reads
  `OPENAI_API_KEY` if configured, otherwise prompts once with hidden input. It
  sends at most one request per attempted example with automatic retries disabled.
  Each request may incur API charges. Never save a real key in the repository.

The default split is `development`. Default JSON destinations are
`reports/triage-MODE-SPLIT.json`, for example
`reports/triage-demo-development.json`. Use `--output PATH` to preserve separate
runs instead of overwriting the default report. A report contains the synthetic
ticket text, expected labels, predictions, and failure states.

## Dataset meaning and holdout discipline

`data/triage_development.jsonl` and `data/triage_holdout.jsonl` each contain 30
synthetic examples: ten per category, with low/normal/high urgency represented.
They were authored for this exercise and manually checked against the written
teaching policy. They are not customer data, independently annotated research
data, or a validated representation of real support traffic. Urgency is not
balanced, and this policy does not cover every possible business escalation.

Use development examples to inspect mistakes and improve the implementation.
The holdout has separate messages and scenarios. Freeze the prompt, rules, and
implementation before evaluating it:

```powershell
.\.venv\Scripts\python.exe .\evaluate_triage.py --mode live --split holdout --output reports/triage-live-holdout-run-01.json
```

Do not inspect holdout mistakes and then continue to claim it as an untouched
final test while tuning against them. After using it to guide changes, treat it
as development evidence and create a genuinely new evaluation set for a final
comparison. Keep existing results and dataset versions. The report hashes the
dataset bytes so changes are visible. These files are visible to repository
readers; this is a learning holdout, not an externally blinded benchmark.

## What the report measures

- **Category accuracy:** correct categories divided by all dataset examples.
- **Urgency accuracy:** correct urgency labels divided by all examples.
- **Joint accuracy:** examples where both labels are correct divided by all
  examples. Matching structure or writing a plausible summary does not count
  as a correct label.
- **Per-class precision:** correct predictions for a label divided by all
  predictions of that label.
- **Per-class recall:** correct predictions for a label divided by all examples
  whose expected label is that label, including failures and unattempted cases.
- **F1:** the harmonic mean of precision and recall. Undefined per-class values
  are reported as zero. Macro metrics average all three defined labels equally,
  including a label that has no predictions.
- **Confusion matrices:** rows are expected labels; columns are predicted labels,
  plus explicit `__failed__` and `__unattempted__` columns.

A prediction error is retained as a failed row, never silently removed from the
accuracy denominator. Other examples continue after ordinary prediction errors.
Authentication failure stops further requests; the rejected attempt is failed
and the remaining cases are unattempted. Missing credentials create a report with
every case unattempted. The report therefore distinguishes inability to run the
evaluation from a model's incorrect answer. Interpret the failure counts alongside
the full-denominator score; an authentication failure is not evidence of poor model
classification. Interrupting an in-progress prediction also retains partial results.

The program saves error types and HTTP status, not arbitrary exception messages
that could contain credentials or sensitive server text. A successful CLI exit
means every prediction completed, not that the scores passed a quality threshold.
Runs with failed or unattempted cases exit with status 1 after saving the report.

## Latency, usage, versions, and limits

Latency is measured around each attempted prediction call. It includes failed
attempts but excludes client setup, dataset loading, report writing, and unattempted
cases. P50/P95 use linear interpolation at `(n - 1) * p`. Thirty observations are
too few for a robust production latency claim. Local demo latency must not be
presented as hosted-model performance.

Token totals include only responses that returned usage. Missing usage and failed
requests do not imply zero billing. `cost_usd` remains `null` because no verified
price schedule has been supplied. Consult actual provider usage and billing for
financial reporting; no dollar savings are inferred here.

Reports include UTC start/end timestamps, dataset hash, implementation hashes,
the configured live model identifier, and the live prompt hash. Demo/rules model
and prompt fields are `null` because they use no model prompt. The current live
identifier is an alias, not an immutable model snapshot. There are no fabricated
confidence values. A single run does not establish repeated-run consistency.

The offline test suite checks metric accounting, failure handling, free default
mode, report persistence, and dataset shape. It does not call a model, and it does
not evaluate or tune the holdout predictions.
