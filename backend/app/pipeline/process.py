from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Record, RoutingDecision
from app.models.enums import DecidedBy, RecordStatus
from app.pipeline.audit import write_audit_log
from app.pipeline.classify import classify_record
from app.pipeline.confidence import compute_confidence
from app.pipeline.extract import extract_record
from app.pipeline.rules import evaluate_rules


def load_categories() -> list[dict[str, Any]]:
    with open(settings.categories_path, encoding="utf-8") as f:
        return yaml.safe_load(f)["categories"]


async def process_record(record_id: int, db: AsyncSession) -> Record:
    """Runs one record through the full pipeline: classify -> extract -> required-field
    check -> confidence -> rules -> final status. Any unexpected exception is recorded
    on the record (status='failed', an audit_log row with the error) and then
    re-raised — failures are visible, never swallowed."""
    record = await db.get(Record, record_id)
    if record is None:
        raise ValueError(f"Record {record_id} not found")

    try:
        record.status = RecordStatus.PROCESSING.value
        await write_audit_log(db, record_id=record.id, actor="system", action="processing_started")

        categories = load_categories()
        classification = await classify_record(record, categories, db)

        extract_outcome = await extract_record(record, classification.category, db)
        extraction = extract_outcome.extraction

        if extract_outcome.missing_required_fields:
            record.status = RecordStatus.NEEDS_REVIEW.value
            await write_audit_log(
                db,
                record_id=record.id,
                actor="system",
                action="forced_review_missing_fields",
                after={"missing_fields": extract_outcome.missing_required_fields},
            )
            await db.flush()
            return record

        confidence = compute_confidence(classification, extraction)

        if confidence < settings.confidence_threshold:
            record.status = RecordStatus.NEEDS_REVIEW.value
            await write_audit_log(
                db,
                record_id=record.id,
                actor="system",
                action="needs_review_low_confidence",
                after={"confidence": confidence, "threshold": settings.confidence_threshold},
            )
            await db.flush()
            return record

        outcome = await evaluate_rules(classification.category, extraction.fields, db)

        if outcome.requires_review:
            record.status = RecordStatus.NEEDS_REVIEW.value
            await write_audit_log(
                db,
                record_id=record.id,
                actor="system",
                action="forced_review_by_rule",
                after={
                    "rule_id": outcome.matched_rule.id if outcome.matched_rule else None,
                    "rule_name": outcome.matched_rule.name if outcome.matched_rule else None,
                },
            )
            await db.flush()
            return record

        db.add(
            RoutingDecision(
                record_id=record.id,
                rule_id=outcome.matched_rule.id if outcome.matched_rule else None,
                destination=outcome.destination,
                decided_by=DecidedBy.SYSTEM.value,
            )
        )
        record.status = RecordStatus.AUTO_ROUTED.value
        await write_audit_log(
            db,
            record_id=record.id,
            actor="system",
            action="auto_routed",
            after={"destination": outcome.destination},
        )
        await db.flush()
        return record

    except Exception as exc:
        record.status = RecordStatus.FAILED.value
        await write_audit_log(
            db, record_id=record.id, actor="system", action="failed", after={"error": str(exc)}
        )
        await db.flush()
        raise
