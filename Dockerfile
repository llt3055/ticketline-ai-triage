FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRIAGE_DB_PATH=/app/data/app.db \
    TRIAGE_HOST=0.0.0.0 \
    TRIAGE_PORT=8000

WORKDIR /app
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown appuser:appuser /app/data

COPY --chown=appuser:appuser . .
USER appuser
VOLUME ["/app/data"]
EXPOSE 8000
CMD ["python", "run_server.py"]
