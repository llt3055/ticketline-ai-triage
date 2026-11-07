# Architecture and operating scope

This is a learning and portfolio application for a single operator reviewing
support-ticket triage suggestions. It is not a multi-tenant support platform.
It stores local demonstration data in SQLite; use synthetic tickets rather
than confidential customer data for a public demonstration.

## Components and flow

```text
static/index.html + app.js + styles.css
                │ same-origin HTTP
                ▼
        app.py (FastAPI API)
           ├─ triage_demo.py: deterministic rules
           ├─ triage.py: validated live model output ──► model API
           └─ storage.py ──► SQLite tickets + activity events

evaluate_triage.py ──► synthetic labeled sets ──► JSON evaluation report
```

1. The browser dashboard provides the interface to submit and review tickets.
2. A Python FastAPI application handles requests, applies validation, and
   coordinates classification and persistence.
3. SQLite stores the local application's data. `TRIAGE_DB_PATH` configures
   its path; the default is `data/app.db`.
4. A deterministic demonstration mode runs without an external model API.
   Live model mode uses `OPENAI_API_KEY` on the server and may incur charges.
   The browser does not collect the model API key.

Model output is a suggestion: structural validation alone does not establish
that the classification is correct. Review and correction by a person remain
part of the workflow. A failure or unknown result should not be treated as
evidence that a ticket is safe or resolved.

The API exposes ticket creation, listing, details, review and retry; summary
stats; sample-ticket seeding; and CSV export. `/health` and `/api/config` are
public. When configured, the shared-token gate protects ticket, stats, seed,
and export endpoints. The export escapes spreadsheet formula prefixes, but
is subject to the application export limit; the UI lists only a limited number
of recent tickets. Check the README for current limits.

## Data and access

An optional `TRIAGE_ACCESS_TOKEN` adds a shared-token gate. The dashboard
accepts the workspace token and creates a session using an HttpOnly,
SameSite=Strict cookie. API clients may instead use the `X-Access-Token`
request header. This shared token is separate from the server's model API key;
it is not individual user authentication, role-based authorization, or tenant
isolation. For a non-loopback deployment, configure the token, serve over HTTPS
using an appropriate reverse proxy, and restrict access to trusted users. Do
not expose the application to the public internet as a production service.
Store secrets in the server environment, not in Git or a demo recording.
The `run_server.py` entry point refuses to listen on a non-loopback host without
the workspace token. Use this entry point for deployment; starting Uvicorn
directly bypasses that startup check. Behind an HTTPS-terminating proxy, set
`TRIAGE_EXTERNAL_ORIGIN` to the exact public HTTPS origin so mutation origin
checks and cookie security reflect the browser-facing address. Do not set it
from an untrusted request or assume arbitrary forwarded headers are trusted.

SQLite is a single-host database. Its file persists only if the configured
directory persists; back it up separately if the data matters. The supplied
Dockerfile runs as a non-root user and uses `/app/data` as its storage location.
When using a bind mount, ensure that the container user (UID 10001) can write
the mounted directory. No high availability, multi-user concurrency, or backup
guarantees are claimed.

## Quality and evaluation

Run the offline tests and deterministic evaluation as described in the README
and demo guide. A passing software test checks the behavior it covers, not
overall model quality. The triage evaluator includes separate synthetic
development and holdout sets; neither represents real customer traffic or a
validated benchmark. See [PORTFOLIO.md](PORTFOLIO.md) and the reports for
results and failure analysis. Do not infer live accuracy, production usage,
or business impact from the deterministic demo.
