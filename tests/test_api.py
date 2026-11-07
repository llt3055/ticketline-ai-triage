"""Offline integration tests for the HTTP API and persistent review workflow."""

import csv
import io
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from triage import TicketTriage


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "tickets.sqlite3"

    def client(self, **kwargs):
        return TestClient(create_app(db_path=self.db_path, **kwargs))

    def create_demo(self, client, message="I need a copy of my invoice."):
        response = client.post("/api/tickets", json={"message": message, "mode": "demo"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_create_review_and_persist_across_app_instances(self):
        with self.client() as client:
            ticket = self.create_demo(client)
            self.assertEqual(ticket["mode"], "demo")
            self.assertEqual(ticket["review_status"], "pending")
            original = ticket["suggestion"].copy()
            update = {"category": "other", "urgency": "normal", "summary": "Reviewed summary", "review_status": "approved"}
            response = client.patch(f"/api/tickets/{ticket['id']}", json=update)
            self.assertEqual(response.status_code, 200, response.text)
            reviewed = response.json()
            for key, value in update.items():
                self.assertEqual(reviewed[key], value)
            self.assertEqual(reviewed["suggestion"], original)
            self.assertGreater(len(reviewed["history"]), len(ticket["history"]))
            self.assertEqual(client.get("/api/stats").json()["approved"], 1)

        with self.client() as restarted:
            response = restarted.get("/api/tickets")
            self.assertEqual(response.status_code, 200)
            persisted = response.json()
            self.assertEqual(len(persisted), 1)
            self.assertEqual(persisted[0]["id"], ticket["id"])
            self.assertEqual(persisted[0]["summary"], "Reviewed summary")
            self.assertEqual(persisted[0]["suggestion"], original)

    def test_invalid_requests_are_rejected(self):
        with self.client() as client:
            for payload in (
                {"message": "   ", "mode": "demo"},
                {"message": "A ticket", "mode": "unknown"},
                {"message": "", "mode": "live"},
            ):
                with self.subTest(payload=payload):
                    self.assertEqual(client.post("/api/tickets", json=payload).status_code, 422)
            ticket = self.create_demo(client)
            response = client.patch(f"/api/tickets/{ticket['id']}", json={
                "category": "billing", "urgency": "critical", "summary": "test", "review_status": "approved"
            })
            self.assertEqual(response.status_code, 422)
            self.assertEqual(client.get("/api/stats").json()["total"], 1)

    def test_unconfigured_live_mode_never_creates_a_ticket(self):
        with self.client(api_key="") as client:
            response = client.post("/api/tickets", json={"message": "The app crashed", "mode": "live"})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(client.get("/api/tickets").json(), [])

    def test_live_error_is_saved_without_secret_and_cannot_be_approved(self):
        secret = "fake-server-secret-do-not-return"

        def broken(_message):
            raise RuntimeError(f"backend details include {secret}")

        with self.client(api_key=secret, live_runner=broken) as client:
            response = client.post("/api/tickets", json={"message": "App crashed", "mode": "live"})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertNotIn(secret, response.text)
            ticket = response.json()
            self.assertEqual(ticket["triage_status"], "error")
            self.assertTrue(ticket["error"])
            update = {"category": "technical", "urgency": "normal", "summary": "App crashed", "review_status": "approved"}
            self.assertEqual(client.patch(f"/api/tickets/{ticket['id']}", json=update).status_code, 409)
            self.assertNotIn(secret, client.get("/api/tickets").text)

    def test_failed_ticket_can_retry_and_become_ready(self):
        attempts = []

        def flaky(message):
            attempts.append(message)
            if len(attempts) == 1:
                raise RuntimeError("simulated failure")
            return TicketTriage(category="technical", urgency="normal", summary="App crashed."), None

        with self.client(api_key="fake-secret", live_runner=flaky) as client:
            ticket = client.post("/api/tickets", json={"message": "App crashed", "mode": "live"}).json()
            self.assertEqual(ticket["triage_status"], "error")
            response = client.post(f"/api/tickets/{ticket['id']}/retry", json={"mode": "live"})
            self.assertEqual(response.status_code, 200, response.text)
            retried = response.json()
            self.assertEqual(retried["triage_status"], "ready")
            self.assertFalse(retried["error"])
            self.assertEqual(retried["category"], "technical")
            self.assertGreater(len(retried["history"]), len(ticket["history"]))
            self.assertEqual(len(attempts), 2)

    def test_auth_header_session_cookie_and_logout(self):
        with self.client(access_token="workspace-test-token") as client:
            self.assertEqual(client.get("/api/tickets").status_code, 401)
            self.assertEqual(client.get("/api/tickets", headers={"Authorization": "Bearer workspace-test-token"}).status_code, 200)
            self.assertEqual(client.post("/api/session", json={"token": "wrong"}).status_code, 401)
            login = client.post("/api/session", json={"token": "workspace-test-token"})
            self.assertEqual(login.status_code, 200)
            self.assertIn("httponly", login.headers.get("set-cookie", "").lower())
            self.assertEqual(client.get("/api/tickets").status_code, 200)
            self.assertEqual(client.post("/api/session/logout").status_code, 200)
            self.assertEqual(client.get("/api/tickets").status_code, 401)

    def test_config_is_public_and_never_exposes_the_api_key(self):
        secret = "fake-config-secret-do-not-return"
        with self.client(access_token="workspace-test-token", api_key=secret) as client:
            response = client.get("/api/config")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["auth_required"])
            self.assertTrue(response.json()["live_available"])
            self.assertIn("model", response.json())
            self.assertNotIn(secret, response.text)

    def test_cross_origin_mutation_is_rejected(self):
        with self.client() as client:
            response = client.post("/api/tickets", headers={"Origin": "https://untrusted.example"}, json={"message": "App crashed", "mode": "demo"})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(client.get("/api/tickets").json(), [])

    def test_csv_import_validates_all_rows_before_writing_and_handles_quotes(self):
        with self.client() as client:
            invalid = client.post("/api/tickets/import", json={"csv": "message\nValid ticket\n   \n", "mode": "demo"})
            self.assertEqual(invalid.status_code, 422, invalid.text)
            self.assertEqual(client.get("/api/tickets").json(), [])
            text = 'message\n"Invoice, please"\n"App crashed\non startup"\n'
            imported = client.post("/api/tickets/import", json={"csv": text, "mode": "demo"})
            self.assertEqual(imported.status_code, 200, imported.text)
            result = imported.json()
            self.assertEqual(result["imported"], 2)
            self.assertEqual(result["remaining"], 0)
            self.assertFalse(result["stopped_on_error"])
            self.assertEqual({t["message"] for t in result["tickets"]}, {"Invoice, please", "App crashed\non startup"})

    def test_csv_live_import_stops_after_first_provider_failure(self):
        calls = []

        def fails_on_second(message):
            calls.append(message)
            if len(calls) == 2:
                raise RuntimeError("simulated provider failure")
            return TicketTriage(category="other", urgency="normal", summary="First request."), None

        with self.client(live_runner=fails_on_second, api_key="") as client:
            response = client.post("/api/tickets/import", json={"csv": "message\nFirst\nSecond\nThird\n", "mode": "live"})
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertTrue(result["stopped_on_error"])
            self.assertEqual((result["imported"], result["remaining"]), (2, 1))
            self.assertEqual(calls, ["First", "Second"])
            self.assertEqual(result["tickets"][-1]["triage_status"], "error")
            self.assertEqual(client.get("/api/stats").json()["total"], 2)

    def test_csv_export_requires_auth_and_includes_all_with_formula_escaping(self):
        with self.client(access_token="workspace-token") as client:
            self.assertEqual(client.get("/api/export.csv").status_code, 401)
            self.assertEqual(client.post("/api/session", json={"token": "workspace-token"}).status_code, 200)
            self.create_demo(client, '=HYPERLINK("https://example.com", "click")')
            self.create_demo(client, "A regular message")
            response = client.get("/api/export.csv")
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/csv", response.headers["content-type"])
            rows = list(csv.DictReader(io.StringIO(response.text)))
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["message"] for row in rows}, {'\'=HYPERLINK("https://example.com", "click")', "A regular message"})

    def test_unicode_workspace_token_can_sign_in_and_authenticate(self):
        with self.client(access_token="测试-workspace-🔑") as client:
            login = client.post("/api/session", json={"token": "测试-workspace-🔑"})
            self.assertEqual(login.status_code, 200, login.text)
            self.assertEqual(client.get("/api/tickets").status_code, 200)

    def test_interrupted_processing_recovers_and_ready_ticket_cannot_retry(self):
        with self.client() as client:
            ready = self.create_demo(client)
            self.assertEqual(client.post(f"/api/tickets/{ready['id']}/retry", json={"mode": "demo"}).status_code, 409)
            pending_id = client.app.state.store.create("Interrupted ticket", "demo")

        with self.client() as restarted:
            recovered = restarted.get(f"/api/tickets/{pending_id}").json()
            self.assertEqual(recovered["triage_status"], "error")
            self.assertIn("interrupted", recovered["error"].lower())
            self.assertTrue(any(event["action"] == "interrupted" for event in recovered["history"]))

    def test_begin_retry_only_allows_one_claim(self):
        with self.client() as client:
            store = client.app.state.store
            ticket_id = store.create("Interrupted ticket", "demo")
            store.fail(ticket_id, "Simulated failure", 0)
            store.begin_retry(ticket_id, "demo")
            with self.assertRaises(ValueError):
                store.begin_retry(ticket_id, "demo")
            ticket = store.get(ticket_id)
            self.assertEqual(ticket["triage_status"], "processing")
            self.assertEqual(sum(event["action"] == "retry_started" for event in ticket["history"]), 1)


if __name__ == "__main__":
    unittest.main()
