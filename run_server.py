"""Start the local dashboard; require access protection for network exposure."""

import os
import argparse
from getpass import getpass
import uvicorn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Ask privately for an API key if OPENAI_API_KEY is not set.")
    parser.add_argument("--protect", action="store_true", help="Ask privately for a workspace token if not already configured.")
    args = parser.parse_args()
    if args.live and not os.environ.get("OPENAI_API_KEY"):
        key = getpass("OpenAI API key (hidden, kept only for this server process): ").strip()
        if not key:
            raise SystemExit("No API key entered.")
        os.environ["OPENAI_API_KEY"] = key
    if args.protect and not os.environ.get("TRIAGE_ACCESS_TOKEN"):
        token = getpass("Workspace access token (16+ characters, hidden): ").strip()
        if len(token) < 16:
            raise SystemExit("Use at least 16 characters for the workspace token.")
        os.environ["TRIAGE_ACCESS_TOKEN"] = token
    host = os.environ.get("TRIAGE_HOST", "127.0.0.1")
    port = int(os.environ.get("TRIAGE_PORT", "8000"))
    if host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get("TRIAGE_ACCESS_TOKEN"):
        raise SystemExit("Set TRIAGE_ACCESS_TOKEN before exposing the application beyond localhost.")
    uvicorn.run("app:app", host=host, port=port, access_log=False)


if __name__ == "__main__":
    main()
