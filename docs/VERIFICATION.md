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

The dashboard runs locally. [GitHub Actions run 42414862025](https://github.com/llt3055/ticketline-ai-triage/actions/runs/42414862025)
passed all 31 tests, deterministic development evaluation, JavaScript syntax,
Docker image build, and the container health/access-control smoke test on Linux.
The Docker CLI was unavailable on the Windows development machine.

The [public GitHub Pages showcase](https://llt3055.github.io/ticketline-ai-triage/)
hosts screenshots and a recorded deterministic walkthrough. It does not run
the backend or send model requests. Chrome verification confirmed that the page
and screenshot loaded and the 57-second WebM had playable metadata with no
media error. A managed public backend service has not
been provisioned. See `docs/DEMO.md` for deployment configuration and its
persistent-storage and HTTPS requirements.
