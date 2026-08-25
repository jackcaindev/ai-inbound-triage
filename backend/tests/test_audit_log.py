import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Record
from app.models.enums import RecordStatus
from app.pipeline.process import process_record
from tests.conftest import FakeLLMController


async def test_audit_log_entries_written_at_each_pipeline_stage(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    record: Record = await make_record(raw_content="Hi, quote for a new install please.")
    fake_llm.set_classification(category="new_inquiry", confidence=0.95)
    fake_llm.set_extraction(
        contact_name="Rae",
        company="Rae Co",
        requested_action="quote",
        urgency="low",
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )

    await process_record(record.id, db)

    entries = (
        await db.execute(select(AuditLog).where(AuditLog.record_id == record.id).order_by(AuditLog.id))
    ).scalars().all()
    actions = [e.action for e in entries]
    assert actions == ["processing_started", "classified", "extracted", "auto_routed"]


async def test_process_record_marks_failed_and_reraises_on_unexpected_error(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    """Failures are visible: an unexpected exception must not be swallowed — it's
    recorded on the record and audit_log, then re-raised to the caller."""
    record: Record = await make_record(raw_content="whatever")
    # fake_llm is active but never configured with a classification, so
    # classify_record blows up accessing .category on None — an unexpected error.

    with pytest.raises(AttributeError):
        await process_record(record.id, db)

    await db.refresh(record)
    assert record.status == RecordStatus.FAILED.value

    entries = (
        await db.execute(select(AuditLog).where(AuditLog.record_id == record.id))
    ).scalars().all()
    assert any(e.action == "failed" for e in entries)
