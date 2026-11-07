"""Network-free deployment, documentation and import-safety checks."""

import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import create_app
import run_server


class ServerTests(unittest.TestCase):
    def test_proxy_origin_is_explicit_and_session_cookie_is_secure(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"TRIAGE_EXTERNAL_ORIGIN": "https://workspace.example"}):
            app = create_app(db_path=Path(directory) / "db.sqlite", access_token="test-workspace-token", api_key="")
            with TestClient(app) as client:
                result = client.post("/api/session", json={"token": "test-workspace-token"}, headers={"Origin": "https://workspace.example"})
                self.assertEqual(result.status_code, 200)
                self.assertIn("Secure", result.headers["set-cookie"])
                self.assertNotIn("test-workspace-token", result.headers["set-cookie"])
                self.assertEqual(client.post("/api/session", json={"token": "test-workspace-token"}, headers={"Origin": "https://attacker.example"}).status_code, 403)

    def test_network_bind_without_token_is_rejected_before_server_starts(self):
        with patch.dict(os.environ, {"TRIAGE_HOST": "0.0.0.0", "TRIAGE_ACCESS_TOKEN": ""}), patch("sys.argv", ["run_server.py"]), patch("run_server.uvicorn.run") as start:
            with self.assertRaises(SystemExit):
                run_server.main()
            start.assert_not_called()

    def test_api_reference_uses_local_assets_and_schema_is_available(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(db_path=Path(directory) / "db.sqlite", access_token="", api_key="")
            with TestClient(app) as client:
                page = client.get("/docs")
                self.assertEqual(page.status_code, 200)
                self.assertIn('/static/api-docs.js', page.text)
                self.assertIn('/api/tickets', client.get("/openapi.json").json()["paths"])

    def test_category_cli_import_never_prompts_or_creates_a_client(self):
        path = Path(__file__).resolve().parents[1] / "ticket_classifier_ai.py"
        with patch("getpass.getpass") as prompt, patch("openai.OpenAI") as provider:
            runpy.run_path(str(path), run_name="imported_cli")
            prompt.assert_not_called()
            provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
