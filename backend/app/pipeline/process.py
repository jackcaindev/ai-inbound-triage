from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Record, RoutingDecision
from app.models.enums import DecidedBy, RecordStatus
from app.pipeline.audit import write_audit_log
from app.pipeline.classify import classify_record
from app.pipeline.confidence import classification_below_threshold
from app.pipeline.extract import extract_record
from app.pipeline.rules import evaluate_rules

NEEDS_REVIEW_DESTINATION = "needs_review"


def load_categories() -> list[dict[str, Any]]:
    with open(settings.categories_path, encoding="utf-8") as f:
        return yaml.safe_load(f)["categories"]


async def _route_to_review(
    db: AsyncSession,
    record: Record,
    *,
    reason: str,
    rule_id: int | None,
    destination: str,
    audit_action: str,
    audit_after: dict[str, Any],
) -> None:
    """Every record that lands in needs_review still gets a routing_decisions row —
    reviewers and the eval harness need to see *why* it stopped, not just that it did."""
    db.add(
        RoutingDecision(
            record_id=record.id,
            rule_id=rule_id,
            destination=destination,
            decided_by=DecidedBy.SYSTEM.value,
            reason=reason,
        )
    )
    record.status = RecordStatus.NEEDS_REVIEW.value
    await write_audit_log(
        db, record_id=record.id, actor="system", action=audit_action, after=audit_after
    )
    await db.flush()


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
            field = extract_outcome.missing_required_fields[0]
            await _route_to_review(
                db,
                record,
                reason=f"missing_required_field:{field}",
                rule_id=None,
                destination=NEEDS_REVIEW_DESTINATION,
                audit_action="forced_review_missing_fields",
                audit_after={"missing_fields": extract_outcome.missing_required_fields},
            )
            return record

        if classification_below_threshold(classification, settings.confidence_threshold):
            await _route_to_review(
                db,
                record,
                reason="low_classification_confidence",
                rule_id=None,
                destination=NEEDS_REVIEW_DESTINATION,
                audit_action="needs_review_low_confidence",
                audit_after={
                    "confidence": classification.confidence,
                    "threshold": settings.confidence_threshold,
                },
            )
            return record

        outcome = await evaluate_rules(classification.category, extraction.fields, db)

        if outcome.requires_review:
            assert outcome.matched_rule is not None  # requires_review only true on a match
            await _route_to_review(
                db,
                record,
                reason="rule",
                rule_id=outcome.matched_rule.id,
                destination=outcome.destination,
                audit_action="forced_review_by_rule",
                audit_after={
                    "rule_id": outcome.matched_rule.id,
                    "rule_name": outcome.matched_rule.name,
                },
            )
            return record

        db.add(
            RoutingDecision(
                record_id=record.id,
                rule_id=outcome.matched_rule.id if outcome.matched_rule else None,
                destination=outcome.destination,
                decided_by=DecidedBy.SYSTEM.value,
                reason="rule" if outcome.matched_rule else "auto",
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
