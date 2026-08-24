from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Classification, Extraction, Record
from app.models.enums import RecordStatus
from app.pipeline.confidence import compute_confidence
from app.pipeline.process import process_record
from tests.conftest import FakeLLMController


def test_floor_rule_caps_confidence_when_extraction_mostly_empty() -> None:
    classification = Classification(
        record_id=1,
        category="new_inquiry",
        confidence=0.95,
        model="test",
        prompt_version="v1",
        raw_response={},
        latency_ms=1,
    )
    extraction = Extraction(
        record_id=1, schema_version="v1", fields={}, confidence=0.16, model="test", raw_response={}
    )

    assert compute_confidence(classification, extraction) == 0.5


def test_confidence_unaffected_when_extraction_mostly_populated() -> None:
    classification = Classification(
        record_id=1,
        category="new_inquiry",
        confidence=0.95,
        model="test",
        prompt_version="v1",
        raw_response={},
        latency_ms=1,
    )
    extraction = Extraction(
        record_id=1, schema_version="v1", fields={}, confidence=0.83, model="test", raw_response={}
    )

    assert compute_confidence(classification, extraction) == 0.95


async def test_low_confidence_record_lands_in_needs_review(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    record: Record = await make_record(raw_content="Not sure what this is about, kind of vague.")
    fake_llm.set_classification(category="new_inquiry", confidence=0.4)
    fake_llm.set_extraction(
        contact_name=None,
        company=None,
        requested_action=None,
        urgency=None,
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )

    result = await process_record(record.id, db)

    assert result.status == RecordStatus.NEEDS_REVIEW.value
