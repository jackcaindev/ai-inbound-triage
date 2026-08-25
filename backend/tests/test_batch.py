from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Record
from app.models.enums import RecordStatus
from app.pipeline.batch import compute_stats, run_batch
from app.schemas.classification import ClassificationResult
from app.schemas.extraction import BaseExtractionFields
from tests.conftest import FakeLLMController

# (snippet unique to the message, category, confidence, extraction fields)
RESPONSES_BY_SNIPPET: list[tuple[str, str, float, dict[str, Any]]] = [
    (
        "service my area",
        "new_inquiry",
        0.93,
        {
            "contact_name": "Morgan",
            "company": None,
            "requested_action": "service area check",
            "urgency": "low",
            "dates_mentioned": [],
            "dollar_amounts_mentioned": [],
        },
    ),
    (
        "following up on the thing",
        "new_inquiry",
        0.35,
        {
            "contact_name": None,
            "company": None,
            "requested_action": None,
            "urgency": None,
            "dates_mentioned": [],
            "dollar_amounts_mentioned": [],
        },
    ),
]


def _responder(kwargs: dict[str, Any]) -> Any:
    user_message = kwargs["user_message"]
    for snippet, category, confidence, fields in RESPONSES_BY_SNIPPET:
        if snippet in user_message:
            if kwargs["response_model"] is ClassificationResult:
                return ClassificationResult(category=category, confidence=confidence)
            return BaseExtractionFields(**fields)
    raise AssertionError(f"no fake response configured for message: {user_message!r}")


async def test_run_batch_processes_pending_and_reports_summary(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    fake_llm.set_responder(_responder)
    await make_record(external_ref="clear", raw_content="service my area please")
    await make_record(external_ref="vague", raw_content="hey, following up on the thing")

    seen = []
    summary = await run_batch(db, on_record=seen.append)

    assert summary.total == 2
    assert summary.auto_routed == 1
    assert summary.needs_review == 1
    assert summary.failed == 0
    assert summary.auto_route_pct == 50.0
    assert [o.external_ref for o in seen] == ["clear", "vague"]
    assert [o.status for o in summary.outcomes] == [
        RecordStatus.AUTO_ROUTED.value,
        RecordStatus.NEEDS_REVIEW.value,
    ]


async def test_run_batch_leaves_no_pending_records_behind(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    fake_llm.set_responder(_responder)
    await make_record(external_ref="clear", raw_content="service my area please")
    await make_record(external_ref="vague", raw_content="hey, following up on the thing")

    await run_batch(db)

    remaining = (
        await db.execute(select(Record).where(Record.status == RecordStatus.PENDING.value))
    ).scalars().all()
    assert remaining == []


async def test_run_batch_limit_caps_how_many_are_processed(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    fake_llm.set_classification(category="new_inquiry", confidence=0.93)
    fake_llm.set_extraction(
        contact_name="A",
        company=None,
        requested_action="x",
        urgency="low",
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )
    for i in range(3):
        await make_record(external_ref=f"rec-{i}", raw_content=f"message {i}")

    summary = await run_batch(db, limit=2)

    assert summary.total == 2
    remaining = (
        await db.execute(select(Record).where(Record.status == RecordStatus.PENDING.value))
    ).scalars().all()
    assert len(remaining) == 1


async def test_run_batch_record_id_processes_only_that_record(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    fake_llm.set_classification(category="new_inquiry", confidence=0.93)
    fake_llm.set_extraction(
        contact_name="A",
        company=None,
        requested_action="x",
        urgency="low",
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )
    other = await make_record(external_ref="rec-a", raw_content="a")
    target = await make_record(external_ref="rec-b", raw_content="b")

    summary = await run_batch(db, record_id=target.id)

    assert summary.total == 1
    assert summary.outcomes[0].record_id == target.id

    refreshed_other = await db.get(Record, other.id)
    assert refreshed_other.status == RecordStatus.PENDING.value


async def test_run_batch_record_id_not_found_raises(db: AsyncSession) -> None:
    with pytest.raises(ValueError, match="not found"):
        await run_batch(db, record_id=999999)


async def test_run_batch_record_id_not_pending_raises(db: AsyncSession, make_record) -> None:
    record = await make_record()
    record.status = RecordStatus.RESOLVED.value
    await db.flush()

    with pytest.raises(ValueError, match="not pending"):
        await run_batch(db, record_id=record.id)


async def test_run_batch_continues_past_a_failed_record(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    def responder(kwargs: dict[str, Any]) -> Any:
        if "boom" in kwargs["user_message"]:
            raise RuntimeError("simulated LLM failure")
        return _responder(kwargs)

    fake_llm.set_responder(responder)
    await make_record(external_ref="broken", raw_content="boom, this will explode")
    await make_record(external_ref="clear", raw_content="service my area please")

    summary = await run_batch(db)

    assert summary.total == 2
    assert summary.failed == 1
    assert summary.auto_routed == 1
    statuses = {o.external_ref: o.status for o in summary.outcomes}
    assert statuses["broken"] == RecordStatus.FAILED.value
    assert statuses["clear"] == RecordStatus.AUTO_ROUTED.value


async def test_run_batch_on_error_receives_the_record_and_exception(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    def responder(kwargs: dict[str, Any]) -> Any:
        if "boom" in kwargs["user_message"]:
            raise RuntimeError("simulated LLM failure")
        return _responder(kwargs)

    fake_llm.set_responder(responder)
    broken = await make_record(external_ref="broken", raw_content="boom, this will explode")
    await make_record(external_ref="clear", raw_content="service my area please")

    errors: list[tuple[int, Exception]] = []
    summary = await run_batch(
        db, on_error=lambda record, exc: errors.append((record.id, exc))
    )

    assert summary.failed == 1
    assert len(errors) == 1
    assert errors[0][0] == broken.id
    assert isinstance(errors[0][1], RuntimeError)
    assert str(errors[0][1]) == "simulated LLM failure"


async def test_run_batch_without_on_error_still_continues_past_failures(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    def responder(kwargs: dict[str, Any]) -> Any:
        if "boom" in kwargs["user_message"]:
            raise RuntimeError("simulated LLM failure")
        return _responder(kwargs)

    fake_llm.set_responder(responder)
    await make_record(external_ref="broken", raw_content="boom, this will explode")
    await make_record(external_ref="clear", raw_content="service my area please")

    summary = await run_batch(db)

    assert summary.failed == 1
    assert summary.auto_routed == 1


async def test_compute_stats_matches_a_batch_run(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    fake_llm.set_responder(_responder)
    await make_record(external_ref="clear", raw_content="service my area please")
    await make_record(external_ref="vague", raw_content="hey, following up on the thing")

    assert await compute_stats(db) == {
        "total": 0,
        "auto_routed": 0,
        "needs_review": 0,
        "failed": 0,
        "auto_route_pct": 0.0,
    }

    await run_batch(db)
    stats = await compute_stats(db)

    assert stats["total"] == 2
    assert stats["auto_routed"] == 1
    assert stats["needs_review"] == 1
    assert stats["failed"] == 0
    assert stats["auto_route_pct"] == 50.0
