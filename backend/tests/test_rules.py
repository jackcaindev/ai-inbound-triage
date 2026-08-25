from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import REPO_ROOT
from app.models import Record, RoutingDecision, Rule
from app.models.enums import RecordStatus
from app.pipeline.process import process_record
from app.pipeline.rules import load_seed_rules
from tests.conftest import FakeLLMController

SEED_RULES_PATH = REPO_ROOT / "seeds" / "rules.json"


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
    assert routing is not None
    assert routing.destination == "finance_review"
    assert routing.reason == "rule"
    assert routing.rule_id is not None


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


async def test_high_dollar_spam_record_routes_to_finance_review_not_spam(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    """Regression test: a spam-classified record with a high dollar amount must hit
    the priority-10 amount rule before the priority-20 spam-category rule, even though
    the extraction is otherwise sparse (as spam typically is) and classification
    confidence alone is high enough to auto-route."""
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
    db.add(
        Rule(
            name="Spam goes straight to spam queue",
            priority=20,
            conditions=[{"category": "spam"}],
            destination="spam",
            requires_review=False,
            active=True,
        )
    )
    await db.flush()

    record: Record = await make_record(
        raw_content="You've won! Claim your $50,000 prize now, click here."
    )
    fake_llm.set_classification(category="spam", confidence=0.97)
    fake_llm.set_extraction(
        contact_name=None,
        company=None,
        requested_action=None,
        urgency=None,
        dates_mentioned=[],
        dollar_amounts_mentioned=[50000.0],
    )

    result = await process_record(record.id, db)

    assert result.status == RecordStatus.NEEDS_REVIEW.value

    routing = (
        await db.execute(select(RoutingDecision).where(RoutingDecision.record_id == record.id))
    ).scalars().first()
    assert routing is not None
    assert routing.destination == "finance_review"
    assert routing.reason == "rule"

    amount_rule = (
        await db.execute(select(Rule).where(Rule.name == "High dollar amount forces review"))
    ).scalars().first()
    assert routing.rule_id == amount_rule.id


async def test_load_seed_rules_is_idempotent_on_name(db: AsyncSession) -> None:
    first = await load_seed_rules(SEED_RULES_PATH, db)
    assert first.created == 2
    assert first.skipped == 0

    second = await load_seed_rules(SEED_RULES_PATH, db)
    assert second.created == 0
    assert second.skipped == 2

    count = (await db.execute(select(Rule))).scalars().all()
    assert len(count) == 2


async def test_seeded_rules_route_high_dollar_spam_to_finance_review(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    """End-to-end verification against the real seeds/rules.json (not hand-rolled
    Rule objects): the priority-10 amount rule must win over the priority-20 spam
    rule for a spam record carrying a $50,000 amount."""
    await load_seed_rules(SEED_RULES_PATH, db)

    record: Record = await make_record(
        raw_content="You've won! Claim your $50,000 prize now, click here."
    )
    fake_llm.set_classification(category="spam", confidence=0.97)
    fake_llm.set_extraction(
        contact_name=None,
        company=None,
        requested_action=None,
        urgency=None,
        dates_mentioned=[],
        dollar_amounts_mentioned=[50000.0],
    )

    result = await process_record(record.id, db)

    assert result.status == RecordStatus.NEEDS_REVIEW.value

    routing = (
        await db.execute(select(RoutingDecision).where(RoutingDecision.record_id == record.id))
    ).scalars().first()
    assert routing is not None
    assert routing.destination == "finance_review"
    assert routing.reason == "rule"

    amount_rule = (
        await db.execute(select(Rule).where(Rule.name == "High dollar amount forces review"))
    ).scalars().first()
    assert routing.rule_id == amount_rule.id


async def test_high_classification_confidence_auto_routes_despite_sparse_extraction(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    """Low extraction confidence alone must never gate a record into review — only
    the classifier's own confidence, and rules, get a say."""
    record: Record = await make_record(raw_content="Hi, interested in your services.")
    fake_llm.set_classification(category="new_inquiry", confidence=0.97)
    fake_llm.set_extraction(
        contact_name=None,
        company=None,
        requested_action="general inquiry",
        urgency=None,
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )

    result = await process_record(record.id, db)

    assert result.status == RecordStatus.AUTO_ROUTED.value
    routing = (
        await db.execute(select(RoutingDecision).where(RoutingDecision.record_id == record.id))
    ).scalars().first()
    assert routing is not None
    assert routing.destination == "new_inquiry"


async def test_billing_question_without_dollar_amount_or_company_auto_routes(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    """An absent field is not an uncertain one: a billing question that never states a
    dollar figure or a company name must still auto-route on high confidence, as long
    as requested_action — the field routing actually depends on — is present."""
    record: Record = await make_record(raw_content="Why did my subscription price go up?")
    fake_llm.set_classification(category="billing_question", confidence=0.95)
    fake_llm.set_extraction(
        contact_name="Riley",
        company=None,
        requested_action="explain price increase",
        urgency="low",
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )

    result = await process_record(record.id, db)

    assert result.status == RecordStatus.AUTO_ROUTED.value
    routing = (
        await db.execute(select(RoutingDecision).where(RoutingDecision.record_id == record.id))
    ).scalars().first()
    assert routing is not None
    assert routing.destination == "billing_question"


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
