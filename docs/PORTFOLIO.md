# Portfolio notes: Ticketline

Ticketline is a single-operator support-ticket triage demonstration. A user can
submit a synthetic request, inspect a suggested category, urgency, and summary,
correct or approve it, view its activity history, and export tickets as CSV. A
Python/FastAPI backend stores tickets and events in SQLite; the browser uses
plain HTML, CSS, and JavaScript. There is a deterministic demo mode and an
optional live model mode configured on the server.

## Evidence in this repository

- Offline unit and API checks run with `python -m unittest discover -s tests -v`.
- A separate evaluation harness compares category, urgency, and their joint
  correctness against labeled synthetic examples. It saves per-case results,
  confusion matrices, and source hashes in `reports/`.
- On the 30-case development set, deterministic demo mode scored 25/30 for
  category, 19/30 for urgency, and 16/30 for both together.
- On the separate 30-case synthetic holdout, the same demo mode scored 23/30
  for category, 13/30 for urgency, and 8/30 for both. The simpler rules
  baseline scored 13/30, 13/30, and 4/30 respectively. See
  [demo holdout report](../reports/triage-demo-holdout.json) and
  [rules holdout report](../reports/triage-rules-holdout.json).
- The demo mode is deterministic rules, not AI inference. Its holdout urgency
  results included zero correct predictions among five high-urgency examples;
  this is an important failure for any real support workflow. The small,
  synthetic data and project-specific urgency policy do not establish real-world
  accuracy. Summary quality was not scored by these metrics.
- The current structured live model has not been evaluated on the holdout set.
  A previous user-observed 9/9 category result used an older prompt and nine
  development examples, not the current triage workflow or its holdout.

## Resume wording

Use a bullet like the following only if it accurately reflects work you can
personally explain, and adjust it to identify your contribution:

> Built a support-ticket triage demo using Python, FastAPI, SQLite, and a review
> dashboard; added a labeled evaluation harness and measured category and
> urgency results on synthetic development and holdout examples.

Be prepared to explain the access model, the difference between demo and live
mode, how the evaluation was designed, and the high-urgency failure above. A
personal project does not demonstrate enterprise deployment, user adoption,
business impact, or live-model performance unless those are independently
verified. Add a repository or demo link only after it exists.
