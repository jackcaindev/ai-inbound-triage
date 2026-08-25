import csv
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Record, Rule, Source
from app.models.enums import RecordStatus
from app.pipeline.ingest import ingest_csv
from app.pipeline.process import process_record
from app.schemas.classification import ClassificationResult
from app.schemas.extraction import BaseExtractionFields
from tests.conftest import FakeLLMController

ROWS = [
    {
        "external_ref": "e2e-clear-inquiry",
        "raw_content": "Hi, I'd like to know if you service my area, no rush.",
        "received_at": "2026-01-01T00:00:00",
    },
    {
        "external_ref": "e2e-vague",
        "raw_content": "hey, following up on the thing",
        "received_at": "2026-01-01T00:00:00",
    },
    {
        "external_ref": "e2e-high-dollar",
        "raw_content": "We'd like to proceed with the $50,000 retrofit quote you sent.",
        "received_at": "2026-01-01T00:00:00",
    },
    {
        "external_ref": "e2e-support",
        "raw_content": "The unit is rattling again, can someone come out this week?",
        "received_at": "2026-01-01T00:00:00",
    },
]

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
    (
        "$50,000 retrofit",
        "billing_question",
        0.97,
        {
            "contact_name": "Casey",
            "company": "Casey LLC",
            "requested_action": "approve quote",
            "urgency": "medium",
            "dates_mentioned": [],
            "dollar_amounts_mentioned": [50000],
        },
    ),
    (
        "rattling again",
        "support_issue",
        0.90,
        {
            "contact_name": "Drew",
            "company": None,
            "requested_action": "repair visit",
            "urgency": "high",
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


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["external_ref", "raw_content", "received_at"])
        writer.writeheader()
        writer.writerows(rows)
    return path


async def test_seeded_batch_processes_end_to_end(
    db: AsyncSession, source: Source, tmp_path: Path, fake_llm: FakeLLMController
) -> None:
    """Mirrors the Phase 1 acceptance criterion: a seeded batch processes end to end,
    low-confidence records land in needs_review, and so do rule-flagged records —
    everything else reaches auto_routed."""
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

    csv_path = _write_csv(tmp_path / "batch.csv", ROWS)
    ingest_result = await ingest_csv(source, csv_path, db)
    assert ingest_result.created == len(ROWS)

    fake_llm.set_responder(_responder)

    pending = (
        await db.execute(select(Record).where(Record.source_id == source.id))
    ).scalars().all()
    for record in pending:
        await process_record(record.id, db)

    statuses = {
        r.external_ref: r.status
        for r in (
            await db.execute(select(Record).where(Record.source_id == source.id))
        ).scalars().all()
    }

    # Nothing is left pending/processing/failed — every record reached a terminal
    # decision.
    assert set(statuses.values()) <= {
        RecordStatus.AUTO_ROUTED.value,
        RecordStatus.NEEDS_REVIEW.value,
    }

    assert statuses["e2e-clear-inquiry"] == RecordStatus.AUTO_ROUTED.value
    assert statuses["e2e-support"] == RecordStatus.AUTO_ROUTED.value
    assert statuses["e2e-vague"] == RecordStatus.NEEDS_REVIEW.value  # low confidence
    assert statuses["e2e-high-dollar"] == RecordStatus.NEEDS_REVIEW.value  # rule-forced
