from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Classification, EvalExample, Extraction, Record, RoutingDecision
from app.models.enums import DecidedBy, EvalSource, RecordStatus
from app.pipeline.audit import write_audit_log

ReviewDecision = Literal["accept", "correct", "reject"]


async def submit_review_decision(
    record_id: int,
    decision: ReviewDecision,
    db: AsyncSession,
    *,
    corrected_category: str | None = None,
    corrected_fields: dict[str, Any] | None = None,
    destination: str | None = None,
    reviewer: str = "reviewer",
    note: str | None = None,
) -> Record:
    """The reviewer accepts, corrects, or rejects the model's output.

    accept/correct: writes a routing_decisions row (decided_by='human') and an
    eval_examples row (source='human_correction') — this is what closes the loop and
    feeds the eval set, whether or not the reviewer actually changed anything. reject:
    the record is resolved with no routing and no eval example (there is no confirmed
    ground truth to learn from).
    """
    record = await db.get(Record, record_id)
    if record is None:
        raise ValueError(f"Record {record_id} not found")

    latest_classification = await _latest(db, Classification, record_id)
    latest_extraction = await _latest(db, Extraction, record_id)

    before = {
        "category": latest_classification.category if latest_classification else None,
        "fields": latest_extraction.fields if latest_extraction else None,
    }

    if decision == "reject":
        record.status = RecordStatus.RESOLVED.value
        await write_audit_log(
            db,
            record_id=record.id,
            actor=reviewer,
            action="human_reviewed",
            before=before,
            after={"decision": "reject", "note": note},
        )
        await db.flush()
        return record

    final_category = corrected_category or (
        latest_classification.category if latest_classification else None
    )
    final_fields = (
        corrected_fields
        if corrected_fields is not None
        else (latest_extraction.fields if latest_extraction else {})
    )
    if final_category is None:
        raise ValueError("No category available: record was never classified and none was provided")

    db.add(
        RoutingDecision(
            record_id=record.id,
            rule_id=None,
            destination=destination or final_category,
            decided_by=DecidedBy.HUMAN.value,
            reviewer_note=note,
        )
    )
    db.add(
        EvalExample(
            record_id=record.id,
            expected_category=final_category,
            expected_fields=final_fields,
            source=EvalSource.HUMAN_CORRECTION.value,
        )
    )

    record.status = RecordStatus.RESOLVED.value
    await write_audit_log(
        db,
        record_id=record.id,
        actor=reviewer,
        action="human_reviewed",
        before=before,
        after={"decision": decision, "category": final_category, "fields": final_fields, "note": note},
    )
    await db.flush()
    return record


async def _latest(
    db: AsyncSession, model: type[Classification] | type[Extraction], record_id: int
) -> Classification | Extraction | None:
    result = await db.execute(
        select(model).where(model.record_id == record_id).order_by(model.created_at.desc()).limit(1)
    )
    return result.scalars().first()
