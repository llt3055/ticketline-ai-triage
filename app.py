"""Single-operator support triage web application."""

from contextlib import asynccontextmanager
import csv
import io
import hashlib
import logging
import os
from pathlib import Path
import secrets
import threading
from time import perf_counter
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import APIError, OpenAI
from pydantic import BaseModel, ConfigDict, Field, field_validator

from classifier import MODEL_NAME
from storage import TicketStore
from triage import TicketTriage, triage_ticket
from triage_demo import demo_triage

ROOT = Path(__file__).resolve().parent
logger = logging.getLogger("triage")


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=5000)
    mode: Literal["demo", "live"] = "demo"

    @field_validator("message")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Ticket message cannot be blank.")
        return value.strip()


class TicketReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["billing", "technical", "other"]
    urgency: Literal["low", "normal", "high"]
    summary: str = Field(min_length=1, max_length=1000)
    review_status: Literal["pending", "approved"] = "pending"

    @field_validator("summary")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Summary cannot be blank.")
        return value.strip()


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["demo", "live"] = "demo"


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=1024)


class TicketImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv: str = Field(min_length=1, max_length=60000)
    mode: Literal["demo", "live"] = "demo"


def create_app(db_path=None, live_runner=None, access_token=None, api_key=None):
    store = TicketStore(db_path or os.environ.get("TRIAGE_DB_PATH", ROOT / "data" / "app.db"))
    workspace_token = os.environ.get("TRIAGE_ACCESS_TOKEN", "") if access_token is None else access_token
    session_value = hashlib.sha256(workspace_token.encode("utf-8")).hexdigest()
    provider_key = os.environ.get("OPENAI_API_KEY", "") if api_key is None else api_key
    live_available = bool(provider_key or live_runner)
    external_origin = os.environ.get("TRIAGE_EXTERNAL_ORIGIN", "").rstrip("/")
    if external_origin:
        parsed = urlsplit(external_origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("TRIAGE_EXTERNAL_ORIGIN must be an http(s) origin without a path.")

    @asynccontextmanager
    async def lifespan(application):
        store.initialize()
        yield

    application = FastAPI(title="Ticketline — Support triage", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    application.state.store = store
    seed_lock = threading.Lock()

    @application.middleware("http")
    async def request_guards(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != (external_origin or str(request.base_url).rstrip("/")):
                return JSONResponse({"detail": "Cross-origin changes are not allowed."}, status_code=403)
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > 64000):
                return JSONResponse({"detail": "Request body is too large."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response

    def authorized(request: Request):
        if workspace_token:
            scheme, _, bearer = request.headers.get("Authorization", "").partition(" ")
            supplied = request.headers.get("X-Access-Token") or (bearer if scheme.casefold() == "bearer" else "")
            expected = workspace_token if supplied else session_value
            supplied = supplied or request.cookies.get("triage_session", "")
            if not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
                raise HTTPException(401, "Workspace access token required.")

    def find(ticket_id):
        ticket = store.get(ticket_id)
        if ticket is None:
            raise HTTPException(404, "Ticket not found.")
        return ticket

    def check_mode(mode):
        if mode == "live" and not live_available:
            raise HTTPException(503, "Live AI is not configured. Set OPENAI_API_KEY on the server or use demo mode.")

    def run_triage(ticket_id, message, mode):
        started = perf_counter()
        try:
            if mode == "demo":
                result, usage = demo_triage(message), None
            elif live_runner is not None:
                result, usage = live_runner(message)
            else:
                with OpenAI(api_key=provider_key, timeout=30.0, max_retries=0) as client:
                    result, usage = triage_ticket(message, client)
            # Validate even injected provider implementations before persistence.
            result = TicketTriage.model_validate(result)
            if not result.summary.strip() or len(result.summary) > 1000:
                raise ValueError("Summary is blank or too long.")
            store.complete(ticket_id, result, (perf_counter() - started) * 1000, usage)
        except Exception as error:
            # Do not expose API error bodies: they may contain credentials or input.
            status = getattr(error, "status_code", None)
            safe_error = f"Triage failed: {type(error).__name__}" + (f" (HTTP {status})" if status else "") + ". Review server configuration and retry."
            store.fail(ticket_id, safe_error, (perf_counter() - started) * 1000)
            logger.warning("triage_failed ticket_id=%s error_type=%s status=%s", ticket_id, type(error).__name__, status)
        return find(ticket_id)

    @application.get("/health")
    def health():
        return {"status": "ok", "version": "1.0.0"}

    @application.get("/api/config")
    def config(request: Request):
        try:
            authorized(request)
            authenticated = True
        except HTTPException:
            authenticated = False
        return {"live_available": live_available, "model": MODEL_NAME, "auth_required": bool(workspace_token), "authenticated": authenticated, "workspace": "single-operator"}

    @application.post("/api/session")
    def login(payload: LoginRequest, request: Request, response: Response):
        if not workspace_token or not secrets.compare_digest(payload.token.encode("utf-8"), workspace_token.encode("utf-8")):
            raise HTTPException(401, "Incorrect workspace access token.")
        response.set_cookie("triage_session", session_value, httponly=True, secure=request.url.scheme == "https" or external_origin.startswith("https://"), samesite="strict", max_age=28800)
        return {"authenticated": True}

    @application.post("/api/session/logout")
    def logout(response: Response):
        response.delete_cookie("triage_session", httponly=True, samesite="strict")
        return {"authenticated": False}

    @application.get("/api/tickets", dependencies=[Depends(authorized)])
    def list_tickets():
        return store.list()

    @application.post("/api/tickets", status_code=201, dependencies=[Depends(authorized)])
    def submit(payload: TicketCreate):
        check_mode(payload.mode)
        ticket_id = store.create(payload.message, payload.mode)
        return run_triage(ticket_id, payload.message, payload.mode)

    @application.get("/api/tickets/{ticket_id}", dependencies=[Depends(authorized)])
    def detail(ticket_id: str):
        return find(ticket_id)

    @application.post("/api/tickets/import", dependencies=[Depends(authorized)])
    def import_tickets(payload: TicketImport):
        check_mode(payload.mode)
        try:
            reader = csv.DictReader(io.StringIO(payload.csv.lstrip("\ufeff")), strict=True)
            if not reader.fieldnames or "message" not in reader.fieldnames:
                raise HTTPException(422, "CSV must include a message column.")
            records = list(reader)
            if not 1 <= len(records) <= 25:
                raise HTTPException(422, "Import between 1 and 25 tickets at a time.")
            messages = [TicketCreate(message=row.get("message") or "", mode=payload.mode).message for row in records]
        except (ValueError, csv.Error):
            raise HTTPException(422, "Invalid CSV or ticket message. No tickets were imported.") from None
        created = []
        for message in messages:
            ticket = run_triage(store.create(message, payload.mode), message, payload.mode)
            created.append(ticket)
            if ticket["error"]:
                break
        return {"tickets": created, "imported": len(created), "remaining": len(messages) - len(created), "stopped_on_error": bool(created[-1]["error"])}

    @application.patch("/api/tickets/{ticket_id}", dependencies=[Depends(authorized)])
    def review(ticket_id: str, payload: TicketReview):
        find(ticket_id)
        try:
            store.review(ticket_id, payload.model_dump())
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        return find(ticket_id)

    @application.post("/api/tickets/{ticket_id}/retry", dependencies=[Depends(authorized)])
    def retry(ticket_id: str, payload: RetryRequest):
        ticket = find(ticket_id)
        check_mode(payload.mode)
        try:
            store.begin_retry(ticket_id, payload.mode)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        return run_triage(ticket_id, ticket["message"], payload.mode)

    @application.get("/api/stats", dependencies=[Depends(authorized)])
    def stats():
        return store.stats()

    @application.post("/api/demo/seed", dependencies=[Depends(authorized)])
    def samples():
        with seed_lock:
            if not store.stats()["total"]:
                messages = [
                    "Our entire support team cannot sign in, so nobody can answer customer tickets.",
                    "I was charged twice for this month's subscription.",
                    "Please send me a copy of my invoice.",
                ]
                for message in messages:
                    run_triage(store.create(message, "demo"), message, "demo")
            return store.list()

    @application.get("/api/export.csv", dependencies=[Depends(authorized)])
    def export():
        stream = io.StringIO(newline="")
        fields = ["id", "message", "category", "urgency", "summary", "review_status", "mode", "triage_status", "created_at"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for ticket in store.list():
            # Prevent spreadsheet formula evaluation when exported text is opened.
            row = {field: ticket.get(field, "") or "" for field in fields}
            for field, value in row.items():
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    row[field] = "'" + value
            writer.writerow(row)
        return Response(stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=tickets.csv"})

    application.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @application.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    @application.get("/docs", include_in_schema=False)
    def api_reference():
        return FileResponse(ROOT / "static" / "api.html")

    return application


app = create_app()
