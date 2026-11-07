# Example tickets: each contains a message and its correct category.
tickets = [
    ("I was charged twice for my subscription.", "billing"),
    ("I cannot log in to my account.", "technical"),
    ("What are your business hours?", "other"),
    ("I cannot access my account.", "technical"),
]


# Predict a category using simple keyword rules.
def classify(message):
    text = message.lower()

    if "charged" in text or "invoice" in text:
        return "billing"

    if "log in" in text:
        return "technical"

    return "other"


# The guard lets other files import classify without running this demonstration.
if __name__ == "__main__":
    # Check each prediction against the correct category.
    correct = 0

    for message, expected in tickets:
        predicted = classify(message)

        print(f"Message: {message}")
        print(f"Expected: {expected} | Predicted: {predicted}")
        print()

        if predicted == expected:
            correct += 1

    print(f"Accuracy on these examples: {correct}/{len(tickets)}")
