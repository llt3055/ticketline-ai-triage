"""Ask for one ticket and print its structured AI triage."""

from getpass import getpass
from time import perf_counter

from openai import APIError, AuthenticationError, OpenAI

from triage import triage_ticket


def main():
    message = input("Ticket message: ").strip()
    if not message:
        raise SystemExit("No ticket entered. No API request was sent.")

    api_key = getpass("Paste your OpenAI API key (hidden): ").strip()
    if not api_key:
        raise SystemExit("No key entered. No API request was sent.")

    client = OpenAI(api_key=api_key, timeout=30.0, max_retries=0)
    started = perf_counter()
    try:
        result, usage = triage_ticket(message, client)
    except AuthenticationError:
        raise SystemExit(
            "Triage stopped: authentication failed (401). Check your complete secret key."
        ) from None
    except APIError as error:
        status = getattr(error, "status_code", None)
        raise SystemExit(
            f"Triage stopped: {type(error).__name__}, HTTP status {status}.\n"
            "Check API access, credit, or connection before retrying."
        ) from None
    except (ValueError, RuntimeError) as error:
        raise SystemExit(f"Triage stopped: {error}") from None
    finally:
        client.close()

    elapsed = perf_counter() - started
    print(result.model_dump_json(indent=2))
    print(f"Response time: {elapsed:.2f} seconds")
    if usage is not None:
        print(f"Input tokens: {usage.input_tokens}")
        print(f"Output tokens: {usage.output_tokens}")


if __name__ == "__main__":
    main()
