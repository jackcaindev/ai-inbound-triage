from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EvalExample, Record, RoutingDecision
from app.models.enums import RecordStatus
from app.pipeline.classify import classify_record
from app.pipeline.extract import extract_record
from app.pipeline.review import submit_review_decision
from tests.conftest import FakeLLMController

CATEGORIES = [
    {"name": "support_issue", "description": "x"},
    {"name": "billing_question", "description": "y"},
]


async def test_correction_persists_and_creates_eval_example(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    """The Phase 1 acceptance line this exists for: a human correction must persist
    and must write an eval_examples row with source='human_correction' — this is what
    closes the loop and feeds the eval set."""
    record: Record = await make_record(raw_content="Can I get a refund for my March bill?")
    fake_llm.set_classification(category="support_issue", confidence=0.6)
    fake_llm.set_extraction(
        contact_name="Lee",
        company=None,
        requested_action="refund request",
        urgency="medium",
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )
    classification = await classify_record(record, CATEGORIES, db)
    await extract_record(record, classification.category, db)

    result = await submit_review_decision(
        record.id,
        "correct",
        db,
        corrected_category="billing_question",
        reviewer="ops@example.com",
        note="miscategorized, it's actually about a refund",
    )

    assert result.status == RecordStatus.RESOLVED.value

    eval_example = (
        await db.execute(select(EvalExample).where(EvalExample.record_id == record.id))
    ).scalars().first()
    assert eval_example is not None
    assert eval_example.expected_category == "billing_question"
    assert eval_example.source == "human_correction"

    routing = (
        await db.execute(select(RoutingDecision).where(RoutingDecision.record_id == record.id))
    ).scalars().first()
    assert routing is not None
    assert routing.decided_by == "human"


async def test_accept_uses_original_model_output_as_the_eval_example(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    record: Record = await make_record(raw_content="Please cancel my subscription.")
    fake_llm.set_classification(category="billing_question", confidence=0.7)
    fake_llm.set_extraction(
        contact_name="Robin",
        company=None,
        requested_action="cancel subscription",
        urgency="low",
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )
    classification = await classify_record(record, CATEGORIES, db)
    await extract_record(record, classification.category, db)

    await submit_review_decision(record.id, "accept", db, reviewer="ops@example.com")

    eval_example = (
        await db.execute(select(EvalExample).where(EvalExample.record_id == record.id))
    ).scalars().first()
    assert eval_example.expected_category == "billing_question"
    assert eval_example.expected_fields["requested_action"] == "cancel subscription"


async def test_reject_resolves_without_creating_an_eval_example(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    record: Record = await make_record(raw_content="Not a real business request.")
    fake_llm.set_classification(category="support_issue", confidence=0.5)
    fake_llm.set_extraction(
        contact_name=None,
        company=None,
        requested_action=None,
        urgency=None,
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )
    classification = await classify_record(record, CATEGORIES, db)
    await extract_record(record, classification.category, db)

    result = await submit_review_decision(record.id, "reject", db, reviewer="ops@example.com")

    assert result.status == RecordStatus.RESOLVED.value
    eval_example = (
        await db.execute(select(EvalExample).where(EvalExample.record_id == record.id))
    ).scalars().first()
    assert eval_example is None
