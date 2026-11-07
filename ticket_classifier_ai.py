"""Project 1, step 2: send one support ticket to a language model."""

from getpass import getpass
import os
from time import perf_counter

from openai import AuthenticationError, OpenAI

from classifier import classify_ticket

def main():
    api_key = os.environ.get("OPENAI_API_KEY", "").strip() or getpass("Paste your OpenAI API key (hidden): ").strip()
    if not api_key:
        raise SystemExit("No API key entered.")
    message = "I cannot access my account."
    started = perf_counter()
    try:
        with OpenAI(api_key=api_key, timeout=30.0, max_retries=0) as client:
            predicted, usage = classify_ticket(message, client)
    except AuthenticationError:
        raise SystemExit("Authentication failed (401). Check your complete secret key at https://platform.openai.com/api-keys.") from None
    print(f"Message: {message}")
    print(f"Predicted: {predicted}")
    print(f"Response time: {perf_counter() - started:.2f} seconds")
    if usage is not None:
        print(f"Input tokens: {usage.input_tokens}")
        print(f"Output tokens: {usage.output_tokens}")


if __name__ == "__main__":
    main()
