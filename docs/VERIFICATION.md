# Verification record

Observed 2026-11-07 during completion of the application.

## Local software verification

- Python 3.13.9 and the committed locked dependencies.
- `python -m unittest discover -s tests -v`: **31 tests passed**.
- `python -m pip check`: no broken requirements.
- `node --check static/app.js` and `node --check static/api-docs.js`: passed.
- Real Chrome browser: created a demo ticket, corrected its summary, approved it,
  filtered the inbox, refreshed and observed persistence, imported four CSV
  tickets, downloaded CSV, checked workspace sign-in/sign-out, opened the local
  API reference, and inspected desktop/mobile rendering.
- The browser walkthrough uses deterministic demo mode and contains no provider
  credential or model-quality claim. Media is under `docs/assets/`.

## Evaluation evidence

Four saved reports compare deterministic demo and keyword baselines on the
30-case development and 30-case separate holdout sets. The holdout was run
without changing the rules afterward. These reports are evidence about those
baselines on synthetic examples only. Category and urgency are scored;
summary correctness is not scored. See `docs/EVALUATION.md` and `reports/`.

No live structured holdout evaluation was executed because this build process
had no provider API key. The older 9/9 category development observation is
retained separately, attributed to the user's terminal screenshot.

## Deployment scope

The dashboard runs locally. A GitHub CI pipeline checks tests, deterministic
development evaluation, JavaScript syntax and a Docker health/auth smoke test.
The Docker CLI was unavailable on the development machine, so container
verification depends on that remote CI result. A managed public cloud service
has not been provisioned. See `docs/DEMO.md` for deployment configuration and
its persistent-storage and HTTPS requirements.
