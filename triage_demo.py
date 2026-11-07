"""Deterministic, credential-free demonstration. This is not an AI model."""

import re

from triage import TicketTriage


def demo_triage(message):
    if not isinstance(message, str) or not message.strip():
        raise ValueError("A ticket must be nonempty text.")
    text = message.casefold()
    broken = any(word in text for word in (
        "crash", "error", "broken", "fails", "failed", "won't", "cannot",
        "can't", "unable", "not working", "unavailable", "outage", "locked out",
    ))
    technical = any(word in text for word in (
        "log in", "login", "sign in", "password", "access", "crash", "error",
        "broken", "fails", "failed", "not working", "unavailable", "outage",
        "upload", "download", "blank screen", "locked out", "won't open",
    ))
    billing = any(word in text for word in (
        "charg", "invoice", "refund", "payment", "paid", "money", "billing",
        "receipt", "debit", "credit card", "subscription cost", "transaction",
    ))
    # A broken billing page is a technical issue; otherwise money requests are billing.
    category = "technical" if technical and broken else "billing" if billing else "technical" if technical else "other"
    many = any(word in text for word in (
        "entire team", "whole team", "all users", "every user", "many users",
        "everyone", "nobody", "team-wide", "company-wide", "all staff",
        "entire support team", "whole company",
    ))
    routine = any(word in text for word in (
        "what", "where", "when", "hours", "copy", "opening", "languages",
        "documentation", "guide", "how do i", "how can i", "resend",
    ))
    urgency = "high" if many and broken else "low" if routine and not broken else "normal"
    clean = re.sub(r"\s+", " ", message).strip()
    summary = clean if len(clean) <= 180 else clean[:177].rstrip() + "..."
    return TicketTriage(category=category, urgency=urgency, summary=summary)
