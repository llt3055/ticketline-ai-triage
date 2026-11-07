"""Compare classifiers on nine known development examples."""

import argparse
from getpass import getpass

from openai import APIError, AuthenticationError, OpenAI

from classifier import classify_ticket
from ticket_classifier import classify

# Hand-written teaching examples, not real customer data or a held-out test set.
DEV_TICKETS = [
    ("I was charged twice for my subscription.", "billing"),
    ("Please send me a copy of my invoice.", "billing"),
    ("I requested a refund but have not received the money.", "billing"),
    ("I cannot log in to my account.", "technical"),
    ("I cannot access my account.", "technical"),
    ("The app crashes every time I open it.", "technical"),
    ("What are your business hours?", "other"),
    ("Where is your company headquarters?", "other"),
    ("What languages does your customer support team speak?", "other"),
]


def evaluate(predict, tickets):
    """Give only the message to predict; keep the expected label for scoring."""
    correct = 0
    for message, expected in tickets:
        predicted = predict(message)
        matched = predicted == expected
        if matched:
            correct += 1
        result = "CORRECT" if matched else "WRONG"
        print(f"Message: {message}")
        print(f"Expected: {expected} | Predicted: {predicted} | {result}\n")

    # Reached only after every prediction succeeds. Errors are never skipped.
    print(f"Accuracy on development examples: {correct}/{len(tickets)}")
    return correct


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ai", action="store_true",
        help="Use the AI model: sends up to nine paid requests instead of rules.",
    )
    args = parser.parse_args(argv)

    if not args.ai:
        print("Mode: keyword rules. No API requests.\n")
        return evaluate(classify, DEV_TICKETS)

    print(f"Mode: AI. Up to {len(DEV_TICKETS)} requests, one per ticket.\n")
    api_key = getpass("Paste your OpenAI API key (hidden): ").strip()
    if not api_key:
        raise SystemExit("No key entered. No AI requests were sent.")

    client = OpenAI(api_key=api_key, timeout=30.0, max_retries=0)

    def predict(message):
        category, usage = classify_ticket(message, client)
        return category

    try:
        return evaluate(predict, DEV_TICKETS)
    except AuthenticationError:
        raise SystemExit(
            "Evaluation stopped: authentication failed (401).\n"
            "Check your complete secret key at https://platform.openai.com/api-keys.\n"
            "No complete accuracy score was produced."
        ) from None
    except APIError as error:
        status = getattr(error, "status_code", None)
        raise SystemExit(
            f"Evaluation stopped: {type(error).__name__}, HTTP status {status}.\n"
            "Check API access, credit, or connection before retrying.\n"
            "No complete accuracy score was produced."
        ) from None
    except (ValueError, RuntimeError) as error:
        raise SystemExit(
            f"Evaluation stopped: {error}\n"
            "No complete accuracy score was produced."
        ) from None
    finally:
        client.close()


if __name__ == "__main__":
    main()
