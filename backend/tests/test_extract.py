from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Record
from app.pipeline.extract import extract_record
from tests.conftest import FakeLLMController


async def test_extract_returns_none_for_fields_absent_from_source(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    """The non-negotiable: a field not present in the source is None, never invented.
    Only requested_action is actually stated in this message — everything else the
    (fake) model correctly reports as absent."""
    record: Record = await make_record(raw_content="Hi, quick question about your hours.")
    fake_llm.set_extraction(
        contact_name=None,
        company=None,
        requested_action="asking about business hours",
        urgency=None,
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )

    outcome = await extract_record(record, "new_inquiry", db)

    assert outcome.extraction.fields["contact_name"] is None
    assert outcome.extraction.fields["company"] is None
    assert outcome.extraction.fields["urgency"] is None
    assert outcome.extraction.fields["dates_mentioned"] == []
    assert outcome.extraction.fields["dollar_amounts_mentioned"] == []
    assert outcome.extraction.fields["requested_action"] == "asking about business hours"


async def test_missing_category_required_field_is_flagged(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    """billing_question requires a dollar amount to be extractable — if the model
    (correctly) can't find one, that must be surfaced as a missing required field so
    the caller can force needs_review, not silently treated as a normal empty field."""
    record: Record = await make_record(raw_content="Why was I charged again this month?")
    fake_llm.set_extraction(
        contact_name="Sam",
        company=None,
        requested_action="dispute a charge",
        urgency="medium",
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )

    outcome = await extract_record(record, "billing_question", db)

    assert outcome.missing_required_fields == ["dollar_amounts_mentioned"]


async def test_no_required_fields_for_a_category_with_none_configured(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    record: Record = await make_record(raw_content="Just saying hi, no request here.")
    fake_llm.set_extraction(
        contact_name=None,
        company=None,
        requested_action=None,
        urgency=None,
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )

    outcome = await extract_record(record, "spam", db)

    assert outcome.missing_required_fields == []
