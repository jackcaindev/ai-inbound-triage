"""Extraction prompt, version extract_v1."""

PROMPT_VERSION = "extract_v1"


def build_extract_prompt(category: str, raw_content: str) -> tuple[str, str]:
    """Returns (system_prompt, user_message)."""
    system = (
        f"You are extracting structured fields from an inbound '{category}' business message.\n"
        "Extract these fields: contact_name, company, requested_action, "
        "urgency (one of: low, medium, high), dates_mentioned (list of date strings "
        "exactly as they appear in the message), dollar_amounts_mentioned (list of "
        "numbers, no currency symbols).\n\n"
        "CRITICAL: only extract a value that is explicitly stated in the message. "
        "If a field is not clearly present, you MUST return null for it (or an empty "
        "list for the two list fields). Never guess, infer, or fabricate a value that "
        "is not stated in the message — an absent field is expected and correct, not "
        "an error."
    )
    user_message = f"Message:\n\n{raw_content}"
    return system, user_message
