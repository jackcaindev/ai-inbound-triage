"""Classification prompt, version classify_v1. Category names/descriptions come from
config/categories.yaml at call time — never hardcode a category list in this file."""

PROMPT_VERSION = "classify_v1"


def build_classify_prompt(categories: list[dict], raw_content: str) -> tuple[str, str]:
    """Returns (system_prompt, user_message)."""
    category_lines = "\n".join(
        f"- {c['name']}: {c['description'].strip()}" for c in categories
    )
    system = (
        "You are a triage classifier for inbound business messages arriving by email.\n"
        "Classify the message into exactly one of the following categories:\n\n"
        f"{category_lines}\n\n"
        "Respond by calling the provided tool with your chosen category (use the exact "
        "category name given above), a confidence score between 0 and 1 reflecting how "
        "certain you are, and a brief one-sentence reasoning."
    )
    user_message = f"Message to classify:\n\n{raw_content}"
    return system, user_message
