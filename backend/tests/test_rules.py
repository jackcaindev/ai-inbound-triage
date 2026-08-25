from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Record, RoutingDecision, Rule
from app.models.enums import RecordStatus
from app.pipeline.process import process_record
from tests.conftest import FakeLLMController


async def test_rule_forces_review_despite_high_confidence(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    """The non-negotiable this whole engine exists to prove: a rule can send a
    high-confidence record to human review, independent of confidence scoring."""
    db.add(
        Rule(
            name="High dollar amount forces review",
            priority=10,
            conditions=[{"field": "dollar_amounts_mentioned", "op": "any_gte", "value": 10000}],
            destination="finance_review",
            requires_review=True,
            active=True,
        )
    )
    await db.flush()

    record: Record = await make_record(raw_content="We'd like a quote for a $50,000 project.")
    fake_llm.set_classification(category="new_inquiry", confidence=0.98)
    fake_llm.set_extraction(
        contact_name="Jordan",
        company="Acme",
        requested_action="project quote",
        urgency="medium",
        dates_mentioned=[],
        dollar_amounts_mentioned=[50000],
    )

    result = await process_record(record.id, db)

    assert result.status == RecordStatus.NEEDS_REVIEW.value

    routing = (
        await db.execute(select(RoutingDecision).where(RoutingDecision.record_id == record.id))
    ).scalars().first()
    assert routing is None  # forced to review, not routed anywhere


async def test_first_matching_active_rule_wins_by_priority(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    db.add(
        Rule(
            name="lower priority number wins",
            priority=5,
            conditions=[{"category": "new_inquiry"}],
            destination="priority_queue",
            requires_review=False,
            active=True,
        )
    )
    db.add(
        Rule(
            name="later rule should be ignored",
            priority=50,
            conditions=[{"category": "new_inquiry"}],
            destination="other_queue",
            requires_review=False,
            active=True,
        )
    )
    await db.flush()

    record: Record = await make_record(raw_content="Hi, interested in your services.")
    fake_llm.set_classification(category="new_inquiry", confidence=0.95)
    fake_llm.set_extraction(
        contact_name="Alex",
        company=None,
        requested_action="general inquiry",
        urgency="low",
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )

    result = await process_record(record.id, db)

    assert result.status == RecordStatus.AUTO_ROUTED.value
    routing = (
        await db.execute(select(RoutingDecision).where(RoutingDecision.record_id == record.id))
    ).scalars().first()
    assert routing.destination == "priority_queue"


async def test_inactive_rule_is_never_matched(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    db.add(
        Rule(
            name="disabled high-dollar rule",
            priority=1,
            conditions=[{"field": "dollar_amounts_mentioned", "op": "any_gte", "value": 10000}],
            destination="finance_review",
            requires_review=True,
            active=False,
        )
    )
    await db.flush()

    record: Record = await make_record(raw_content="We'd like a quote for a $50,000 project.")
    fake_llm.set_classification(category="new_inquiry", confidence=0.98)
    fake_llm.set_extraction(
        contact_name="Jordan",
        company="Acme",
        requested_action="project quote",
        urgency="medium",
        dates_mentioned=[],
        dollar_amounts_mentioned=[50000],
    )

    result = await process_record(record.id, db)

    assert result.status == RecordStatus.AUTO_ROUTED.value
