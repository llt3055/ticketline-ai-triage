"""SQLite persistence with short transactions and an append-only review history."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class TicketStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Database schema is newer than this application.")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    message TEXT NOT NULL,
                    mode TEXT NOT NULL CHECK(mode IN ('demo','live')),
                    category TEXT,
                    urgency TEXT,
                    summary TEXT NOT NULL DEFAULT '',
                    review_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(review_status IN ('pending','approved')),
                    triage_status TEXT NOT NULL DEFAULT 'processing'
                        CHECK(triage_status IN ('processing','ready','error')),
                    error TEXT,
                    latency_ms REAL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    suggestion TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_ticket ON events(ticket_id, id);
                PRAGMA user_version = 1;
            """)
            # Recover records left in progress by a terminated local process.
            pending = db.execute("SELECT id FROM tickets WHERE triage_status='processing'").fetchall()
            for row in pending:
                db.execute("UPDATE tickets SET triage_status='error', error=?, updated_at=? WHERE id=?",
                           ("Previous run was interrupted. Retry this ticket.", now(), row["id"]))
                self._event(db, row["id"], "interrupted", {"reason": "Application restarted before triage completed"})

    @staticmethod
    def _event(db, ticket_id, action, details):
        db.execute("INSERT INTO events(ticket_id,created_at,action,details) VALUES(?,?,?,?)",
                   (ticket_id, now(), action, json.dumps(details)))

    def create(self, message, mode):
        ticket_id, timestamp = str(uuid4()), now()
        with self.connection() as db:
            db.execute("INSERT INTO tickets(id,message,mode,created_at,updated_at) VALUES(?,?,?,?,?)",
                       (ticket_id, message, mode, timestamp, timestamp))
            self._event(db, ticket_id, "submitted", {"mode": mode})
        return ticket_id

    def get(self, ticket_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["suggestion"] = json.loads(result["suggestion"]) if result["suggestion"] else None
            result["history"] = [
                {"created_at": event["created_at"], "action": event["action"], "details": json.loads(event["details"])}
                for event in db.execute("SELECT * FROM events WHERE ticket_id=? ORDER BY id", (ticket_id,))
            ]
            return result

    def list(self, limit=None):
        with self.connection() as db:
            query = "SELECT * FROM tickets ORDER BY created_at DESC"
            rows = db.execute(query if limit is None else query + " LIMIT ?", () if limit is None else (limit,)).fetchall()
            results = {row["id"]: dict(row) for row in rows}
            for result in results.values():
                result["suggestion"] = json.loads(result["suggestion"]) if result["suggestion"] else None
                result["history"] = []
            for event in db.execute("SELECT * FROM events ORDER BY id"):
                if event["ticket_id"] in results:
                    results[event["ticket_id"]]["history"].append({
                        "created_at": event["created_at"], "action": event["action"], "details": json.loads(event["details"])
                    })
            return list(results.values())

    def complete(self, ticket_id, result, elapsed_ms, usage):
        suggestion = result.model_dump()
        with self.connection() as db:
            db.execute("""UPDATE tickets SET category=?,urgency=?,summary=?,suggestion=?,
                triage_status='ready',error=NULL,latency_ms=?,input_tokens=?,output_tokens=?,updated_at=? WHERE id=?""",
                (result.category, result.urgency, result.summary, json.dumps(suggestion), elapsed_ms,
                 getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None), now(), ticket_id))
            self._event(db, ticket_id, "triaged", {"suggestion": suggestion, "latency_ms": round(elapsed_ms, 2)})

    def fail(self, ticket_id, error, elapsed_ms):
        with self.connection() as db:
            db.execute("UPDATE tickets SET triage_status='error',error=?,latency_ms=?,updated_at=? WHERE id=?",
                       (error, elapsed_ms, now(), ticket_id))
            self._event(db, ticket_id, "triage_failed", {"error": error})

    def begin_retry(self, ticket_id, mode):
        with self.connection() as db:
            row = db.execute("SELECT triage_status FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if row is None:
                raise KeyError(ticket_id)
            if row[0] != "error":
                raise ValueError("Only failed tickets can be retried.")
            changed = db.execute("UPDATE tickets SET triage_status='processing',mode=?,error=NULL,updated_at=? WHERE id=? AND triage_status='error'",
                                 (mode, now(), ticket_id)).rowcount
            if not changed:
                raise ValueError("This ticket is already being retried.")
            self._event(db, ticket_id, "retry_started", {"mode": mode})

    def review(self, ticket_id, values):
        with self.connection() as db:
            row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if row is None:
                raise KeyError(ticket_id)
            if row["triage_status"] != "ready":
                raise ValueError("Only successfully triaged tickets can be reviewed.")
            changes = {key: {"from": row[key], "to": value} for key, value in values.items() if row[key] != value}
            db.execute("UPDATE tickets SET category=?,urgency=?,summary=?,review_status=?,updated_at=? WHERE id=?",
                       (values["category"], values["urgency"], values["summary"], values["review_status"], now(), ticket_id))
            self._event(db, ticket_id, "approved" if values["review_status"] == "approved" else "review_saved", {"changes": changes})

    def stats(self):
        with self.connection() as db:
            row = db.execute("""SELECT COUNT(*) total,
                COALESCE(SUM(review_status='pending'),0) pending,
                COALESCE(SUM(review_status='approved'),0) approved,
                COALESCE(SUM(urgency='high'),0) high,
                COALESCE(SUM(triage_status='error'),0) errors FROM tickets""").fetchone()
            return dict(row)
