from typing import Literal

from pydantic import BaseModel, Field


class BaseExtractionFields(BaseModel):
    """Structured output the LLM must return for the extract stage.

    Every field is optional. A field not clearly present in the source message must
    come back None (or an empty list for the list fields) — never guessed or inferred.
    The extract prompt says this explicitly, and test_extract.py asserts it directly.
    """

    contact_name: str | None = None
    company: str | None = None
    requested_action: str | None = None
    urgency: Literal["low", "medium", "high"] | None = None
    dates_mentioned: list[str] = Field(default_factory=list)
    dollar_amounts_mentioned: list[float] = Field(default_factory=list)


# Fields a category cannot be missing without forcing needs_review, even though the
# schema itself keeps every field Optional (a field can legitimately be absent from
# the source). Enforced in app code post-extraction, not via Pydantic `...`-required,
# since "required but nullable" isn't expressible as a plain required Pydantic field.
#
# Kept deliberately minimal: an absent field is not an uncertain one. A sender who
# never mentions a dollar amount or a date isn't a low-confidence extraction — the
# category just isn't about money or dates for that message. requested_action is the
# one field routing genuinely cannot proceed without, since it's what tells a human
# (or a rule) what the business is actually being asked to do. spam has no required
# fields at all: "no genuine business request" is exactly what that category means, so
# there's nothing to require.
REQUIRED_FIELDS_BY_CATEGORY: dict[str, list[str]] = {
    "new_inquiry": ["requested_action"],
    "support_issue": ["requested_action"],
    "billing_question": ["requested_action"],
    "scheduling_request": ["requested_action"],
}


def missing_required_fields(category: str, fields: BaseExtractionFields) -> list[str]:
    """Return the names of required-for-this-category fields that came back empty."""
    required = REQUIRED_FIELDS_BY_CATEGORY.get(category, [])
    missing = []
    for name in required:
        value = getattr(fields, name)
        if value is None or value == []:
            missing.append(name)
    return missing


BASE_FIELD_NAMES = [
    "contact_name",
    "company",
    "requested_action",
    "urgency",
    "dates_mentioned",
    "dollar_amounts_mentioned",
]


def completeness(fields: BaseExtractionFields) -> float:
    """Fraction of the base fields that came back populated. This is what feeds the
    confidence floor rule — an extraction that's mostly empty caps overall confidence
    regardless of how confident the classifier was."""
    populated = sum(1 for name in BASE_FIELD_NAMES if getattr(fields, name) not in (None, []))
    return populated / len(BASE_FIELD_NAMES)
