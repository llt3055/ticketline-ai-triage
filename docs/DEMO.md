# Demo guide

Use synthetic examples and run the application locally. The deterministic mode
does not require an API key and makes no external model request. The live mode
requires `OPENAI_API_KEY` to be set in the server environment and requests may
incur charges. Do not display keys or sensitive ticket text in a recording.

## Prepare and run

From the project directory, create an environment and install the project's
dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe run_server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). If the server has a
`TRIAGE_ACCESS_TOKEN` configured, enter that workspace token to sign in; it is
separate from the model API key. Demonstrate submitting a synthetic ticket,
reviewing the suggestion, and correcting it as appropriate.
Explain the difference between a suggestion and a confirmed human decision.
Show what the application does when it cannot classify a ticket; do not present
the example as a measurement of model accuracy.

To run checks in a second terminal:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe evaluate.py
.\.venv\Scripts\python.exe evaluate_triage.py --mode demo --split holdout
```

The original keyword evaluation uses nine hand-written development examples.
The triage evaluation uses a separate set; examine its data and report to
understand its size and limitations. Both commands above run without live API
calls. These small sets do not establish real-world performance, and a demo
mode score is not a live model score. Preserve the holdout set for final
assessment instead of repeatedly tuning on it.

## Container option

With Docker installed, build and run locally:

```powershell
docker build -t ticket-triage .
docker volume create ticket-triage-data
$env:TRIAGE_ACCESS_TOKEN = Read-Host 'Enter a workspace access token'
docker run --rm -p 127.0.0.1:8000:8000 -e TRIAGE_ACCESS_TOKEN -v ticket-triage-data:/app/data ticket-triage
```

The Docker image build and health/access-control smoke test passed in
[GitHub Actions](https://github.com/llt3055/ticketline-ai-triage/actions/runs/42414862025).
Docker was unavailable on the Windows development machine; this container
verification was performed on the CI Linux runner.

The named volume keeps SQLite data between container runs. The container binds
to a non-loopback address internally, so the startup guard requires the token
even though the host port is bound to loopback. Enter this token in the
dashboard when prompted. To use live mode,
set the API key as an environment variable on the host and pass it with
`docker run -e OPENAI_API_KEY ...`; do not put the key into the image or
repository. A shared access token is needed for a non-loopback deployment;
see [ARCHITECTURE.md](ARCHITECTURE.md) for the scope and limitations.

## Suggested short walkthrough

1. State the intended user and the support workflow being demonstrated.
2. Submit a synthetic ticket, inspect the suggestion, and make a correction.
3. Show the relevant automated checks and explain the evaluation set's limits.
4. Describe one failure mode and what you would improve next.

## Optional Render deployment (not yet verified)

The following is a possible way to host a short synthetic-data demo; no Render
service has been created or tested for this project. Render web services are
publicly reachable, so use a strong workspace token and do not use confidential
data. The shared token is not a production-grade identity system.

1. After the repository is available, create a Render web service from it and
   choose the Docker runtime. Review the selected plan and charges before
   creating the service.
2. Set `TRIAGE_ACCESS_TOKEN` as a secret environment variable and set
   `TRIAGE_EXTERNAL_ORIGIN` to the exact public HTTPS origin, such as
   `https://your-service.onrender.com`, without a trailing slash or path.
   Set the Docker Command to
   `/bin/sh -c 'export TRIAGE_PORT="$PORT"; exec python run_server.py'`.
   The image sets `TRIAGE_HOST=0.0.0.0`. Leave `OPENAI_API_KEY` unset for the
   deterministic demo; live API requests can incur provider charges.
3. Set the health-check path to `/health`. Test login, ticket creation, review,
   and export over HTTPS before sharing any link. Render terminates HTTPS at a
   proxy; the configured external origin is used for same-origin checks and
   secure cookies. If login or changes fail, check the exact origin and hosting
   configuration before sharing.
4. Render's free service filesystem is ephemeral: SQLite data can disappear on
   restarts, redeploys, or spin-down. A persistent disk requires a paid service;
   the app remains a single-instance demonstration and does not automatically
   switch to Postgres. See Render's [web-service documentation](https://render.com/docs/web-services)
   and [free-tier limitations](https://render.com/docs/free).

This guide does not assert that a public deployment, a live evaluation, or user
adoption exists.
